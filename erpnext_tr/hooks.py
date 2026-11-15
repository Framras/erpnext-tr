app_name = "erpnext_tr"
app_title = "Türkiye Paketi"
app_publisher = "Framras"
app_description = "ERPNext v16 Türkiye muhasebe ve vergi paketi (kapanış, KDV, tevkifat, beyanname ayrımları, e-belge arayüzü)"
app_email = "tufan.kaynak@framras.com"
app_license = "mit"

required_apps = ["frappe", "erpnext", "trebelge"]

after_install = "erpnext_tr.install.after_install"
after_migrate = "erpnext_tr.install.after_migrate"

doctype_js = {
	"Accounting Period": "public/js/accounting_period.js",
}

override_whitelisted_methods = {
	"erpnext.accounts.doctype.account.chart_of_accounts.chart_of_accounts.get_charts_for_country": (
		"erpnext_tr.chart.get_charts_for_country"
	),
	"erpnext.accounts.doctype.account.chart_of_accounts.chart_of_accounts.get_chart": (
		"erpnext_tr.chart.get_chart"
	),
}

doc_events = {
	"Customer": {
		"validate": "erpnext_tr.validations.validate_party",
	},
	"Supplier": {
		"validate": "erpnext_tr.validations.validate_party",
	},
	"Account": {
		"validate": "erpnext_tr.validations.validate_account_closing_fields",
	},
	"Sales Invoice": {
		"validate": [
			"erpnext_tr.validations.validate_sales_invoice_efatura",
			"erpnext_tr.kdv.apply_tevkifat_template_selection",
		],
	},
	"Purchase Invoice": {
		"validate": "erpnext_tr.kdv.apply_tevkifat_template_selection",
	},
	"Payment Entry": {
		"validate": "erpnext_tr.kmh.validate_kmh_on_payment",
	},
	"Journal Entry": {
		"validate": "erpnext_tr.kmh.validate_kmh_on_payment",
	},
}

fixtures = [
	{
		"dt": "Custom Field",
		"filters": [
			[
				"name",
				"in",
				[
					"Customer-custom_vergi_dairesi",
					"Customer-custom_mersis_no",
					"Supplier-custom_vergi_dairesi",
					"Supplier-custom_mersis_no",
					"Account-custom_kapanis_hesabi",
					"Account-custom_kapanis_notu",
					"Company-custom_maliyet_yontemi",
					"Bank Account-custom_kmh_hesabi",
					"Bank Account-custom_kmh_limiti",
					"Sales Invoice Item-custom_tevkifat_orani",
					"Sales Invoice Item-custom_istisna_kodu",
					"Sales Invoice Item-custom_iade_hakki",
					"Sales Invoice Item-custom_muhsgk_odeme_turu",
					"Sales Invoice Item-custom_kkeg_nedeni",
					"Sales Invoice Item-custom_istisna_indirim_nedeni",
					"Purchase Invoice Item-custom_tevkifat_orani",
					"Purchase Invoice Item-custom_istisna_kodu",
					"Purchase Invoice Item-custom_iade_hakki",
					"Purchase Invoice Item-custom_muhsgk_odeme_turu",
					"Purchase Invoice Item-custom_kkeg_nedeni",
					"Purchase Invoice Item-custom_istisna_indirim_nedeni",
				],
			]
		],
	},
]
