
frappe.ui.form.on('TR Period Closing', {
	refresh(frm) {
		frm.clear_custom_buttons();
		if (frm.doc.durum !== 'Kapatıldı' && frm.doc.durum !== 'İptal Edildi') {
			frm.add_custom_button(__('Hesapla'), () => {
				frm.call('hesapla').then(() => frm.reload_doc());
			});
		}
		if (frm.doc.kip === 'Kapanış' && frm.doc.durum === 'Hesaplandı') {
			frm.add_custom_button(__('Kapat'), () => {
				frappe.confirm(__('Önizleme satırları yevmiye olarak atılacak. Devam?'), () => {
					frm.call('kapat').then(() => frm.reload_doc());
				});
			}, __('İşlemler'));
		}
		if (frm.doc.durum === 'Kapatıldı') {
			frm.add_custom_button(__('İptal'), () => {
				frappe.confirm(__('Ters yevmiyeler atılacak. Devam?'), () => {
					frm.call('iptal').then(() => frm.reload_doc());
				});
			}, __('İşlemler'));
		}
	}
});
