# Copyright (c) 2026, Framras and contributors
# License: MIT
"""KMH (102) ön kontrolü ve bölüştürme yardımcısı — native balance_must_be'yi değiştirmez."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, nowdate

from erpnext_tr.setup import _norm


def _is_102_account(account: str) -> bool:
	number = frappe.db.get_value("Account", account, "account_number")
	return _norm(number).startswith("102")


def _bank_kmh_for_account(company: str, account: str) -> dict | None:
	"""Bank Account kartında bu 102 hesabına bağlı KMH bilgisi."""
	rows = frappe.get_all(
		"Bank Account",
		filters={"account": account, "company": company},
		fields=["name", "custom_kmh_hesabi", "custom_kmh_limiti"],
		limit=1,
	)
	if not rows:
		# company field may be absent on some versions — retry without
		rows = frappe.get_all(
			"Bank Account",
			filters={"account": account},
			fields=["name", "custom_kmh_hesabi", "custom_kmh_limiti"],
			limit=1,
		)
	if not rows or not rows[0].custom_kmh_hesabi:
		return None
	return rows[0]


def _current_balance(account: str) -> float:
	"""Anlık bakiye (borç − alacak)."""
	from erpnext.accounts.utils import get_balance_on

	return flt(get_balance_on(account))


def _kmh_credit_balance(kmh_account: str) -> float:
	bal = _current_balance(kmh_account)
	# Liability: credit balance is negative in debit-credit convention from get_balance_on
	# get_balance_on returns debit - credit for assets; for liability credit bal is negative
	return abs(min(bal, 0)) if bal < 0 else 0.0 if bal >= 0 else abs(bal)


def validate_kmh_on_payment(doc, method: str | None = None) -> None:
	"""Payment Entry / Journal Entry: 102 negatife düşecekse ve KMH bağlıysa paket mesajı."""
	company = doc.get("company")
	if not company:
		return

	# Toplanacak 102 etkileri
	impacts: dict[str, float] = {}

	if doc.doctype == "Payment Entry":
		paid_from = doc.get("paid_from")
		if paid_from and _is_102_account(paid_from):
			# Ödeme 102'den çıkış → credit → bakiye azalır
			impacts[paid_from] = impacts.get(paid_from, 0) - flt(doc.get("paid_amount") or doc.get("base_paid_amount"))
		paid_to = doc.get("paid_to")
		if paid_to and _is_102_account(paid_to):
			impacts[paid_to] = impacts.get(paid_to, 0) + flt(doc.get("received_amount") or doc.get("base_received_amount"))
	elif doc.doctype == "Journal Entry":
		for row in doc.get("accounts") or []:
			acc = row.get("account")
			if acc and _is_102_account(acc):
				delta = flt(row.get("debit_in_account_currency")) - flt(row.get("credit_in_account_currency"))
				impacts[acc] = impacts.get(acc, 0) + delta

	for account, delta in impacts.items():
		current = _current_balance(account)
		projected = current + delta
		if projected >= -0.00001:
			continue

		kmh = _bank_kmh_for_account(company, account)
		if not kmh:
			# Native ERPNext balance_must_be hatası devreye girer; paket sessiz
			continue

		limit = flt(kmh.custom_kmh_limiti)
		needed = abs(projected)
		kmh_name = kmh.custom_kmh_hesabi
		used = _kmh_credit_balance(kmh_name)
		if used + needed > limit + 0.00001:
			frappe.throw(
				_(
					"Bu ödeme 102 hesabını negatife düşürür (mevcut {0} TL, etki {1} TL). "
					"KMH hesabı {2} ile {3} TL karşılanabilir (limit {4} TL) — limit aşımı."
				).format(
					frappe.format_value(current, {"fieldtype": "Currency"}),
					frappe.format_value(abs(delta), {"fieldtype": "Currency"}),
					kmh_name,
					frappe.format_value(needed, {"fieldtype": "Currency"}),
					frappe.format_value(limit, {"fieldtype": "Currency"}),
				)
			)

		frappe.throw(
			_(
				"Bu ödeme 102 hesabını negatife düşürür (mevcut {0} TL, ödeme {1} TL). "
				"KMH hesabı {2} ile {3} TL karşılanabilir (limit {4} TL)."
			).format(
				frappe.format_value(current, {"fieldtype": "Currency"}),
				frappe.format_value(abs(delta), {"fieldtype": "Currency"}),
				kmh_name,
				frappe.format_value(needed, {"fieldtype": "Currency"}),
				frappe.format_value(limit, {"fieldtype": "Currency"}),
			)
		)


@frappe.whitelist()
def split_kmh_payment(payment_entry_name: str) -> str:
	"""Eksik tutar için KMH JV yazar; PE'yi değiştirmez."""
	frappe.has_permission("Payment Entry", doc=payment_entry_name, throw=True)
	pe = frappe.get_doc("Payment Entry", payment_entry_name)
	if pe.docstatus != 1:
		frappe.throw(_("Bölüştürme yalnızca gönderilmiş Payment Entry için çalışır: {0}").format(pe.name))

	account = pe.paid_from
	if not account or not _is_102_account(account):
		frappe.throw(_("Payment Entry {0} kaynağı 102 hesabı değil.").format(pe.name))

	kmh = _bank_kmh_for_account(pe.company, account)
	if not kmh:
		frappe.throw(_("Banka hesabında KMH hesabı tanımlı değil (102: {0}).").format(account))

	current = _current_balance(account)
	# PE zaten gönderilmiş — mevcut bakiye post-PE. Eksik = negatif kısım
	if current >= -0.00001:
		frappe.throw(
			_("102 hesabı {0} negatif değil (bakiye {1}); KMH JV gerekmiyor.").format(
				account, current
			)
		)

	shortage = abs(current)
	kmh_account = kmh.custom_kmh_hesabi
	limit = flt(kmh.custom_kmh_limiti)
	used = _kmh_credit_balance(kmh_account)
	if used + shortage > limit + 0.00001:
		frappe.throw(
			_(
				"KMH limit aşımı: mevcut kullanım {0} TL + {1} TL > limit {2} TL "
				"(KMH hesabı {3})."
			).format(used, shortage, limit, kmh_account)
		)

	# Dr: PE'nin karşı hesabı (varsa references / paid_to); Cr: KMH
	# Basit model: PE party hesabı veya paid_to
	debit_account = pe.paid_to
	if pe.payment_type == "Pay" and pe.get("party"):
		# Tedarikçi/ödeme: gider/borç — references yoksa paid_to kullan
		if pe.references:
			# leave as paid_to / party account resolution
			pass
	if not debit_account:
		frappe.throw(_("Payment Entry {0} için borçlandırılacak hesap (paid_to) boş.").format(pe.name))

	je = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"company": pe.company,
			"posting_date": nowdate(),
			"user_remark": _("KMH bölüştürme — PE {0}").format(pe.name),
			"accounts": [
				{
					"account": debit_account,
					"debit_in_account_currency": shortage,
					"credit_in_account_currency": 0,
					"party_type": pe.party_type,
					"party": pe.party,
				},
				{
					"account": kmh_account,
					"debit_in_account_currency": 0,
					"credit_in_account_currency": shortage,
				},
			],
		}
	)
	je.flags.ignore_permissions = True
	je.insert()
	je.submit()
	return je.name
