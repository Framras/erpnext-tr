"""T1/T5/T7 on existing debug seed ACC-JV-2026-00013."""

from __future__ import annotations

import frappe
from frappe.utils import flt

from erpnext_tr.closing import get_period_balance
from erpnext_tr.setup import find_account_by_number


def run() -> dict:
	company = frappe.db.get_value("Company", {"abbr": "FIA"}, "name")
	fr, to = "2026-07-01", "2026-09-30"
	out: dict = {}

	# disable error rules
	for code in ["D1", "D2", "D5", "D8", "D9", "D12", "D14", "D19"]:
		name = frappe.db.get_value("TR Rule Setting", {"sirket": company, "kural_kodu": code}, "name")
		if name:
			frappe.db.set_value("TR Rule Setting", name, "aktif", 0, update_modified=False)
		else:
			frappe.db.sql(
				"""
				insert into `tabTR Rule Setting`
				(name, sirket, kural_kodu, aktif, creation, modified, owner, modified_by, docstatus, idx)
				values (%s,%s,%s,0,now(),now(),'Administrator','Administrator',0,0)
				""",
				(frappe.generate_hash(length=10), company, code),
			)

	acc740 = find_account_by_number(company, "740")
	out["740_before"] = get_period_balance(company, acc740, fr, to)

	doc = frappe.get_doc(
		{
			"doctype": "TR Period Closing",
			"sirket": company,
			"donem_tipi": "Çeyrek",
			"donem_baslangic": fr,
			"donem_bitis": to,
			"kip": "Kapanış",
			"vergi_karsiligi": 0,
		}
	)
	doc.insert(ignore_permissions=True)
	doc.hesapla()
	doc.reload()
	out["preview_n"] = len(doc.kapanis_yevmiyeleri)
	out["preview"] = [
		{
			"src": r.kaynak_hesap,
			"tgt": r.hedef_hesap,
			"amt": r.tutar,
		}
		for r in doc.kapanis_yevmiyeleri
	]

	try:
		doc.kapat()
		doc.reload()
		acc741 = find_account_by_number(company, "741")
		acc622 = find_account_by_number(company, "622")
		out["T1"] = {
			"durum": doc.durum,
			"740": get_period_balance(company, acc740, fr, to),
			"741": get_period_balance(company, acc741, fr, to),
			"622": get_period_balance(company, acc622, fr, to),
			"jes": [r.je_no for r in doc.kapanis_yevmiyeleri if r.je_no],
		}
		out["T1_result"] = (
			"GEÇTİ"
			if doc.durum == "Kapatıldı" and abs(flt(out["T1"]["740"])) < 0.01
			else "KALDI"
		)

		# T7
		try:
			d2 = frappe.get_doc(
				{
					"doctype": "TR Period Closing",
					"sirket": company,
					"donem_tipi": "Çeyrek",
					"donem_baslangic": fr,
					"donem_bitis": to,
					"kip": "Kapanış",
				}
			)
			d2.insert(ignore_permissions=True)
			d2.hesapla()
			d2.kapat()
			out["T7"] = "KALDI"
		except Exception as exc:
			out["T7"] = f"GEÇTİ ({str(exc)[:120]})"

		# T5
		doc.iptal()
		doc.reload()
		out["T5"] = "GEÇTİ" if doc.durum == "İptal Edildi" else f"KALDI {doc.durum}"
		try:
			doc.iptal()
			out["T5_second"] = "KALDI"
		except Exception:
			out["T5_second"] = "GEÇTİ"
	except Exception as exc:
		out["T1_result"] = f"KALDI {exc}"[:400]
		import traceback

		traceback.print_exc()

	# cancel debug seed
	for name in frappe.get_all(
		"Journal Entry",
		filters={"user_remark": ("like", "%FAZ1 debug seed%"), "docstatus": 1},
		pluck="name",
	):
		frappe.get_doc("Journal Entry", name).cancel()
		out.setdefault("cancelled_seeds", []).append(name)

	# leftover closing docs
	out["closing_docs"] = frappe.get_all(
		"TR Period Closing",
		fields=["name", "durum", "kip"],
		order_by="creation desc",
		limit=10,
	)

	frappe.db.sql("update `tabTR Rule Setting` set aktif=1 where sirket=%s", (company,))
	frappe.db.commit()
	return out
