# Copyright (c) 2026, Framras and contributors
# License: MIT
"""Cari Eşleştirme (Party Link) raporu: 120 Alıcılar + 320 Satıcılar tek satırda, asıl cari üzerinden.

TRY/döviz ayrımı, KDV oran kırılımı (191/391), çek/senet (101/103/121/321), mahsup fişi ve
cari hesap mutabakat mektubu verisi. Alacak (+), borç (-); Net = Alacak - Borç.
KDV tutarı hesaplanmaz; yalnızca açık faturaların mevcut vergi satırları oranlanır.
"""

from __future__ import annotations

from collections import defaultdict

import frappe
from erpnext.accounts.party import get_party_account
from erpnext.accounts.report.accounts_receivable.accounts_receivable import ReceivablePayableReport
from erpnext.accounts.utils import get_balance_on
from frappe import _
from frappe.utils import flt, getdate, today

from erpnext_tr.setup import _norm

AGE = ["range1", "range2", "range3", "range4", "range5"]

# KDV rates reported in their own column. Everything else goes to "KDV Other".
KDV_RATES = (1, 10, 20)
DEFAULT_KDV_PREFIXES = "391,191"  # Hesaplanan KDV, Indirilecek KDV

# Çek / Senet account groups (matched on Account.account_number prefix)
CHEQUE_GROUPS = {
	"bal_101": "101",  # Alinan Cekler
	"bal_103": "103",  # Verilen Cekler ve Odeme Emirleri (-)
	"bal_121": "121",  # Alacak Senetleri
	"bal_321": "321",  # Borc Senetleri
}

CUSTOM_FILTER_KEYS = ("view", "only_linked", "kdv_prefixes", "party")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def execute(filters=None):
	filters = prepare_filters(filters)
	link_map = get_party_link_map()

	rows = get_open_rows(filters, link_map)
	add_kdv(rows, filters)

	if filters.view == "Detailed":
		return get_detailed_columns(filters), get_detailed_data(rows, filters)

	cheques = get_cheque_balances(filters, link_map)
	return get_summary_columns(filters), get_summary_data(rows, cheques, filters, link_map)


def prepare_filters(filters):
	filters = frappe._dict(filters or {})
	filters.company = filters.get("company") or frappe.defaults.get_user_default("Company")
	filters.report_date = filters.get("report_date") or today()
	filters.ageing_based_on = filters.get("ageing_based_on") or "Due Date"
	filters.range = filters.get("range") or "30, 60, 90, 120"
	filters.view = filters.get("view") or "Summary"
	filters.kdv_prefixes = filters.get("kdv_prefixes") or DEFAULT_KDV_PREFIXES
	if not filters.company:
		frappe.throw(_("Şirket zorunludur"))
	return filters


# --------------------------------------------------------------------------- #
# Party Link helpers
# --------------------------------------------------------------------------- #
def accounts_by_prefix(company, prefix, leaf_only=False):
	"""Hesap numarası (nokta/boşluk yok sayılarak) prefix ile başlayan hesaplar."""
	rows = frappe.get_all(
		"Account", filters={"company": company}, fields=["name", "account_number", "is_group"]
	)
	return [
		r.name
		for r in rows
		if _norm(r.account_number).startswith(_norm(prefix)) and not (leaf_only and r.is_group)
	]


def get_party_link_map():
	"""{(role, party): (primary_role, primary_party)} for both sides of every Party Link."""
	out = {}
	for d in frappe.get_all(
		"Party Link", fields=["primary_role", "primary_party", "secondary_role", "secondary_party"]
	):
		primary = (d.primary_role, d.primary_party)
		out[primary] = primary
		out[(d.secondary_role, d.secondary_party)] = primary
	return out


def resolve(role, party, link_map):
	return link_map.get((role, party), (role, party))


def party_label(role, party):
	field = "customer_name" if role == "Customer" else "supplier_name"
	return frappe.db.get_value(role, party, field) or party


