# Copyright (c) 2026, Framras and contributors
# License: MIT
"""Customer/Supplier tax_id (TCKN/VKN) ve MERSİS doğrulamaları; e-Fatura uyarısı."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint


def validate_tckn(value: str) -> bool:
	"""TCKN algoritması (11 hane)."""
	if not value or len(value) != 11 or not value.isdigit():
		return False
	digits = [int(ch) for ch in value]
	if digits[0] == 0:
		return False
	d10 = ((digits[0] + digits[2] + digits[4] + digits[6] + digits[8]) * 7 - (
		digits[1] + digits[3] + digits[5] + digits[7]
	)) % 10
	if d10 < 0:
		d10 = (d10 + 10) % 10
	d11 = sum(digits[:10]) % 10
	return digits[9] == d10 and digits[10] == d11


def validate_vkn(value: str) -> bool:
	"""VKN algoritması (10 hane)."""
	if not value or len(value) != 10 or not value.isdigit():
		return False
	digits = [int(ch) for ch in value]
	total = 0
	for i in range(1, 10):
		t = (digits[i - 1] + (10 - i)) % 10
		t = t * (2 ** (10 - i))
		if t > 9:
			t = (t % 10) + (t // 10)
		total += t
	check = (10 - (total % 10)) % 10
	return check == digits[9]


def validate_tax_id_value(tax_id: str | None) -> None:
	"""tax_id doluysa TCKN/VKN checksum doğrular; değer yazılmaz."""
	if not tax_id:
		return
	value = str(tax_id).strip()
	if not value.isdigit():
		frappe.throw(_("Vergi numarası yalnızca rakamlardan oluşmalıdır: {0}").format(value))
	if len(value) == 11:
		if not validate_tckn(value):
			frappe.throw(_("TCKN hatalı: {0}").format(value))
	elif len(value) == 10:
		if not validate_vkn(value):
			frappe.throw(_("VKN hatalı: {0}").format(value))
	else:
		frappe.throw(
			_("Vergi numarası 10 (VKN) veya 11 (TCKN) hane olmalıdır: {0}").format(value)
		)


def validate_mersis_no(mersis_no: str | None) -> None:
	"""MERSİS 16 haneli sayısal olmalıdır."""
	if not mersis_no:
		return
	value = str(mersis_no).strip()
	if len(value) != 16 or not value.isdigit():
		frappe.throw(_("MERSİS numarası 16 haneli sayısal olmalıdır: {0}").format(value))


def warn_mersis_tax_consistency(tax_id: str | None, mersis_no: str | None) -> None:
	"""Tüzel kişide VKN MERSİS içinde geçmiyorsa uyar (engellemez)."""
	if not tax_id or not mersis_no:
		return
	tax = str(tax_id).strip()
	mersis = str(mersis_no).strip()
	if len(tax) == 10 and tax.isdigit() and tax not in mersis:
		frappe.msgprint(
			_(
				"MERSİS numarası ({0}) vergi numarasını ({1}) içermiyor. "
				"Tüzel kişilerde MERSİS genelde VKN'yi barındırır; kaydı kontrol edin."
			).format(mersis, tax),
			indicator="orange",
			alert=True,
		)


def validate_party(doc, method: str | None = None) -> None:
	"""Customer / Supplier validate hook."""
	validate_tax_id_value(doc.get("tax_id"))
	mersis = doc.get("custom_mersis_no")
	validate_mersis_no(mersis)
	warn_mersis_tax_consistency(doc.get("tax_id"), mersis)


def validate_account_closing_fields(doc, method: str | None = None) -> None:
	"""Account: custom_kapanis_hesabi yalnızca 6./7. sınıf; aynı şirket; döngü yok."""
	target = doc.get("custom_kapanis_hesabi")
	if not target:
		return

	number = (doc.get("account_number") or "").replace(" ", "").replace(".", "")
	if not number or number[0] not in ("6", "7"):
		frappe.throw(
			_(
				"Kapanış hesabı yalnızca 6. veya 7. sınıf hesaplara yazılabilir. "
				"Hesap {0} (numara: {1}) uygun değil."
			).format(doc.name, doc.get("account_number") or "-")
		)

	target_company = frappe.db.get_value("Account", target, "company")
	if target_company and doc.company and target_company != doc.company:
		frappe.throw(
			_("Kaynak hesap ({0}) ile hedef kapanış hesabı ({1}) farklı şirketlere ait.").format(
				doc.name, target
			)
		)

	# Döngü: hedef zincirini takip et
	visited: set[str] = {doc.name}
	current = target
	while current:
		if current in visited:
			frappe.throw(
				_("Kapanış hesabı döngüsü tespit edildi: {0} → … → {1}").format(doc.name, current)
			)
		visited.add(current)
		current = frappe.db.get_value("Account", current, "custom_kapanis_hesabi")


def validate_sales_invoice_efatura(doc, method: str | None = None) -> None:
	"""Alıcının is_efatura_user bayrağı boşsa uyar (engelleme yok)."""
	if cint(doc.get("is_return")):
		return
	customer = doc.get("customer")
	if not customer:
		return
	flag = frappe.db.get_value("Customer", customer, "is_efatura_user")
	if flag in (None, ""):
		frappe.msgprint(
			_(
				"Müşteri {0} için e-Fatura mükellefiyet bayrağı (is_efatura_user) henüz "
				"sorgulanmamış. e-Fatura / e-Arşiv kararını kullanıcı verir; kayıt engellenmedi."
			).format(customer),
			indicator="orange",
			alert=True,
		)
