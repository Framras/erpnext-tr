# Copyright (c) 2026, Framras and contributors
# License: MIT

from __future__ import annotations

from frappe.tests.utils import FrappeTestCase

from erpnext_tr.party_link_ar_ap import age_labels, resolve


class TestPartyLinkArAp(FrappeTestCase):
	def test_resolve_maps_secondary_to_primary(self) -> None:
		link_map = {
			("Customer", "C1"): ("Customer", "C1"),
			("Supplier", "S1"): ("Customer", "C1"),
		}
		self.assertEqual(resolve("Supplier", "S1", link_map), ("Customer", "C1"))
		self.assertEqual(resolve("Customer", "C1", link_map), ("Customer", "C1"))

	def test_resolve_unlinked_party_stays_itself(self) -> None:
		self.assertEqual(resolve("Supplier", "S9", {}), ("Supplier", "S9"))

	def test_age_labels(self) -> None:
		labels = age_labels(type("F", (), {"range": "30, 60, 90, 120"})())
		self.assertEqual(labels[:4], ["0-30", "31-60", "61-90", "91-120"])
		self.assertEqual(len(labels), 5)