def wanted_parties(filters, link_map):
	"""Expand the 'Primary Party' filter to the Customer and Supplier records behind it."""
	if not filters.get("party"):
		return None
	members = {k for k, v in link_map.items() if v[1] == filters.party}
	if not members:
		members = {("Customer", filters.party), ("Supplier", filters.party)}
	return {
		"Customer": [p for t, p in members if t == "Customer"],
		"Supplier": [p for t, p in members if t == "Supplier"],
	}


# --------------------------------------------------------------------------- #
# Open items from the core AR / AP engines (detailed mode)
# --------------------------------------------------------------------------- #
def get_open_rows(filters, link_map):
	company_ccy = frappe.get_cached_value("Company", filters.company, "default_currency")
	wanted = wanted_parties(filters, link_map)
	out = []

	for side, party_type, sign, naming in (
		("Receivable", "Customer", 1, ["Selling Settings", "cust_master_name"]),
		("Payable", "Supplier", -1, ["Buying Settings", "supp_master_name"]),
	):
		f = frappe._dict({k: v for k, v in filters.items() if k not in CUSTOM_FILTER_KEYS})
		f.party_type = party_type
		if wanted is not None:
			if not wanted[party_type]:
				continue
			f.party = wanted[party_type]

		result = ReceivablePayableReport(f).run({"account_type": side, "naming_by": naming})
		data = result[1] or []

		for r in data:
			party = r.get("party")
			if not party or not r.get("voucher_no"):
				continue
			role, primary = resolve(party_type, party, link_map)
			ccy = r.get("currency") or company_ccy
			is_fx = ccy != company_ccy
			raw = flt(r.get("outstanding"))
			row = frappe._dict(
				side=side,
				sign=sign,
				party_type=party_type,
				party=party,
				primary_role=role,
				primary_party=primary,
				voucher_type=r.get("voucher_type"),
				voucher_no=r.get("voucher_no"),
				posting_date=r.get("posting_date"),
				due_date=r.get("due_date"),
				age=r.get("age"),
				currency=ccy,
				raw_outstanding=raw,
				outstanding=sign * raw,
				outstanding_fx=sign * flt(r.get("outstanding_in_account_currency")) if is_fx else 0.0,
			)
			for a in AGE:
				row[a] = sign * flt(r.get(a))
			out.append(row)
	return out


# --------------------------------------------------------------------------- #
# KDV breakdown (proportional share of the tax rows in the open amount)
# --------------------------------------------------------------------------- #
def add_kdv(rows, filters):
	keys = [f"kdv_{r}" for r in KDV_RATES] + ["kdv_other"]
	for r in rows:
		for k in keys:
			r[k] = 0.0
		r.kdv_total = 0.0

	prefixes = [p.strip() for p in str(filters.kdv_prefixes).split(",") if p.strip()]
	accounts = set()
	for p in prefixes:
		accounts.update(accounts_by_prefix(filters.company, p))

	if accounts:
		for doctype, tax_doctype in (
			("Sales Invoice", "Sales Taxes and Charges"),
			("Purchase Invoice", "Purchase Taxes and Charges"),
		):
			subset = [r for r in rows if r.voucher_type == doctype and r.raw_outstanding]
			if not subset:
				continue
			names = list({r.voucher_no for r in subset})
			inv = {
				d.name: d
				for d in frappe.get_all(
					doctype,
					filters={"name": ["in", names]},
					fields=["name", "base_grand_total", "base_net_total"],
				)
			}
			taxes = defaultdict(list)
			for t in frappe.get_all(
				tax_doctype,
				filters={
					"parent": ["in", names],
					"parenttype": doctype,
					"account_head": ["in", list(accounts)],
				},
				fields=["parent", "rate", "base_tax_amount_after_discount_amount as amount"],
			):
				taxes[t.parent].append(t)

			for r in subset:
				i = inv.get(r.voucher_no)
				if not i or not flt(i.base_grand_total):
					continue
				share = r.raw_outstanding / flt(i.base_grand_total)
				for t in taxes.get(r.voucher_no, []):
					amt = flt(t.amount)
					rate = flt(t.rate)
					if not rate and flt(i.base_net_total):
						rate = abs(amt) / abs(flt(i.base_net_total)) * 100
					bucket = f"kdv_{round(rate)}" if round(rate) in KDV_RATES else "kdv_other"
					val = r.sign * share * amt
					r[bucket] += val
					r.kdv_total += val

	for r in rows:
		r.net_excl_kdv = r.outstanding - r.kdv_total


