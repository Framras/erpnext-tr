# Copyright (c) 2026, Framras and contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from erpnext_tr.closing import (
	assert_accounting_period_open,
	assert_no_pcv_conflict,
	assert_not_already_closed,
	compute_preview,
	create_closing_jv,
	reverse_jv,
)
from erpnext_tr.rule_checks import has_error_violations


class TRPeriodClosing(Document):
	def validate(self) -> None:
		if getdate(self.donem_baslangic) > getdate(self.donem_bitis):
			frappe.throw(_("Dönem başlangıcı bitişten sonra olamaz."))
		self._validate_period_bounds()

	def _validate_period_bounds(self) -> None:
		start = getdate(self.donem_baslangic)
		end = getdate(self.donem_bitis)
		if self.donem_tipi == "Yıllık":
			if start.month != 1 or start.day != 1 or end.month != 12 or end.day != 31 or start.year != end.year:
				frappe.throw(_("Yıllık dönem 01.01–31.12 aynı yıl olmalıdır."))
			return
		# Çeyrek
		quarters = {(1, 3), (4, 6), (7, 9), (10, 12)}
		if (start.month, end.month) not in quarters or start.day != 1:
			frappe.throw(_("Çeyrek dönem 01.01–31.03 / 01.04–30.06 / 01.07–30.09 / 01.10–31.12 olmalıdır."))
		if start.year != end.year:
			frappe.throw(_("Çeyrek dönemi tek takvim yılı içinde olmalıdır."))

	@frappe.whitelist()
	def hesapla(self) -> None:
		"""Önizleme — kayıt atmaz."""
		self.check_permission("write")
		preview = compute_preview(
			self.sirket,
			self.donem_baslangic,
			self.donem_bitis,
			flt(self.vergi_karsiligi),
		)
		self.set("kapanis_yevmiyeleri", [])
		for row in preview["rows"]:
			self.append(
				"kapanis_yevmiyeleri",
				{
					"kaynak_hesap": row["kaynak_hesap"],
					"hedef_hesap": row["hedef_hesap"],
					"tutar": row["tutar"],
					"kaynak_bakiye": row.get("kaynak_bakiye"),
					"tarih": self.donem_bitis,
				},
			)
		self.donem_kari = preview["donem_kari"]
		self.durum = "Hesaplandı"
		self.save()
		frappe.msgprint(
			_("Önizleme hazır: {0} satır. Kayıt atılmadı.").format(len(preview["rows"])),
			indicator="green",
		)

	@frappe.whitelist()
	def kapat(self) -> None:
		"""Önizleme satırlarından zincir adımı başına JV atar."""
		self.check_permission("write")
		if self.kip != "Kapanış":
			frappe.throw(_("Kapat yalnızca kip=Kapanış iken çalışır."))
		if self.durum != "Hesaplandı":
			frappe.throw(_("Önce Hesapla ile önizleme alın (durum Hesaplandı olmalı)."))

		assert_no_pcv_conflict(self.sirket, self.donem_baslangic, self.donem_bitis)
		assert_accounting_period_open(self.sirket, self.donem_baslangic, self.donem_bitis)
		assert_not_already_closed(self.sirket, self.donem_baslangic, self.donem_bitis, exclude=self.name)

		if not self.kapanis_yevmiyeleri:
			frappe.throw(_("Kapatılacak satır yok. Önce Hesapla çalıştırın."))

		errors = has_error_violations(self.sirket, self.donem_baslangic, self.donem_bitis)
		if errors:
			lines = "<br>".join(f"{e.get('rule')}: {e.get('message')}" for e in errors[:20])
			frappe.throw(_("Kural denetimi Hata ihlalleri nedeniyle kapatma reddedildi:<br>{0}").format(lines))

		for row in self.kapanis_yevmiyeleri:
			if flt(row.tutar) <= 0:
				continue
			je_name = create_closing_jv(
				self.sirket,
				self.donem_bitis,
				row.kaynak_hesap,
				row.hedef_hesap,
				flt(row.tutar),
				flt(row.kaynak_bakiye),
				_("TR Dönem Kapanışı {0}: {1} → {2}").format(self.name, row.kaynak_hesap, row.hedef_hesap),
			)
			row.je_no = je_name
			row.tarih = self.donem_bitis

		self._close_accounting_period_docs()
		self.durum = "Kapatıldı"
		self.save()
		frappe.msgprint(_("Dönem kapatıldı. Yevmiyeler atıldı."), indicator="green")

	def _close_accounting_period_docs(self) -> None:
		periods = frappe.get_all(
			"Accounting Period",
			filters={
				"company": self.sirket,
				"start_date": ("<=", self.donem_bitis),
				"end_date": (">=", self.donem_baslangic),
			},
			fields=["name"],
		)
		for p in periods:
			doc = frappe.get_doc("Accounting Period", p.name)
			changed = False
			for row in doc.closed_documents or []:
				if not row.closed:
					row.closed = 1
					changed = True
			if changed:
				doc.save(ignore_permissions=True)

	@frappe.whitelist()
	def iptal(self) -> None:
		self.check_permission("write")
		if self.durum == "İptal Edildi":
			frappe.throw(_("Bu kapanış zaten iptal edilmiş: {0}").format(self.name))
		if self.durum != "Kapatıldı":
			frappe.throw(_("Yalnızca Kapatıldı durumundaki kayıt iptal edilebilir."))

		reversed_pairs: list[str] = []
		for row in self.kapanis_yevmiyeleri:
			if not row.je_no:
				continue
			# Link alanını bozmadan ters kayıt at
			original = row.je_no.split(" / ")[0].strip()
			if not frappe.db.exists("Journal Entry", original):
				continue
			# Zaten iptal edilmişse atla
			if frappe.db.get_value("Journal Entry", original, "docstatus") == 2:
				continue
			rev = reverse_jv(original, self.donem_bitis)
			reversed_pairs.append(f"{original}→{rev}")
			# orijinal JE linki korunur; ters kayıt user_remark'da

		self._open_accounting_period_docs()
		self.durum = "İptal Edildi"
		self.save()
		frappe.msgprint(
			_("Kapanış iptal edildi; ters yevmiyeler: {0}").format(", ".join(reversed_pairs) or "-"),
			indicator="orange",
		)

	def _open_accounting_period_docs(self) -> None:
		periods = frappe.get_all(
			"Accounting Period",
			filters={
				"company": self.sirket,
				"start_date": ("<=", self.donem_bitis),
				"end_date": (">=", self.donem_baslangic),
			},
			fields=["name"],
		)
		for p in periods:
			doc = frappe.get_doc("Accounting Period", p.name)
			changed = False
			for row in doc.closed_documents or []:
				if row.closed:
					row.closed = 0
					changed = True
			if changed:
				doc.save(ignore_permissions=True)
