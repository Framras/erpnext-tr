# Copyright (c) 2026, Framras and contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from erpnext_tr.validations import validate_tckn, validate_tax_id_value, validate_vkn


class TestTaxIdChecksum(FrappeTestCase):
	def test_valid_vkn(self) -> None:
		# Bilinen geçerli VKN örnekleri (algoritmik)
		candidates = []
		for base in range(100000000, 100000050):
			s9 = f"{base:09d}"
			digits = [int(ch) for ch in s9]
			total = 0
			for i in range(1, 10):
				t = (digits[i - 1] + (10 - i)) % 10
				t = t * (2 ** (10 - i))
				if t > 9:
					t = (t % 10) + (t // 10)
				total += t
			check = (10 - (total % 10)) % 10
			vkn = s9 + str(check)
			if validate_vkn(vkn):
				candidates.append(vkn)
				break
		self.assertTrue(candidates)
		validate_tax_id_value(candidates[0])

	def test_invalid_vkn(self) -> None:
		self.assertFalse(validate_vkn("1111111111"))
		with self.assertRaises(frappe.ValidationError):
			validate_tax_id_value("1111111111")

	def test_valid_tckn(self) -> None:
		# Algoritmik geçerli TCKN üret
		for d1 in range(1, 10):
			body = [d1, 2, 3, 4, 5, 6, 7, 8, 9]
			d10 = ((body[0] + body[2] + body[4] + body[6] + body[8]) * 7 - (
				body[1] + body[3] + body[5] + body[7]
			)) % 10
			if d10 < 0:
				d10 = (d10 + 10) % 10
			d11 = (sum(body) + d10) % 10
			tckn = "".join(str(x) for x in body) + str(d10) + str(d11)
			if validate_tckn(tckn):
				validate_tax_id_value(tckn)
				return
		self.fail("Geçerli TCKN üretilemedi")

	def test_invalid_tckn(self) -> None:
		# d1=0 yasak; kontrol haneleri de uymayan örnek
		self.assertFalse(validate_tckn("01234567890"))
		self.assertFalse(validate_tckn("12345678901"))
		with self.assertRaises(frappe.ValidationError):
			validate_tax_id_value("123")