# --------------------------------------------------------------------------- #
# Çek / Senet balances (GL based, party level)
# --------------------------------------------------------------------------- #
def get_cheque_balances(filters, link_map):
	"""{(primary_role, primary_party): {bal_101: x, ...}}  Debit - Credit, company currency.
	Only GL entries that carry a Party are attributable to a party."""
	out = defaultdict(lambda: {k: 0.0 for k in CHEQUE_GROUPS})
	for field, prefix in CHEQUE_GROUPS.items():
		accounts = accounts_by_prefix(filters.company, prefix, leaf_only=True)
		if not accounts:
			continue
		res = frappe.db.sql(
			"""
			select party_type, party, sum(debit - credit) as bal
			from `tabGL Entry`
			where company = %s and is_cancelled = 0 and posting_date <= %s
				and account in %s and ifnull(party, '') != ''
			group by party_type, party
			""",
			(filters.company, getdate(filters.report_date), tuple(accounts)),
			as_dict=True,
		)
		for d in res:
			key = resolve(d.party_type, d.party, link_map)
			out[key][field] += flt(d.bal)
	return out


# --------------------------------------------------------------------------- #
# Summary
# --------------------------------------------------------------------------- #
def new_bucket(key, primaries):
	b = frappe._dict(
		primary_role=key[0],
		primary_party=key[1],
		primary_party_name=party_label(*key),
		linked=1 if key in primaries else 0,
		rec_outstanding=0.0,
		pay_outstanding=0.0,
		net_outstanding=0.0,
		fx_try=0.0,
		fx={},
		cheque_total=0.0,
		kdv_total=0.0,
	)
	for a in AGE:
		b[f"net_{a}"] = 0.0
	for k in [f"kdv_{r}" for r in KDV_RATES] + ["kdv_other"] + list(CHEQUE_GROUPS):
		b[k] = 0.0
	return b


def get_summary_data(rows, cheques, filters, link_map):
	primaries = set(link_map.values())
	buckets = {}

	def get(key):
		if key not in buckets:
			buckets[key] = new_bucket(key, primaries)
		return buckets[key]

	for r in rows:
		b = get((r.primary_role, r.primary_party))
		if r.side == "Receivable":
			b.rec_outstanding += r.outstanding
		else:
			b.pay_outstanding += -r.outstanding
		b.net_outstanding += r.outstanding
		for a in AGE:
			b[f"net_{a}"] += r[a]
		for k in [f"kdv_{x}" for x in KDV_RATES] + ["kdv_other", "kdv_total"]:
			b[k] += r[k]
		if r.outstanding_fx:
			b.fx[r.currency] = b.fx.get(r.currency, 0.0) + r.outstanding_fx
			b.fx_try += r.outstanding

	for key, vals in cheques.items():
		if filters.get("party") and key[1] != filters.party:
			continue
		if not any(flt(v) for v in vals.values()):
			continue
		b = get(key)
		for k, v in vals.items():
			b[k] += v

	data = []
	for b in buckets.values():
		if filters.get("party") and b.primary_party != filters.party:
			continue
		if filters.get("only_linked") and not b.linked:
			continue
		b.try_native = b.net_outstanding - b.fx_try
		b.fx_detail = "; ".join(f"{c} {v:,.2f}" for c, v in sorted(b.fx.items()))
		b.net_excl_kdv = b.net_outstanding - b.kdv_total
		b.cheque_total = sum(b[k] for k in CHEQUE_GROUPS)
		b.exposure = b.net_outstanding + b.cheque_total
		b.net_position = (
			_("Net Alacak")
			if b.net_outstanding > 0
			else _("Net Borç")
			if b.net_outstanding < 0
			else _("Kapalı")
		)
		b.mahsup_amount = (
			min(b.rec_outstanding, b.pay_outstanding)
			if b.linked and b.rec_outstanding > 0 and b.pay_outstanding > 0
			else 0.0
		)
		data.append(b)

	data.sort(key=lambda r: abs(r.net_outstanding), reverse=True)

	if data:
		total = frappe._dict(primary_party=_("Total"), bold=1)
		sum_keys = (
			["rec_outstanding", "pay_outstanding", "net_outstanding", "try_native", "fx_try"]
			+ ["net_excl_kdv", "kdv_total", "kdv_other", "cheque_total", "exposure", "mahsup_amount"]
			+ [f"kdv_{x}" for x in KDV_RATES]
			+ list(CHEQUE_GROUPS)
			+ [f"net_{a}" for a in AGE]
		)
		for k in sum_keys:
			total[k] = sum(flt(r.get(k)) for r in data)
		data.append(total)
	return data


