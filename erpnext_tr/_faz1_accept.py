"""Faz1 kabul testleri — T1–T7, P3/P4 smoke. Çalıştır: bench console'dan run()."""

from __future__ import annotations

import frappe
from frappe.utils import flt

from erpnext_tr.closing import (
	compute_preview,
	detect_cycle,
	ensure_postable_account,
	get_period_balance,
)
from erpnext_tr.setup import find_account_by_number


def _disable_errors(company: str) -> None:
	for code in ["D1", "D2", "D5", "D8", "D9", "D12", "D14", "D19"]:
		existing = frappe.db.get_value(
			"TR Rule Setting", {"sirket": company, "kural_kodu": code}, "name"
		)
		if existing:
			frappe.db.set_value("TR Rule Setting", existing, "aktif", 0, update_modified=False)
		else:
			# options migrate sonrası geçerli
			try:
				frappe.get_doc(
					{
						"doctype": "TR Rule Setting",
						"sirket": company,
						"kural_kodu": code,
						"aktif": 0,
					}
				).insert(ignore_permissions=True)
			except Exception:
				frappe.db.sql(
					"""
					insert into `tabTR Rule Setting` (name, sirket, kural_kodu, aktif, creation, modified, owner, modified_by)
					values (%s, %s, %s, 0, now(), now(), 'Administrator', 'Administrator')
					""",
					(frappe.generate_hash(length=10), company, code),
				)


def _enable_errors(company: str) -> None:
	frappe.db.sql(
		"update `tabTR Rule Setting` set aktif=1 where sirket=%s",
		(company,),
	)


def run() -> dict:
	company = frappe.db.get_value("Company", {"abbr": "FIA"}, "name")
	fr, to = "2026-07-01", "2026-09-30"
	out: dict = {}

	# T3
	out["T3"] = "GEÇTİ" if detect_cycle({"A": "B", "B": "A"}) else "KALDI"

	_disable_errors(company)

	# Ensure postable 740 leaf + seed 100000
	acc740 = find_account_by_number(company, "740")
	leaf740 = ensure_postable_account(company, acc740)
	# Karşı hesap: party gerektirmeyen gelir/özkaynak (320 Payable party ister; 100 Debit kilitli)
	credit = ensure_postable_account(company, find_account_by_number(company, "600"))
	seed = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"company": company,
			"posting_date": "2026-09-15",
			"user_remark": "erpnext_tr FAZ1 T1 seed",
			"accounts": [
				{"account": leaf740, "debit_in_account_currency": 100000, "credit_in_account_currency": 0},
				{"account": credit, "debit_in_account_currency": 0, "credit_in_account_currency": 100000},
			],
		}
	)
	seed.flags.ignore_permissions = True
	seed.party_not_required = 1
	seed.insert()
	seed.submit()
	out["seed"] = seed.name
	out["leaf740"] = leaf740
	out["740_bal"] = get_period_balance(company, acc740, fr, to)
	out["leaf740_bal"] = get_period_balance(company, leaf740, fr, to)

	preview = compute_preview(company, fr, to, 0)
	chain = [
		r
		for r in preview["rows"]
		if any(x in (r["kaynak_hesap"] + r["hedef_hesap"]) for x in ("740", "741", "622"))
	]
	out["T1_preview_rows"] = len(chain)
	out["T4"] = "GEÇTİ" if all(flt(r["tutar"]) > 0 for r in preview["rows"]) else "KALDI"

	# T6 Hesaplama
	doc_calc = frappe.get_doc(
		{
			"doctype": "TR Period Closing",
			"sirket": company,
			"donem_tipi": "Çeyrek",
			"donem_baslangic": fr,
			"donem_bitis": to,
			"kip": "Hesaplama",
		}
	)
	doc_calc.insert(ignore_permissions=True)
	doc_calc.hesapla()
	doc_calc.reload()
	out["T6"] = {
		"durum": doc_calc.durum,
		"donem_kari": doc_calc.donem_kari,
		"n": len(doc_calc.kapanis_yevmiyeleri),
		"result": "GEÇTİ" if doc_calc.durum == "Hesaplandı" else "KALDI",
	}

	# T1/T2 Kapanış
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
	try:
		doc.kapat()
		doc.reload()
		b740 = get_period_balance(company, acc740, fr, to)
		acc741 = find_account_by_number(company, "741")
		acc622 = find_account_by_number(company, "622")
		b741 = get_period_balance(company, acc741, fr, to)
		b622 = get_period_balance(company, acc622, fr, to)
		jes = [r.je_no for r in doc.kapanis_yevmiyeleri if r.je_no]
		out["T1"] = {
			"durum": doc.durum,
			"balances": {"740": b740, "741": b741, "622": b622},
			"jes": jes,
			"result": "GEÇTİ" if doc.durum == "Kapatıldı" and abs(flt(b740)) < 0.01 else "KALDI",
		}
		# T2: 690/590 satırı var mı
		has_690 = any("690" in (r.kaynak_hesap or "") for r in doc.kapanis_yevmiyeleri)
		out["T2"] = "GEÇTİ" if has_690 or any("690" in (r.hedef_hesap or "") for r in doc.kapanis_yevmiyeleri) else "KALDI"

		# T7
		try:
			doc2 = frappe.get_doc(
				{
					"doctype": "TR Period Closing",
					"sirket": company,
					"donem_tipi": "Çeyrek",
					"donem_baslangic": fr,
					"donem_bitis": to,
					"kip": "Kapanış",
				}
			)
			doc2.insert(ignore_permissions=True)
			doc2.hesapla()
			doc2.kapat()
			out["T7"] = "KALDI — ikinci kapanışa izin verdi"
		except Exception as exc:
			out["T7"] = f"GEÇTİ ({exc})"[:180]

		# T5
		doc.iptal()
		doc.reload()
		out["T5"] = "GEÇTİ" if doc.durum == "İptal Edildi" else f"KALDI {doc.durum}"
		try:
			doc.iptal()
			out["T5_second"] = "KALDI — ikinci iptale izin verdi"
		except Exception:
			out["T5_second"] = "GEÇTİ"
	except Exception as exc:
		out["T1"] = f"KALDI — {exc}"[:400]
		import traceback

		traceback.print_exc()

	# cleanup seed
	try:
		s = frappe.get_doc("Journal Entry", seed.name)
		if s.docstatus == 1:
			s.cancel()
		out["seed_cleanup"] = "cancelled"
	except Exception as exc:
		out["seed_cleanup"] = str(exc)[:120]

	_enable_errors(company)
	frappe.db.commit()
	return out
