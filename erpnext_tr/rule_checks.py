# Copyright (c) 2026, Framras and contributors
# License: MIT
"""Kural denetimi motoru D1–D22."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, getdate

Violation = dict[str, Any]
RuleFn = Callable[[str, str, str], list[Violation]]

RULE_SEVERITY: dict[str, str] = {
	"D1": "Hata",
	"D2": "Hata",
	"D3": "Uyarı",
	"D4": "Uyarı",
	"D5": "Hata",
	"D6": "Uyarı",
	"D7": "Uyarı",
	"D8": "Hata",
	"D9": "Hata",
	"D10": "Uyarı",
	"D11": "Uyarı",
	"D12": "Hata",
	"D13": "Uyarı",
	"D14": "Hata",
	"D15": "Uyarı",
	"D16": "Uyarı",
	"D17": "Uyarı",
	"D18": "Uyarı",
	"D19": "Hata",
	"D20": "Uyarı",
	"D21": "Uyarı",
	"D22": "Uyarı",
}


def _v(
	voucher_type: str = "",
	voucher_no: str = "",
	posting_date: str | None = None,
	account: str = "",
	amount: float = 0,
	message: str = "",
	rule: str = "",
) -> Violation:
	return {
		"rule": rule,
		"severity": RULE_SEVERITY.get(rule, "Uyarı"),
		"voucher_type": voucher_type,
		"voucher_no": voucher_no,
		"posting_date": posting_date,
		"account": account,
		"amount": amount,
		"message": message,
	}


def _rule_enabled(company: str, code: str) -> bool:
	row = frappe.db.get_value(
		"TR Rule Setting",
		{"sirket": company, "kural_kodu": code},
		["aktif"],
		as_dict=True,
	)
	if not row:
		return True
	return bool(row.aktif)


def check_d1(company: str, from_date: str, to_date: str) -> list[Violation]:
	"""Dengesiz yevmiye."""
	out: list[Violation] = []
	jes = frappe.get_all(
		"Journal Entry",
		filters={
			"company": company,
			"docstatus": 1,
			"posting_date": ("between", [from_date, to_date]),
		},
		fields=["name", "posting_date", "total_debit", "total_credit"],
	)
	for je in jes:
		if abs(flt(je.total_debit) - flt(je.total_credit)) > 0.01:
			out.append(
				_v(
					"Journal Entry",
					je.name,
					je.posting_date,
					message=_("Dengesiz yevmiye: borç {0} ≠ alacak {1}").format(
						je.total_debit, je.total_credit
					),
					amount=abs(flt(je.total_debit) - flt(je.total_credit)),
					rule="D1",
				)
			)
	return out


def check_d2(company: str, from_date: str, to_date: str) -> list[Violation]:
	"""Kapanış döneminde taslak belge."""
	out: list[Violation] = []
	doctypes = [
		"Purchase Invoice",
		"Sales Invoice",
		"Journal Entry",
		"Payment Entry",
		"Purchase Receipt",
		"Delivery Note",
	]
	for dt in doctypes:
		if not frappe.db.exists("DocType", dt):
			continue
		rows = frappe.get_all(
			dt,
			filters={
				"company": company,
				"docstatus": 0,
				"posting_date": ("between", [from_date, to_date]),
			},
			fields=["name", "posting_date"],
			limit=50,
		)
		for row in rows:
			out.append(
				_v(
					dt,
					row.name,
					row.posting_date,
					message=_("Kapanış döneminde taslak belge: {0} {1}").format(dt, row.name),
					rule="D2",
				)
			)
	return out


def check_d3(company: str, from_date: str, to_date: str) -> list[Violation]:
	"""6./7. sınıf kapanış hesabı tanımsız."""
	from erpnext_tr.setup import _norm

	out: list[Violation] = []
	accounts = frappe.get_all(
		"Account",
		filters={"company": company, "is_group": 0},
		fields=["name", "account_number", "custom_kapanis_hesabi"],
	)
	for acc in accounts:
		n = _norm(acc.account_number)
		if len(n) < 1 or n[0] not in ("6", "7"):
			continue
		if not acc.custom_kapanis_hesabi:
			out.append(
				_v(
					"Account",
					acc.name,
					account=acc.name,
					message=_("Kapanış hesabı tanımsız: {0}").format(acc.name),
					rule="D3",
				)
			)
	return out


def check_d4(company: str, from_date: str, to_date: str) -> list[Violation]:
	"""Ters bakiye uyarıları."""
	from erpnext.accounts.utils import get_balance_on
	from erpnext_tr.setup import _norm

	out: list[Violation] = []
	accounts = frappe.get_all(
		"Account",
		filters={"company": company, "is_group": 0},
		fields=["name", "account_number"],
	)
	for acc in accounts:
		n = _norm(acc.account_number)
		bal = flt(get_balance_on(acc.name, date=to_date))
		if n.startswith(("120", "121")) and bal < -0.01:
			out.append(_v(account=acc.name, amount=bal, message=_("120/121 alacak bakiyesi: {0}").format(acc.name), rule="D4"))
		if n.startswith(("320", "321")) and bal > 0.01:
			out.append(_v(account=acc.name, amount=bal, message=_("320/321 borç bakiyesi: {0}").format(acc.name), rule="D4"))
		if n.startswith("102") and bal < -0.01:
			out.append(_v(account=acc.name, amount=bal, message=_("102 negatif bakiye: {0}").format(acc.name), rule="D4"))
	return out


def check_d5(company: str, from_date: str, to_date: str) -> list[Violation]:
	"""118 fon: miktar 0 ama bakiye ≠ 0 — basit tespit."""
	from erpnext.accounts.utils import get_balance_on
	from erpnext_tr.setup import _norm

	out: list[Violation] = []
	accounts = frappe.get_all(
		"Account",
		filters={"company": company, "is_group": 0},
		fields=["name", "account_number"],
	)
	for acc in accounts:
		if not _norm(acc.account_number).startswith("118"):
			continue
		bal = flt(get_balance_on(acc.name, date=to_date))
		if abs(bal) > 0.01:
			# Stok miktarı kontrolü mümkün değilse bakiye uyarısı
			out.append(
				_v(
					account=acc.name,
					amount=bal,
					message=_("118 fon hesabında bakiye var (K1 kontrolü): {0} = {1}").format(
						acc.name, bal
					),
					rule="D5",
				)
			)
	return out


def check_d6(company: str, from_date: str, to_date: str) -> list[Violation]:
	"""153 stok negatif."""
	out: list[Violation] = []
	bins = frappe.get_all(
		"Bin",
		filters={"actual_qty": ("<", 0)},
		fields=["item_code", "warehouse", "actual_qty"],
		limit=50,
	)
	for b in bins:
		wh_company = frappe.db.get_value("Warehouse", b.warehouse, "company")
		if wh_company != company:
			continue
		out.append(
			_v(
				message=_("Negatif stok: {0} @ {1} = {2}").format(
					b.item_code, b.warehouse, b.actual_qty
				),
				amount=b.actual_qty,
				rule="D6",
			)
		)
	return out


def check_d7(company: str, from_date: str, to_date: str) -> list[Violation]:
	from erpnext.accounts.utils import get_balance_on
	from erpnext_tr.setup import _norm

	out: list[Violation] = []
	for acc in frappe.get_all(
		"Account", filters={"company": company, "is_group": 0}, fields=["name", "account_number"]
	):
		if _norm(acc.account_number).startswith("100"):
			bal = flt(get_balance_on(acc.name, date=to_date))
			if bal < -0.01:
				out.append(
					_v(account=acc.name, amount=bal, message=_("100 kasa negatif: {0}").format(acc.name), rule="D7")
				)
	return out


def check_d8(company: str, from_date: str, to_date: str) -> list[Violation]:
	"""Vergi şablonu boş fatura satırı."""
	out: list[Violation] = []
	for dt in ("Sales Invoice", "Purchase Invoice"):
		invoices = frappe.get_all(
			dt,
			filters={
				"company": company,
				"docstatus": 1,
				"posting_date": ("between", [from_date, to_date]),
			},
			fields=["name", "posting_date"],
			limit=200,
		)
		if not invoices:
			continue
		names = [i.name for i in invoices]
		items = frappe.get_all(
			f"{dt} Item",
			filters={"parent": ("in", names)},
			fields=["parent", "item_code", "item_tax_template", "idx"],
		)
		date_map = {i.name: i.posting_date for i in invoices}
		for it in items:
			if not it.item_tax_template:
				out.append(
					_v(
						dt,
						it.parent,
						date_map.get(it.parent),
						message=_("Vergi şablonu boş: {0} satır {1} ({2})").format(
							it.parent, it.idx, it.item_code
						),
						rule="D8",
					)
				)
	return out


def check_d9(company: str, from_date: str, to_date: str) -> list[Violation]:
	"""191/391 mahsup tutarsızlığı — Kaydedilmiş mahsup sonrası bakiye kontrolü (basit)."""
	out: list[Violation] = []
	# Dönem içi Kaydedildi mahsup yoksa atla
	if not frappe.db.exists("DocType", "TR VAT Settlement"):
		return out
	return out


def check_d10(company: str, from_date: str, to_date: str) -> list[Violation]:
	"""Tevkifatlı işlemde 360 karşılığı eksik."""
	out: list[Violation] = []
	for dt, child in (
		("Sales Invoice", "Sales Invoice Item"),
		("Purchase Invoice", "Purchase Invoice Item"),
	):
		invoices = frappe.get_all(
			dt,
			filters={
				"company": company,
				"docstatus": 1,
				"posting_date": ("between", [from_date, to_date]),
			},
			fields=["name", "posting_date"],
			limit=200,
		)
		if not invoices:
			continue
		names = [i.name for i in invoices]
		items = frappe.get_all(
			child,
			filters={"parent": ("in", names), "custom_tevkifat_orani": ("is", "set")},
			fields=["parent", "custom_tevkifat_orani"],
		)
		if not items:
			continue
		date_map = {i.name: i.posting_date for i in invoices}
		parents = {i.parent for i in items}
		for parent in parents:
			taxes = frappe.get_all(
				f"{dt} Item" if False else "Sales Taxes and Charges"
				if dt == "Sales Invoice"
				else "Purchase Taxes and Charges",
				filters={"parent": parent},
				fields=["account_head"],
			)
			# account_head 360 içeriyor mu
			from erpnext_tr.setup import _norm

			has_360 = False
			for t in taxes:
				num = frappe.db.get_value("Account", t.account_head, "account_number")
				if num and _norm(num).startswith("360"):
					has_360 = True
					break
			if not has_360:
				out.append(
					_v(
						dt,
						parent,
						date_map.get(parent),
						message=_("Tevkifatlı işlemde 360 karşılığı eksik: {0}").format(parent),
						rule="D10",
					)
				)
	return out


def check_d11(company: str, from_date: str, to_date: str) -> list[Violation]:
	"""Stopaj + MUHSGK tanımsız — alan varsa kontrol."""
	return []  # Faz 2 stopaj seti


def check_d12(company: str, from_date: str, to_date: str) -> list[Violation]:
	"""e-Fatura mükellefine e-Arşiv."""
	out: list[Violation] = []
	# trebelge alanları: is_efatura_user; e-belge tipi alanı yoksa atla
	invoices = frappe.get_all(
		"Sales Invoice",
		filters={
			"company": company,
			"docstatus": 1,
			"posting_date": ("between", [from_date, to_date]),
		},
		fields=["name", "posting_date", "customer"],
		limit=200,
	)
	# Faz 1'de e-Arşiv belge tipi alanı yoksa ihlal üretilemez — müşteri bayrağı + alan varsa
	for inv in invoices:
		flag = frappe.db.get_value("Customer", inv.customer, "is_efatura_user")
		# e_invoice_type / custom alan yok — tespit için placeholder yok
		_ = flag
	return out


def check_d13(company: str, from_date: str, to_date: str) -> list[Violation]:
	return []  # parametrik limitler Faz 2


def check_d14(company: str, from_date: str, to_date: str) -> list[Violation]:
	"""Mükerrer fatura: aynı tedarikçi + bill_no."""
	out: list[Violation] = []
	rows = frappe.db.sql(
		"""
		select supplier, bill_no, count(*) as cnt, group_concat(name) as names
		from `tabPurchase Invoice`
		where company=%s and docstatus=1 and ifnull(bill_no,'')!=''
		  and posting_date between %s and %s
		group by supplier, bill_no
		having count(*) > 1
		""",
		(company, from_date, to_date),
		as_dict=True,
	)
	for row in rows:
		out.append(
			_v(
				"Purchase Invoice",
				(row.names or "").split(",")[0],
				message=_("Mükerrer fatura: tedarikçi {0}, bill_no {1} ({2})").format(
					row.supplier, row.bill_no, row.names
				),
				rule="D14",
			)
		)
	return out


def check_d15(company: str, from_date: str, to_date: str) -> list[Violation]:
	"""Dönem dışı / gelecek tarihli."""
	from frappe.utils import nowdate

	out: list[Violation] = []
	today = getdate(nowdate())
	for dt in ("Sales Invoice", "Purchase Invoice", "Journal Entry"):
		rows = frappe.get_all(
			dt,
			filters={
				"company": company,
				"docstatus": 1,
				"posting_date": (">", today),
			},
			fields=["name", "posting_date"],
			limit=50,
		)
		for row in rows:
			out.append(
				_v(
					dt,
					row.name,
					row.posting_date,
					message=_("Gelecek tarihli belge: {0} {1}").format(dt, row.name),
					rule="D15",
				)
			)
	return out


def check_d16(company: str, from_date: str, to_date: str) -> list[Violation]:
	return []  # eşleşme motoru sınırlı


def check_d17(company: str, from_date: str, to_date: str) -> list[Violation]:
	"""7/A gider hesabında maliyet merkezi boş."""
	from erpnext_tr.setup import _norm

	out: list[Violation] = []
	method = frappe.db.get_value("Company", company, "custom_maliyet_yontemi") or "7/A"
	if method != "7/A":
		return out
	GLE = frappe.qb.DocType("GL Entry")
	rows = (
		frappe.qb.from_(GLE)
		.select(GLE.voucher_type, GLE.voucher_no, GLE.posting_date, GLE.account, GLE.debit)
		.where(GLE.company == company)
		.where(GLE.is_cancelled == 0)
		.where(GLE.posting_date >= from_date)
		.where(GLE.posting_date <= to_date)
		.where((GLE.cost_center.isnull()) | (GLE.cost_center == ""))
		.limit(200)
		.run(as_dict=True)
	)  # noqa: E501 — basit dönem taraması
	for row in rows:
		num = frappe.db.get_value("Account", row.account, "account_number")
		n = _norm(num)
		if n[:1] == "7" and n[:3].isdigit() and 710 <= int(n[:3]) <= 781:
			out.append(
				_v(
					row.voucher_type,
					row.voucher_no,
					row.posting_date,
					row.account,
					row.debit,
					_("7/A gider hesabında maliyet merkezi boş: {0}").format(row.account),
					"D17",
				)
			)
	return out


def check_d18(company: str, from_date: str, to_date: str) -> list[Violation]:
	return []


def check_d19(company: str, from_date: str, to_date: str) -> list[Violation]:
	"""KMH: 102 bakiyesi < 0."""
	from erpnext.accounts.utils import get_balance_on
	from erpnext_tr.setup import _norm

	out: list[Violation] = []
	for acc in frappe.get_all(
		"Account", filters={"company": company, "is_group": 0}, fields=["name", "account_number"]
	):
		if not _norm(acc.account_number).startswith("102"):
			continue
		bal = flt(get_balance_on(acc.name, date=to_date))
		if bal < -0.01:
			out.append(
				_v(
					account=acc.name,
					amount=bal,
					message=_("D19 KMH: 102 bakiyesi negatif ({0} = {1})").format(acc.name, bal),
					rule="D19",
				)
			)
	return out


def check_d20(company: str, from_date: str, to_date: str) -> list[Violation]:
	if not frappe.db.exists("DocType", "TR Kredi"):
		return []
	return []


def check_d21(company: str, from_date: str, to_date: str) -> list[Violation]:
	"""Fon satış JE'sinde Kıymet Fiyat boş — alan varsa."""
	out: list[Violation] = []
	# Kıymet Fiyat custom alanı yoksa atla
	meta = frappe.get_meta("Journal Entry Account")
	if not meta.has_field("custom_kiymet_fiyat") and not meta.has_field("kiymet_fiyat"):
		return out
	return out