def age_labels(filters):
	rng = [int(x.strip()) for x in str(filters.range).split(",") if x.strip()]
	labels = [f"0-{rng[0]}"]
	labels += [f"{rng[i] + 1}-{rng[i + 1]}" for i in range(len(rng) - 1)]
	labels.append(f"{rng[-1]}-{_('Above')}")
	return labels


def cur(label, fieldname, width=120):
	return {"label": label, "fieldname": fieldname, "fieldtype": "Currency", "width": width}


def get_summary_columns(filters):
	cols = [
		{"label": _("İşlemler"), "fieldname": "actions", "fieldtype": "Data", "width": 150},
		{"label": _("Asıl Rol"), "fieldname": "primary_role", "fieldtype": "Data", "width": 85},
		{
			"label": _("Asıl Cari"),
			"fieldname": "primary_party",
			"fieldtype": "Dynamic Link",
			"options": "primary_role",
			"width": 150,
		},
		{"label": _("Cari Adı"), "fieldname": "primary_party_name", "fieldtype": "Data", "width": 190},
		{"label": _("Bağlı"), "fieldname": "linked", "fieldtype": "Check", "width": 55},
		cur(_("120 Alıcılar"), "rec_outstanding", 130),
		cur(_("320 Satıcılar"), "pay_outstanding", 130),
		cur(_("Net Bakiye"), "net_outstanding", 130),
		{"label": _("Durum"), "fieldname": "net_position", "fieldtype": "Data", "width": 105},
		cur(_("TL Belgeler"), "try_native", 125),
		cur(_("Döviz Belgeler (TL karşılığı)"), "fx_try", 140),
		{"label": _("Döviz Bakiye (orijinal)"), "fieldname": "fx_detail", "fieldtype": "Data", "width": 200},
	]
	for r in KDV_RATES:
		cols.append(cur(_("KDV %{0}").format(r), f"kdv_{r}", 105))
	cols += [
		cur(_("KDV Diğer"), "kdv_other", 100),
		cur(_("KDV Toplam"), "kdv_total", 110),
		cur(_("KDV Hariç Net"), "net_excl_kdv", 125),
		cur(_("101 Alınan Çekler"), "bal_101", 125),
		cur(_("103 Verilen Çekler"), "bal_103", 125),
		cur(_("121 Alacak Senetleri"), "bal_121", 125),
		cur(_("321 Borç Senetleri"), "bal_321", 125),
		cur(_("Çek/Senet Toplam"), "cheque_total", 125),
		cur(_("Çek/Senet Dahil Risk"), "exposure", 140),
		cur(_("Mahsup Tutarı"), "mahsup_amount", 115),
	]
	for a, lb in zip(AGE, age_labels(filters), strict=True):
		cols.append(cur(_("Net {0}").format(lb), f"net_{a}", 105))
	return cols


