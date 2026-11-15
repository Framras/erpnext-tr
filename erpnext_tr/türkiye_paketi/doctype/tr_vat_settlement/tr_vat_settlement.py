# Copyright (c) 2026, Framras and contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, get_last_day

from erpnext_tr.kdv import compute_kdv_settlement


class TRVATSettlement(Document):
	@frappe.whitelist()
	def hesapla(self) -> None:
		self.check_permission("write")
		preview = compute_kdv_settlement(self.sirket, cint(self.yil), cint(self.ay))
		self.set("mahsup_satirlari", [])
		for row in preview["rows"]:
			self.append(
				"mahsup_satirlari",
				{
					"hesap": row["hesap"],
					"borc": row["borc"],
					"alacak": row["alacak"],
					"aciklama": row["aciklama"],
				},
			)
		self.fark_hesabi = preview["fark_hesabi"]
		self.fark_tutari = preview["fark_tutari"]
		self.durum = "Hesaplandı"
		self.save()
		frappe.msgprint(_("KDV mahsup önizlemesi hazır. Kayıt atılmadı."), indicator="green")

	@frappe.whitelist()
	def kaydet_yevmiye(self) -> None:
		self.check_permission("write")
		if self.durum != "Hesaplandı":
			frappe.throw(_("Önce Hesapla ile önizleme alın."))
		existing = frappe.db.exists(
			"TR VAT Settlement",
			{
				"sirket": self.sirket,
				"yil": self.yil,
				"ay": self.ay,
				"durum": "Kaydedildi",
				"name": ("!=", self.name),
			},
		)
		if existing:
			frappe.throw(
				_("Aynı ay için mahsup zaten kaydedilmiş: {0} (şirket {1}, {2}/{3})").format(
					existing, self.sirket, self.ay, self.yil
				)
			)
		if not self.mahsup_satirlari:
			frappe.throw(_("Mahsup satırı yok."))

		posting_date = get_last_day(f"{cint(self.yil)}-{cint(self.ay):02d}-01")
		accounts = []
		for row in self.mahsup_satirlari:
			accounts.append(
				{
					"account": row.hesap,
					"debit_in_account_currency": flt(row.borc),
					"credit_in_account_currency": flt(row.alacak),
					"user_remark": row.aciklama,
				}
			)
		je = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"voucher_type": "Journal Entry",
				"company": self.sirket,
				"posting_date": posting_date,
				"user_remark": _("TR KDV Mahsubu {0}").format(self.name),
				"accounts": accounts,
			}
		)
		je.flags.ignore_permissions = True
		je.insert()
		je.submit()
		self.je_no = je.name
		self.durum = "Kaydedildi"
		self.save()
		frappe.msgprint(_("Mahsup yevmiyesi atıldı: {0}").format(je.name), indicator="green")
