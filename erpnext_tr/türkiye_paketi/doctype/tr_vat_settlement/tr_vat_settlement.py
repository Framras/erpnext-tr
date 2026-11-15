# Copyright (c) 2026, Framras and contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, get_last_day, nowdate

from erpnext_tr.kdv import compute_kdv_settlement


class TRVATSettlement(Document):
	def before_insert(self) -> None:
		# Amend: yeni taslak; eski yevmiye linki taşınmaz (iptal kaydı geçmişte kalır).
		if self.amended_from:
			self.je_no = None
			self.durum = "Taslak"

	def validate(self) -> None:
		if self.docstatus == 0 and not self.durum:
			self.durum = "Taslak"

	@frappe.whitelist()
	def hesapla(self) -> None:
		"""Önizleme: satırları doldurur, yevmiye atmaz. Yalnızca taslak belgede."""
		self.check_permission("write")
		if self.docstatus != 0:
			frappe.throw(_("Önizleme yalnızca taslak belgede çalışır."))

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
		frappe.msgprint(
			_("KDV mahsup önizlemesi hazır. Gönder ile yevmiye atılır."),
			indicator="green",
		)

	def before_submit(self) -> None:
		if self.durum != "Hesaplandı" or not self.mahsup_satirlari:
			frappe.throw(_("Önce Hesapla ile önizleme alın; ardından Gönder’e basın."))
		self._assert_no_other_submitted_for_month()

	def on_submit(self) -> None:
		je_name = self._post_jv()
		self.db_set({"je_no": je_name, "durum": "Kaydedildi"})
		frappe.msgprint(_("Mahsup yevmiyesi atıldı: {0}").format(je_name), indicator="green")

	def on_cancel(self) -> None:
		"""Yevmiyeyi iptal et (silme); timeline’da iz kalır. Amend ile yeniden taslak açılır."""
		if not self.je_no:
			return
		if not frappe.db.exists("Journal Entry", self.je_no):
			return
		je_docstatus = frappe.db.get_value("Journal Entry", self.je_no, "docstatus")
		if cint(je_docstatus) == 1:
			je = frappe.get_doc("Journal Entry", self.je_no)
			je.flags.ignore_permissions = True
			je.cancel()
		self.add_comment(
			"Info",
			_("Mahsup yevmiyesi iptal edildi (geçmiş korundu): {0}").format(self.je_no),
		)

	def _assert_no_other_submitted_for_month(self) -> None:
		existing = frappe.db.exists(
			"TR VAT Settlement",
			{
				"sirket": self.sirket,
				"yil": self.yil,
				"ay": self.ay,
				"docstatus": 1,
				"name": ("!=", self.name),
			},
		)
		if existing:
			frappe.throw(
				_("Aynı ay için gönderilmiş mahsup var: {0} (şirket {1}, {2}/{3})").format(
					existing, self.sirket, self.ay, self.yil
				)
			)

	def _post_jv(self) -> str:
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
				"posting_date": posting_date or nowdate(),
				"user_remark": _("TR KDV Mahsubu {0}").format(self.name),
				"accounts": accounts,
			}
		)
		je.flags.ignore_permissions = True
		je.insert()
		je.submit()
		return je.name
