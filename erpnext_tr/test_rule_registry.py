# Copyright (c) 2026, Framras and contributors
# License: MIT

from __future__ import annotations

from frappe.tests.utils import FrappeTestCase

from erpnext_tr.rule_checks import RULE_REGISTRY, RULE_SEVERITY


class TestRuleRegistry(FrappeTestCase):
	def test_all_rules_defined(self) -> None:
		expected = {f"D{i}" for i in range(1, 23)}
		self.assertEqual(set(RULE_REGISTRY.keys()), expected)
		self.assertEqual(set(RULE_SEVERITY.keys()), expected)
