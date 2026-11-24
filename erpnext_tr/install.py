# Copyright (c) 2026, Framras and contributors
# License: MIT

from __future__ import annotations

from erpnext_tr.setup import after_install as _after_install


def after_install() -> None:
	_after_install()


def after_migrate() -> None:
	"""Migrate sonrası alanlar / zincirler / şablonlar (idempotent)."""
	from erpnext_tr.party_link_ar_ap import setup_print_formats as setup_party_link_print_formats
	from erpnext_tr.setup import (
		load_tax_offices_from_csv,
		setup_closing_chains,
		setup_custom_fields,
		setup_kdv_templates,
		setup_tevkifat_rates,
		setup_vuk_report_templates,
	)

	setup_custom_fields()
	load_tax_offices_from_csv()
	setup_tevkifat_rates()
	setup_closing_chains()
	setup_kdv_templates()
	setup_vuk_report_templates()
	setup_party_link_print_formats()
