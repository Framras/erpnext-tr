import frappe
from erpnext_tr.setup import find_account_by_number


def run() -> None:
	company = frappe.db.get_value("Company", {"abbr": "FIA"}, "name")
	print("C", company)
	for num in ["632", "690", "590", "152", "660", "771", "740", "770"]:
		name = find_account_by_number(company, num)
		print("X", num, name)
		if not name:
			continue
		is_group = frappe.db.get_value("Account", name, "is_group")
		desc = list(frappe.db.get_descendants("Account", name) or [])
		leaves = [d for d in desc if not frappe.db.get_value("Account", d, "is_group")]
		print("  group", is_group, "desc", len(desc), "leaves", len(leaves), leaves[:3])
