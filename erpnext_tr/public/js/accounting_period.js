// Copyright (c) 2026, Framras and contributors
// License: MIT
// Accounting Period: toplu kapat/aç — yalnızca grid; kaydetme kullanıcıda.

frappe.ui.form.on("Accounting Period", {
	refresh(frm) {
		if (frm.doc.disabled) {
			return;
		}
		frm.add_custom_button(__("Tümünü Kapat"), () => {
			const rows = frm.doc.closed_documents || [];
			if (!rows.length) {
				return;
			}
			rows.forEach((row) => {
				frappe.model.set_value(row.doctype, row.name, "closed", 1);
			});
			frm.refresh_field("closed_documents");
			frappe.show_alert({
				message: __("Tüm satırlar kapatıldı olarak işaretlendi. Kaydetmeyi unutmayın."),
				indicator: "orange",
			});
		});
		frm.add_custom_button(__("Tümünü Aç"), () => {
			const rows = frm.doc.closed_documents || [];
			if (!rows.length) {
				return;
			}
			rows.forEach((row) => {
				frappe.model.set_value(row.doctype, row.name, "closed", 0);
			});
			frm.refresh_field("closed_documents");
			frappe.show_alert({
				message: __("Tüm satırlar açıldı olarak işaretlendi. Kaydetmeyi unutmayın."),
				indicator: "orange",
			});
		});
	},
});
