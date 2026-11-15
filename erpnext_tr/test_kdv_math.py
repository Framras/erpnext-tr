# Copyright (c) 2026, Framras and contributors
# License: MIT

from __future__ import annotations

from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt


class TestKdvSettlementMath(FrappeTestCase):
	def test_net_payable(self) -> None:
		indirilecek = 100.0
		hesaplanan = 150.0
		fark = flt(hesaplanan - indirilecek)
		self.assertEqual(fark, 50.0)
		self.assertEqual("360", "360" if fark > 0 else "190")

	def test_net_carry_forward(self) -> None:
		indirilecek = 200.0
		hesaplanan = 150.0
		fark = flt(hesaplanan - indirilecek)
		self.assertEqual(fark, -50.0)
		self.assertEqual("190", "190" if fark < 0 else "360")
