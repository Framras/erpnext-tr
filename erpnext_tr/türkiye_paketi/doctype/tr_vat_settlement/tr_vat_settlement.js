
frappe.ui.form.on('TR VAT Settlement', {
	refresh(frm) {
		frm.clear_custom_buttons();
		if (frm.doc.durum !== 'Kaydedildi') {
			frm.add_custom_button(__('Hesapla'), () => {
				frm.call('hesapla').then(() => frm.reload_doc());
			});
		}
		if (frm.doc.durum === 'Hesaplandı') {
			frm.add_custom_button(__('Kaydet'), () => {
				frappe.confirm(__('Önizleme tutarlarıyla yevmiye atılacak. Devam?'), () => {
					frm.call('kaydet_yevmiye').then(() => frm.reload_doc());
				});
			});
		}
	}
});
