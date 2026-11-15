// Copyright (c) 2026, Framras and contributors
// License: MIT

frappe.query_reports["TR Kural Denetimi"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Şirket"),
			fieldtype: "Link",
			options: "Company",
			reqd: 1,
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "from_date",
			label: __("Dönem Başı"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.year_start(),
		},
		{
			fieldname: "to_date",
			label: __("Dönem Sonu"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.get_today(),
		},
	],
};