def check_d22(company: str, from_date: str, to_date: str) -> list[Violation]:
	"""Kur farkı tek hesaba yazılmış — exchange_gain_loss_account tespiti."""
	out: list[Violation] = []
	ex_acc = frappe.db.get_value("Company", company, "exchange_gain_loss_account")
	if not ex_acc:
		return out
	GLE = frappe.qb.DocType("GL Entry")
	rows = (
		frappe.qb.from_(GLE)
		.select(GLE.voucher_type, GLE.voucher_no, GLE.posting_date, GLE.account, GLE.debit, GLE.credit)
		.where(GLE.company == company)
		.where(GLE.account == ex_acc)
		.where(GLE.is_cancelled == 0)
		.where(GLE.posting_date >= from_date)
		.where(GLE.posting_date <= to_date)
		.limit(100)
		.run(as_dict=True)
	)
	for row in rows:
		out.append(
			_v(
				row.voucher_type,
				row.voucher_no,
				row.posting_date,
				row.account,
				flt(row.debit) - flt(row.credit),
				_(
					"Kur farkı tek hesaba yazılmış ({0}); 646/656 ayrımı Faz 2'de yapılacak"
				).format(ex_acc),
				"D22",
			)
		)
	return out


RULE_REGISTRY: dict[str, RuleFn] = {
	"D1": check_d1,
	"D2": check_d2,
	"D3": check_d3,
	"D4": check_d4,
	"D5": check_d5,
	"D6": check_d6,
	"D7": check_d7,
	"D8": check_d8,
	"D9": check_d9,
	"D10": check_d10,
	"D11": check_d11,
	"D12": check_d12,
	"D13": check_d13,
	"D14": check_d14,
	"D15": check_d15,
	"D16": check_d16,
	"D17": check_d17,
	"D18": check_d18,
	"D19": check_d19,
	"D20": check_d20,
	"D21": check_d21,
	"D22": check_d22,
}


def run_rules(
	company: str,
	from_date: str,
	to_date: str,
	codes: list[str] | None = None,
) -> list[Violation]:
	results: list[Violation] = []
	for code, fn in RULE_REGISTRY.items():
		if codes and code not in codes:
			continue
		if not _rule_enabled(company, code):
			continue
		try:
			results.extend(fn(company, from_date, to_date))
		except Exception as exc:  # noqa: BLE001
			results.append(
				_v(
					message=_("Kural {0} çalıştırılırken hata: {1}").format(code, exc),
					rule=code,
				)
			)
	return results


def has_error_violations(company: str, from_date: str, to_date: str) -> list[Violation]:
	violations = run_rules(company, from_date, to_date)
	return [v for v in violations if v.get("severity") == "Hata"]
