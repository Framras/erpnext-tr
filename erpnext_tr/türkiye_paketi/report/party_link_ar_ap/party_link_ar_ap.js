const PLAP_API = "erpnext_tr.party_link_ar_ap";
const PLAP_PRINT_FORMAT = "Cari Hesap Mutabakat";

frappe.query_reports["Party Link AR AP"] = {
	filters: [
		{ fieldname: "company", label: __("Şirket"), fieldtype: "Link", options: "Company",
		  default: frappe.defaults.get_user_default("Company"), reqd: 1 },
		{ fieldname: "report_date", label: __("Rapor Tarihi"), fieldtype: "Date",
		  default: frappe.datetime.get_today(), reqd: 1 },
		{ fieldname: "view", label: __("Görünüm"), fieldtype: "Select",
		  options: "Summary\nDetailed", default: "Summary" },
		{ fieldname: "ageing_based_on", label: __("Yaşlandırma Bazı"), fieldtype: "Select",
		  options: "Posting Date\nDue Date\nSupplier Invoice Date", default: "Due Date" },
		{ fieldname: "range", label: __("Yaşlandırma Aralığı"), fieldtype: "Data", default: "30, 60, 90, 120" },
		{ fieldname: "party", label: __("Asıl Cari"), fieldtype: "Data" },
		{ fieldname: "only_linked", label: __("Yalnızca Bağlı Cariler"), fieldtype: "Check", default: 0 },
		{ fieldname: "kdv_prefixes", label: __("KDV Hesap Ön Ekleri"), fieldtype: "Data", default: "391,191" },
		{ fieldname: "cost_center", label: __("Maliyet Merkezi"), fieldtype: "Link", options: "Cost Center" },
		{ fieldname: "finance_book", label: __("Finans Defteri"), fieldtype: "Link", options: "Finance Book" },
	],

	onload(report) {
		const wrapper = report.page.wrapper;
		wrapper.off("click.plap");

		// Mahsup (offset) Journal Entry
		wrapper.on("click.plap", ".plap-mahsup", function () {
			const d = $(this).data();
			const f = report.get_values();
			const args = {
				company: f.company,
				primary_role: d.role,
				primary_party: d.party,
				posting_date: f.report_date,
			};
			frappe.call({
				method: `${PLAP_API}.mahsup_journal_entry`,
				args: { ...args, preview: 1 },
				callback(r) {
					const i = r.message;
					const fmt = (v) => format_currency(v, i.currency);
					frappe.confirm(
						__("{1} (Müşteri) ile {2} (Tedarikçi) arasında {0} tutarında mahsup için taslak Yevmiye Kaydı oluşturulsun mu?",
							[fmt(i.amount), i.customer, i.supplier]) +
						`<br><br>${__("Alacak")}: ${fmt(i.receivable)}<br>${__("Borç")}: ${fmt(i.payable)}`,
						() => {
							frappe.call({
								method: `${PLAP_API}.mahsup_journal_entry`,
								args: { ...args, preview: 0 },
								freeze: true,
								callback(res) {
									frappe.set_route("Form", "Journal Entry", res.message.journal_entry);
								},
							});
						}
					);
				},
			});
		});

		// Cari Hesap Mutabakat (opens the print view of the Customer / Supplier)
		wrapper.on("click.plap", ".plap-mutabakat", function () {
			const d = $(this).data();
			const f = report.get_values();
			const url = frappe.urllib.get_full_url(
				"/printview?" +
					$.param({
						doctype: d.role,
						name: d.party,
						format: d.role === "Supplier" ? `${PLAP_PRINT_FORMAT} (Supplier)` : PLAP_PRINT_FORMAT,
						no_letterhead: 0,
						company: f.company,
						report_date: f.report_date,
					})
			);
			window.open(url, "_blank");
		});
	},

	formatter(value, row, column, data, default_formatter) {
		if (column.fieldname === "actions") {
			if (!data || data.bold || !data.primary_party) return "";
			const attrs = `data-role="${frappe.utils.escape_html(data.primary_role)}" data-party="${frappe.utils.escape_html(data.primary_party)}"`;
			let html = `<button class="btn btn-xs btn-default plap-mutabakat" ${attrs}>${__("Mutabakat")}</button>`;
			if (data.mahsup_amount > 0) {
				html += ` <button class="btn btn-xs btn-primary plap-mahsup" ${attrs}>${__("Mahsup")}</button>`;
			}
			return html;
		}
		value = default_formatter(value, row, column, data);
		if (["net_outstanding", "exposure"].includes(column.fieldname) && data && data[column.fieldname] !== undefined) {
			const v = data[column.fieldname];
			const c = v > 0 ? "green" : v < 0 ? "red" : "gray";
			value = `<span style="color:var(--${c}-600)">${value}</span>`;
		}
		return value;
	},
};
