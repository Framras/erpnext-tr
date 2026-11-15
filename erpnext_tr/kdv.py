# Copyright (c) 2026, Framras and contributors
# License: MIT
"""KDV tevkifat seçimi (tutar hesaplamaz) + KDV mahsup matematiği."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import flt

from erpnext_tr.setup import _norm, find_account_by_number


def apply_tevkifat_template_selection(doc, method: str | None = None) -> None:
	"""Tevkifat oranına göre item_tax_template / account_head seçer; tutar yazmaz.

	A11: NEVER calculates withholding amount or writes tax amounts.
	"""
	if not doc.get("items"):
		return

	company = doc.get("company")
	if not company:
		return

	account_360 = _find_360_leaf(company)

	for item in doc.items:
		rate_link = item.get("custom_tevkifat_orani")
		if not rate_link:
			continue
		# Oran kaydını doğrula; şablon seçimi şirket politikasına bırakılabilir.
		# Hook yalnızca 360 hesabını vergi satırına yönlendirmek için işaret bırakır —
		# item_tax_template zaten kullanıcı/şablon tarafından set edilmiş olabilir.
		# Tevkifatlı işlemde taxes tablosunda 360 account_head tercih edilir (varsa).
		if not account_360:
			frappe.msgprint(
				_(
					"Tevkifat seçildi ({0}) ancak şirkette 360 Ödenecek Vergi ve Fonlar "
					"hesabı bulunamadı. Satır: {1}"
				).format(rate_link, item.get("item_code") or item.idx),
				indicator="orange",
				alert=True,
			)
			continue

		# taxes child'ında tevkifat satırı varsa account_head'i 360 yap (tutar dokunulmaz)
		if hasattr(doc, "taxes"):
			for tax in doc.taxes:
				# Yalnızca boş account_head doldur; mevcut tutarlara dokunma
				if not tax.get("account_head") and tax.get("charge_type"):
					tax.account_head = account_360


def _find_360_leaf(company: str) -> str | None:
	root = find_account_by_number(company, "360")
	if not root:
		return None
	leaves = frappe.get_all(
		"Account",
		filters={"company": company, "is_group": 0},
		fields=["name", "account_number"],
	)
	for leaf in leaves:
		if _norm(leaf.account_number).startswith("360"):
			return leaf.name
	return root


def compute_kdv_settlement(company: str, year: int, month: int) -> dict[str, Any]:
	"""191 ↔ 391 netleştirme önizlemesi. Kayıt atmaz."""
	from frappe.utils import get_first_day, get_last_day

	from_date = get_first_day(f"{year}-{month:02d}-01")
	to_date = get_last_day(from_date)

	acc_191 = find_account_by_number(company, "191")
	acc_391 = find_account_by_number(company, "391")
	acc_360 = find_account_by_number(company, "360")
	acc_190 = find_account_by_number(company, "190")

	if not acc_191 or not acc_391:
		frappe.throw(
			_("Şirket {0} için 191 veya 391 hesabı bulunamadı (191={1}, 391={2}).").format(
				company, acc_191, acc_391
			)
		)

	from erpnext_tr.closing import get_period_balance

	bal_191 = flt(get_period_balance(company, acc_191, from_date, to_date))
	bal_391 = flt(get_period_balance(company, acc_391, from_date, to_date))
	# 191 Asset: borç bakiyesi pozitif; 391 Liability: alacak bakiyesi negatif (borç-alacak)
	indirilecek = abs(bal_191)
	hesaplanan = abs(bal_391)
	fark = flt(hesaplanan - indirilecek)

	rows: list[dict[str, Any]] = []
	# Netleştirme: 391 ve 191 karşılıklı kapatılır
	net = min(indirilecek, hesaplanan)
	if net > 0:
		rows.append(
			{
				"hesap": acc_391,
				"borc": net,
				"alacak": 0.0,
				"aciklama": _("391 Hesaplanan KDV kapatma"),
			}
		)
		rows.append(
			{
				"hesap": acc_191,
				"borc": 0.0,
				"alacak": net,
				"aciklama": _("191 İndirilecek KDV kapatma"),
			}
		)

	fark_hesabi = None
	fark_tutari = abs(fark)
	if fark > 0.00001:
		# Ödenecek KDV → 360
		if not acc_360:
			frappe.throw(_("360 Ödenecek Vergi ve Fonlar hesabı bulunamadı (şirket: {0}).").format(company))
		fark_hesabi = "360"
		rows.append(
			{
				"hesap": acc_360,
				"borc": 0.0,
				"alacak": fark_tutari,
				"aciklama": _("Ödenecek KDV (360)"),
			}
		)
		# dengelemek için 391'den kalan
		rows.append(
			{
				"hesap": acc_391,
				"borc": fark_tutari,
				"alacak": 0.0,
				"aciklama": _("391 kalan → 360"),
			}
		)
	elif fark < -0.00001:
		if not acc_190:
			frappe.throw(_("190 Devreden KDV hesabı bulunamadı (şirket: {0}).").format(company))
		fark_hesabi = "190"
		rows.append(
			{
				"hesap": acc_190,
				"borc": fark_tutari,
				"alacak": 0.0,
				"aciklama": _("Devreden KDV (190)"),
			}
		)
		rows.append(
			{
				"hesap": acc_191,
				"borc": 0.0,
				"alacak": fark_tutari,
				"aciklama": _("191 kalan → 190"),
			}
		)
	else:
		fark_hesabi = "-"
		fark_tutari = 0.0

	return {
		"rows": rows,
		"fark_hesabi": fark_hesabi,
		"fark_tutari": fark_tutari,
		"bal_191": bal_191,
		"bal_391": bal_391,
		"from_date": from_date,
		"to_date": to_date,
	}
