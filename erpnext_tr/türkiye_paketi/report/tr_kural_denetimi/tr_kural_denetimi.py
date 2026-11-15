# Copyright (c) 2026, Framras and contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _

from erpnext_tr.rule_checks import RULE_SEVERITY, run_rules


def execute(filters: dict | None = None):
	filters = filters or {}
	company = filters.get("company")
	from_date = filters.get("from_date")
	to_date = filters.get("to_date")
	if not company or not from_date or not to_date:
		frappe.throw(_("Şirket, dönem başı ve dönem sonu zorunludur."))

	columns = [
		{"label": _("Kural"), "fieldname": "rule", "fieldtype": "Data", "width": 70},
		{"label": _("Şiddet"), "fieldname": "severity", "fieldtype": "Data", "width": 80},
		{"label": _("Belge Tipi"), "fieldname": "voucher_type", "fieldtype": "Data", "width": 120},
		{
			"label": _("Belge No"),
			"fieldname": "voucher_no",
			"fieldtype": "Dynamic Link",
			"options": "voucher_type",
			"width": 140,
		},
		{"label": _("Tarih"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
		{"label": _("Hesap"), "fieldname": "account", "fieldtype": "Link", "options": "Account", "width": 180},
		{"label": _("Tutar"), "fieldname": "amount", "fieldtype": "Currency", "width": 110},
		{"label": _("Mesaj"), "fieldname": "message", "fieldtype": "Data", "width": 360},
	]

	data = run_rules(company, from_date, to_date)
	# severity fallback
	for row in data:
		row.setdefault("severity", RULE_SEVERITY.get(row.get("rule", ""), "Uyarı"))
	return columns, data