# --------------------------------------------------------------------------- #
# Detailed
# --------------------------------------------------------------------------- #
def get_detailed_data(rows, filters):
	data = []
	for r in rows:
		r.side_label = _("Alacak") if r.side == "Receivable" else _("Borç")
		data.append(r)
	data.sort(key=lambda x: (x.primary_party or "", str(x.posting_date or "")))
	return data


def get_detailed_columns(filters):
	cols = [
		{
			"label": _("Asıl Cari"),
			"fieldname": "primary_party",
			"fieldtype": "Dynamic Link",
			"options": "primary_role",
			"width": 150,
		},
		{"label": _("Taraf"), "fieldname": "side_label", "fieldtype": "Data", "width": 80},
		{
			"label": _("Gerçek Cari"),
			"fieldname": "party",
			"fieldtype": "Dynamic Link",
			"options": "party_type",
			"width": 140,
		},
		{"label": _("Tarih"), "fieldname": "posting_date", "fieldtype": "Date", "width": 95},
		{"label": _("Belge Tipi"), "fieldname": "voucher_type", "fieldtype": "Data", "width": 110},
		{
			"label": _("Belge No"),
			"fieldname": "voucher_no",
			"fieldtype": "Dynamic Link",
			"options": "voucher_type",
			"width": 150,
		},
		{"label": _("Vade"), "fieldname": "due_date", "fieldtype": "Date", "width": 95},
		{"label": _("Para Birimi"), "fieldname": "currency", "fieldtype": "Data", "width": 70},
		cur(_("İşaretli Bakiye (TL)"), "outstanding", 150),
		cur(_("İşaretli Bakiye (Döviz)"), "outstanding_fx", 140),
	]
	for r in KDV_RATES:
		cols.append(cur(_("KDV %{0}").format(r), f"kdv_{r}", 100))
	cols += [
		cur(_("KDV Diğer"), "kdv_other", 100),
		cur(_("KDV Hariç Net"), "net_excl_kdv", 120),
		{"label": _("Gün"), "fieldname": "age", "fieldtype": "Int", "width": 80},
	]
	for a, lb in zip(AGE, age_labels(filters), strict=True):
		cols.append(cur(lb, a, 100))
	return cols


# --------------------------------------------------------------------------- #
# Mahsup Journal Entry
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def mahsup_journal_entry(company, primary_role, primary_party, posting_date=None, amount=None, preview=0):
	"""Offset the receivable of the linked Customer against the payable of the linked Supplier.

	Dr  320 Supplier payable account  (party: Supplier)
	Cr  120 Customer receivable account (party: Customer)

	Creates a DRAFT Journal Entry. Allocate it to the invoices afterwards with
	Payment Reconciliation (once for the Customer, once for the Supplier).
	preview=1 returns the numbers without creating anything."""
	frappe.has_permission("Journal Entry", "create", throw=True)
	posting_date = getdate(posting_date or today())

	link = frappe.db.get_value(
		"Party Link",
		{"primary_role": primary_role, "primary_party": primary_party},
		["secondary_role", "secondary_party"],
		as_dict=True,
	)
	if not link:
		frappe.throw(
			_("{0} {1} asıl cari olan Cari Eşleştirme (Party Link) kaydı bulunamadı").format(
				primary_role, primary_party
			)
		)

	customer = primary_party if primary_role == "Customer" else link.secondary_party
	supplier = primary_party if primary_role == "Supplier" else link.secondary_party

	rec_acc = get_party_account("Customer", customer, company)
	pay_acc = get_party_account("Supplier", supplier, company)

	company_ccy = frappe.get_cached_value("Company", company, "default_currency")
	for acc in (rec_acc, pay_acc):
		if frappe.get_cached_value("Account", acc, "account_currency") != company_ccy:
			frappe.throw(
				_("Mahsup yalnızca {0} cinsinden hesaplarda desteklenir. {1} farklı para biriminde.").format(
					company_ccy, acc
				)
			)

	rec_bal = flt(
		get_balance_on(
			date=posting_date, account=rec_acc, party_type="Customer", party=customer, company=company
		)
	)
	pay_bal = -flt(
		get_balance_on(
			date=posting_date, account=pay_acc, party_type="Supplier", party=supplier, company=company
		)
	)
	if rec_bal <= 0 or pay_bal <= 0:
		frappe.throw(
			_("Mahsup edilecek tutar yok: alacak {0}, borç {1} ({2} itibarıyla)").format(
				rec_bal, pay_bal, posting_date
			)
		)

	maximum = min(rec_bal, pay_bal)
	amt = flt(amount) if amount else maximum
	if amt <= 0 or amt > maximum + 0.005:
		frappe.throw(_("Tutar 0 ile {0} arasında olmalıdır").format(maximum))

	info = {
		"customer": customer,
		"supplier": supplier,
		"receivable": rec_bal,
		"payable": pay_bal,
		"amount": amt,
		"currency": company_ccy,
	}
	if int(preview):
		return info

	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Journal Entry"
	je.company = company
	je.posting_date = posting_date
	je.user_remark = _("Mahsup: {0} (Müşteri) / {1} (Tedarikçi)").format(customer, supplier)
	je.append(
		"accounts",
		{"account": pay_acc, "party_type": "Supplier", "party": supplier, "debit_in_account_currency": amt},
	)
	je.append(
		"accounts",
		{"account": rec_acc, "party_type": "Customer", "party": customer, "credit_in_account_currency": amt},
	)
	je.insert()
	info["journal_entry"] = je.name
	return info


