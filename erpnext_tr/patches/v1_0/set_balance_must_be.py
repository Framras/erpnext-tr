# Copyright (c) 2026, Framras and contributors
# License: MIT
"""Mevcut şirketlerin leaf bilanço hesaplarına balance_must_be yazar (idempotent)."""

from __future__ import annotations

import frappe

# Ters bakiyeli aktif hesaplar (Credit beklenir)
_CONTRA_ASSET_PREFIXES: tuple[str, ...] = ("257", "129", "158", "119")
# Dönem net zararı (591): borç bakiyesi beklenir
_DEBIT_EQUITY_PREFIXES: tuple[str, ...] = ("591",)


def _normalize_number(account_number: str | None) -> str:
	return (account_number or "").replace(" ", "").replace(".", "").strip()


def _starts_with_code(account_number: str | None, code: str) -> bool:
	normalized = _normalize_number(account_number)
	return normalized.startswith(code)


def _desired_balance(root_type: str, account_number: str | None) -> str | None:
	"""Bilanço leaf için beklenen balance_must_be; gelir/gider için None."""
	if root_type not in ("Asset", "Liability", "Equity"):
		return None

	if root_type == "Asset":
		for prefix in _CONTRA_ASSET_PREFIXES:
			if _starts_with_code(account_number, prefix):
				return "Credit"
		return "Debit"

	if root_type == "Equity":
		for prefix in _DEBIT_EQUITY_PREFIXES:
			if _starts_with_code(account_number, prefix):
				return "Debit"
		return "Credit"

	# Liability
	return "Credit"


def execute() -> None:
	accounts = frappe.get_all(
		"Account",
		filters={"is_group": 0},
		fields=["name", "root_type", "account_number", "balance_must_be", "report_type"],
	)

	for row in accounts:
		if row.get("balance_must_be"):
			continue

		desired = _desired_balance(row.root_type or "", row.account_number)
		if not desired:
			continue

		# Yalnızca bilanço hesapları (6./7. sınıf root_type Income/Expense olabilir)
		frappe.db.set_value(
			"Account",
			row.name,
			"balance_must_be",
			desired,
			update_modified=False,
		)
