
frappe.ui.form.on("TR VAT Settlement", {
	refresh(frm) {
		frm.clear_custom_buttons();
		// Hesapla: yalnızca taslak (docstatus 0). Gönder/İptal/Düzelt = çerçeve butonları.
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Hesapla"), () => {
				frm.call("hesapla").then(() => frm.reload_doc());
			});
		}
	},
});