# --------------------------------------------------------------------------- #
# Data provider for the "Cari Hesap Mutabakat" print format
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def get_mutabakat_data(company, party_type, party, report_date=None):
	frappe.has_permission(party_type, "read", party, throw=True)
	link_map = get_party_link_map()
	role, primary = resolve(party_type, party, link_map)

	filters = prepare_filters(
		{"company": company, "report_date": report_date, "view": "Summary", "party": primary}
	)
	_cols, data = execute(filters)
	bucket = next(
		(b for b in data if not b.get("bold") and b.primary_role == role and b.primary_party == primary),
		None,
	) or new_bucket((role, primary), set(link_map.values()))

	company_doc = frappe.get_cached_doc("Company", company)
	bucket.update(
		company=company,
		company_name=company_doc.company_name,
		company_tax_id=company_doc.tax_id,
		company_currency=company_doc.default_currency,
		report_date=str(getdate(filters.report_date)),
		party_type=party_type,
		party=party,
		party_name=party_label(party_type, party),
		party_tax_id=frappe.db.get_value(party_type, party, "tax_id"),
		linked_counterparts=[
			f"{t}: {p}"
			for (t, p), v in link_map.items()
			if v == (role, primary) and (t, p) != (party_type, party)
		],
	)
	return bucket


# --------------------------------------------------------------------------- #
# Yazdırma biçimi kurulumu (after_migrate, idempotent)
# --------------------------------------------------------------------------- #
PRINT_FORMAT_NAME = "Cari Hesap Mutabakat"


def setup_print_formats() -> None:
	import os

	path = os.path.join(os.path.dirname(__file__), "templates", "print_formats", "cari_hesap_mutabakat.html")
	with open(path, encoding="utf-8") as f:
		html = f.read().replace("__API__", __name__)

	for doctype in ("Customer", "Supplier"):
		name = PRINT_FORMAT_NAME if doctype == "Customer" else f"{PRINT_FORMAT_NAME} (Supplier)"
		values = {
			"doc_type": doctype,
			"print_format_type": "Jinja",
			"custom_format": 1,
			"standard": "No",
			"disabled": 0,
			"html": html,
			"default_print_language": "tr",
		}
		if frappe.db.exists("Print Format", name):
			doc = frappe.get_doc("Print Format", name)
			doc.update(values)
			doc.save(ignore_permissions=True)
		else:
			frappe.get_doc({"doctype": "Print Format", "name": name, **values}).insert(
				ignore_permissions=True
			)
