# Copyright (c) 2026, Framras and contributors
# License: MIT
"""TR hesap planı şablonunu ERPNext şirket kurulumuna bağlar."""

from __future__ import annotations

import json
import os

import frappe
from erpnext.accounts.doctype.account.chart_of_accounts.chart_of_accounts import (
	get_chart as erpnext_get_chart,
)
from erpnext.accounts.doctype.account.chart_of_accounts.chart_of_accounts import (
	get_charts_for_country as erpnext_get_charts_for_country,
)

TR_CHART_NAME = "Türkiye - Tek Düzen Hesap Planı"


def _chart_path() -> str:
	return os.path.join(
		os.path.dirname(__file__),
		"chart_of_accounts",
		"tr_chart_of_accounts.json",
	)


def load_tr_chart() -> dict:
	with open(_chart_path(), encoding="utf-8") as handle:
		return json.load(handle)


@frappe.whitelist()
def get_charts_for_country(country: str, with_standard: bool = False) -> list[str]:
	"""ERPNext listesine erpnext-tr TDHP şablonunu ekler."""
	charts = list(erpnext_get_charts_for_country(country, with_standard=with_standard) or [])
	country_name = (country or "").strip().lower()
	if country_name in {"turkey", "türkiye", "turkiye"} and TR_CHART_NAME not in charts:
		charts.insert(0, TR_CHART_NAME)
	return charts


@frappe.whitelist()
def get_chart(chart_template: str | None = None, existing_company: str | None = None):
	"""erpnext-tr şablonunu veya standart ERPNext şablonunu döndürür."""
	if chart_template == TR_CHART_NAME:
		data = load_tr_chart()
		return data.get("tree") or data
	return erpnext_get_chart(chart_template, existing_company)
