# Copyright (c) 2026, Framras and contributors
# License: MIT

from __future__ import annotations

from frappe.tests.utils import FrappeTestCase

from erpnext_tr.closing import detect_cycle, topological_deepest_first


class TestClosingGraph(FrappeTestCase):
	def test_topo_order_deepest_first(self) -> None:
		# 740→741→622→690→590
		graph = {
			"740": "741",
			"741": "622",
			"622": "690",
			"690": "590",
		}
		order = topological_deepest_first(graph)
		self.assertEqual(order[0], "740")
		self.assertLess(order.index("740"), order.index("741"))
		self.assertLess(order.index("741"), order.index("622"))
		self.assertLess(order.index("622"), order.index("690"))

	def test_cycle_detected(self) -> None:
		graph = {"A": "B", "B": "A"}
		cycle = detect_cycle(graph)
		self.assertIsNotNone(cycle)

	def test_no_cycle(self) -> None:
		graph = {"A": "B", "B": "C"}
		self.assertIsNone(detect_cycle(graph))
