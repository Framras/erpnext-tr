# Copyright (c) 2026, Framras and contributors
# License: MIT
"""Kurulum: kapanış zincirleri, KDV şablonları, VUK rapor şablonları."""

from __future__ import annotations

import json
import os
from typing import Any

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cint, flt

# Kaynak hesap numarası → (hedef numara, not)
CLOSING_CHAINS_7A: list[tuple[str, str, str]] = [
	("710", "711", "Direkt ilk madde → yansıtma"),
	("711", "152", "Yansıtma → mamul (varsayılan 152)"),
	("720", "721", "Direkt işçilik → yansıtma"),
	("721", "152", "Varsayılan 152"),
	("730", "731", "Genel üretim → yansıtma"),
	("731", "152", "Varsayılan 152"),
	("740", "741", "Hizmet üretim → yansıtma"),
	("741", "622", "Yansıtma → satılan hizmet maliyeti"),
	("750", "751", "Ar-Ge → yansıtma"),
	("751", "623", "Yansıtma → satılan mamul maliyeti"),
	("760", "761", "Pazarlama satış dağıtım → yansıtma"),
	("761", "631", "Yansıtma → pazarlama satış dağıtım gideri"),
	("770", "771", "Genel yönetim → yansıtma"),
	("771", "632", "Yansıtma → genel yönetim gideri"),
	("780", "781", "Finansman → yansıtma"),
	("781", "660", "Yansıtma → kısa vadeli borçlanma gideri (varsayılan 660)"),
]

CLOSING_CHAINS_7B: list[tuple[str, str, str]] = [
	("798", "799", "7/B yansıtma"),
	("799", "152", "7/B → mamul (varsayılan 152)"),
]

SKIPPED_CHAINS: list[str] = []


def _norm(num: str | None) -> str:
	return (num or "").replace(" ", "").replace(".", "").strip()


def find_account_by_number(company: str, number: str) -> str | None:
	"""Şirkette hesap numarası tam eşleşen kaydı bul (önce leaf, sonra grup)."""
	wanted = _norm(number)
	rows = frappe.get_all(
		"Account",
		filters={"company": company},
		fields=["name", "account_number", "is_group"],
	)
	exact_leaf = None
	exact_any = None
	for row in rows:
		if _norm(row.account_number) == wanted:
			if not row.is_group and not exact_leaf:
				exact_leaf = row.name
			if not exact_any:
				exact_any = row.name
	return exact_leaf or exact_any


def _set_closing_link(source: str, target: str, note: str) -> None:
	frappe.db.set_value(
		"Account",
		source,
		{
			"custom_kapanis_hesabi": target,
			"custom_kapanis_notu": note,
		},
		update_modified=False,
	)


def setup_closing_chains(company: str | None = None) -> list[str]:
	"""7/A ve 7/B zincirlerini + 6. sınıf→690 bağlarını yazar. Idempotent."""
	global SKIPPED_CHAINS
	SKIPPED_CHAINS = []
	companies = (
		[company]
		if company
		else [c.name for c in frappe.get_all("Company", fields=["name"])]
	)

	for company_name in companies:
		if not company_name:
			continue

		# Şirket maliyet yöntemi varsayılanı
		if not frappe.db.get_value("Company", company_name, "custom_maliyet_yontemi"):
			frappe.db.set_value(
				"Company",
				company_name,
				"custom_maliyet_yontemi",
				"7/A",
				update_modified=False,
			)

		for source_no, target_no, note in CLOSING_CHAINS_7A + CLOSING_CHAINS_7B:
			src = find_account_by_number(company_name, source_no)
			tgt = find_account_by_number(company_name, target_no)
			if not src or not tgt:
				SKIPPED_CHAINS.append(
					f"{company_name}: {source_no}→{target_no} (src={src}, tgt={tgt})"
				)
				continue
			_set_closing_link(src, tgt, note)

		# 600–689 → 690
		target_690 = find_account_by_number(company_name, "690")
		if target_690:
			accounts = frappe.get_all(
				"Account",
				filters={"company": company_name},
				fields=["name", "account_number", "is_group"],
			)
			for row in accounts:
				n = _norm(row.account_number)
				if len(n) < 3:
					continue
				# 600-689 aralığı (tam 3 haneli kök veya alt)
				prefix = n[:3]
				if not prefix.isdigit():
					continue
				code = int(prefix)
				if 600 <= code <= 689:
					# Kök hesaba yaz (tam eşleşen 3 hane veya grup kök)
					if n == prefix or (not row.is_group and n.startswith(prefix)):
						# yalnızca kök numarası tam olan veya account_number tam 3 hane
						if n == prefix:
							_set_closing_link(
								row.name,
								target_690,
								"6. sınıf gelir/gider → dönem kârı/zararı (690)",
							)
		else:
			SKIPPED_CHAINS.append(f"{company_name}: 690 bulunamadı")

		# 690 → 590 (varsayılan; zarar için 591 motor seçer)
		src_690 = find_account_by_number(company_name, "690")
		tgt_590 = find_account_by_number(company_name, "590")
		if src_690 and tgt_590:
			_set_closing_link(
				src_690,
				tgt_590,
				"690 → 590/591 (motor bakiye yönüne göre 591 seçebilir)",
			)
		elif src_690:
			SKIPPED_CHAINS.append(f"{company_name}: 590 bulunamadı")

	return SKIPPED_CHAINS


def get_custom_fields() -> dict[str, list[dict[str, Any]]]:
	"""Tüm custom field tanımları."""
	party_fields = [
		{
			"fieldname": "custom_vergi_dairesi",
			"label": "Vergi Dairesi",
			"fieldtype": "Link",
			"options": "TR Tax Office",
			"insert_after": "tax_id",
		},
		{
			"fieldname": "custom_mersis_no",
			"label": "MERSİS No",
			"fieldtype": "Data",
			"insert_after": "custom_vergi_dairesi",
		},
	]
	item_fields = [
		{
			"fieldname": "custom_tevkifat_orani",
			"label": "Tevkifat Oranı",
			"fieldtype": "Link",
			"options": "TR VAT Withholding Rate",
			"insert_after": "item_tax_template",
		},
		{
			"fieldname": "custom_istisna_kodu",
			"label": "İstisna Kodu",
			"fieldtype": "Data",
			"insert_after": "custom_tevkifat_orani",
		},
		{
			"fieldname": "custom_iade_hakki",
			"label": "KDV İade Hakkı",
			"fieldtype": "Check",
			"insert_after": "custom_istisna_kodu",
		},
		{
			"fieldname": "custom_muhsgk_odeme_turu",
			"label": "MUHSGK Ödeme Türü",
			"fieldtype": "Select",
			"options": "\nKira\nSerbest Meslek\nÜcret\nYıllara Sâri İnşaat\nKâr Payı\nTelif\nDiğer",
			"insert_after": "custom_iade_hakki",
		},
		{
			"fieldname": "custom_kkeg_nedeni",
			"label": "KKEG Nedeni",
			"fieldtype": "Select",
			"options": (
				"\nFinansman Gider Kısıtlaması\nBinek Oto\nÖrtülü Sermaye\n"
				"Transfer Fiyatlandırması\nCeza\nBağış Fazlası\nDiğer"
			),
			"insert_after": "custom_muhsgk_odeme_turu",
		},
		{
			"fieldname": "custom_istisna_indirim_nedeni",
			"label": "İstisna / İndirim Nedeni",
			"fieldtype": "Select",
			"options": (
				"\nİştirak Kazançları\nİştirak Hissesi-Taşınmaz Satış Kazancı\n"
				"Emisyon Primi\nAr-Ge İndirimi\nYatırım Katkı Tutarı\nBağış-Yardım\nSponsorluk"
			),
			"insert_after": "custom_kkeg_nedeni",
		},
	]
	return {
		"Customer": party_fields,
		"Supplier": party_fields,
		"Account": [
			{
				"fieldname": "custom_kapanis_hesabi",
				"label": "Kapanış Hesabı",
				"fieldtype": "Link",
				"options": "Account",
				"insert_after": "account_type",
			},
			{
				"fieldname": "custom_kapanis_notu",
				"label": "Kapanış Notu",
				"fieldtype": "Small Text",
				"insert_after": "custom_kapanis_hesabi",
			},
		],
		"Company": [
			{
				"fieldname": "custom_maliyet_yontemi",
				"label": "Maliyet Yöntemi",
				"fieldtype": "Select",
				"options": "7/A\n7/B",
				"default": "7/A",
				"insert_after": "default_letter_head",
			},
		],
		"Bank Account": [
			{
				"fieldname": "custom_kmh_hesabi",
				"label": "KMH Hesabı",
				"fieldtype": "Link",
				"options": "Account",
				"insert_after": "account",
			},
			{
				"fieldname": "custom_kmh_limiti",
				"label": "KMH Limiti",
				"fieldtype": "Currency",
				"insert_after": "custom_kmh_hesabi",
			},
		],
		"Sales Invoice Item": item_fields,
		"Purchase Invoice Item": item_fields,
	}


def setup_custom_fields() -> None:
	create_custom_fields(get_custom_fields(), update=True)


def setup_tevkifat_rates() -> None:
	rates = [
		(2, 10, "Yapım işleri / kısmi 2/10", "2/10"),
		(3, 10, "Kısmi 3/10", "3/10"),
		(4, 10, "Kısmi 4/10", "4/10"),
		(5, 10, "Kısmi 5/10", "5/10"),
		(7, 10, "Kısmi 7/10", "7/10"),
		(9, 10, "Kısmi 9/10", "9/10"),
		(10, 10, "Tam tevkifat 10/10", "10/10"),
	]
	for pay, payda, aciklama, gib in rates:
		name = f"{pay}/{payda}"
		if frappe.db.exists("TR VAT Withholding Rate", name):
			continue
		doc = frappe.get_doc(
			{
				"doctype": "TR VAT Withholding Rate",
				"oran_pay": pay,
				"oran_payda": payda,
				"aciklama": aciklama,
				"gib_kodu": gib,
			}
		)
		doc.insert(ignore_permissions=True)


def _find_tax_account(company: str, prefixes: tuple[str, ...]) -> str | None:
	for prefix in prefixes:
		name = find_account_by_number(company, prefix)
		if name:
			# leaf tercih: alt leaf varsa ilk leaf
			leaves = frappe.get_all(
				"Account",
				filters={"company": company, "is_group": 0, "account_number": ("like", f"{prefix}%")},
				fields=["name", "account_number"],
				order_by="account_number",
				limit=5,
			)
			# account_number like may not work with spaces; filter in python
			all_leaves = frappe.get_all(
				"Account",
				filters={"company": company, "is_group": 0},
				fields=["name", "account_number"],
			)
			for leaf in all_leaves:
				if _norm(leaf.account_number).startswith(_norm(prefix)):
					return leaf.name
			return name
	return None


def setup_kdv_templates(company: str | None = None) -> list[str]:
	"""Item Tax Template oluşturur. Atlananlar liste olarak döner."""
	skipped: list[str] = []
	companies = (
		[company]
		if company
		else [c.name for c in frappe.get_all("Company", fields=["name"])]
	)
	templates = [
		("TR Satış %1 KDV", 1.0, ("391",), "Sales"),
		("TR Satış %10 KDV", 10.0, ("391",), "Sales"),
		("TR Satış %20 KDV", 20.0, ("391",), "Sales"),
		("TR Alış %1 KDV", 1.0, ("191",), "Purchase"),
		("TR Alış %10 KDV", 10.0, ("191",), "Purchase"),
		("TR Alış %20 KDV", 20.0, ("191",), "Purchase"),
	]
	for company_name in companies:
		for title, rate, prefixes, _kind in templates:
			account = _find_tax_account(company_name, prefixes)
			if not account:
				skipped.append(f"{company_name}: {title} — hesap {prefixes} yok")
				continue
			# ERPNext şirket kısaltmasını kendisi ekler; title'da kısaltma yok
			existing = frappe.db.exists(
				"Item Tax Template", {"title": title, "company": company_name}
			)
			if existing:
				continue
			doc = frappe.get_doc(
				{
					"doctype": "Item Tax Template",
					"title": title,
					"company": company_name,
					"taxes": [
						{
							"tax_type": account,
							"tax_rate": rate,
						}
					],
				}
			)
			try:
				doc.insert(ignore_permissions=True)
			except Exception as exc:  # noqa: BLE001
				skipped.append(f"{company_name}: {title} — {exc}")
	return skipped


def setup_vuk_report_templates() -> None:
	"""VUK Bilanço ve Gelir Tablosu Financial Report Template kayıtları."""
	_ensure_frt(
		"VUK Bilanço",
		"Balance Sheet",
		_vuk_balance_sheet_rows(),
	)
	_ensure_frt(
		"VUK Gelir Tablosu",
		"Profit and Loss Statement",
		_vuk_income_statement_rows(),
	)


def _ensure_frt(name: str, report_type: str, rows: list[dict]) -> None:
	if frappe.db.exists("Financial Report Template", name):
		doc = frappe.get_doc("Financial Report Template", name)
		doc.rows = []
		for row in rows:
			doc.append("rows", row)
		doc.report_type = report_type
		doc.module = "Türkiye Paketi"
		doc.save(ignore_permissions=True)
		return
	doc = frappe.get_doc(
		{
			"doctype": "Financial Report Template",
			"template_name": name,
			"report_type": report_type,
			"module": "Türkiye Paketi",
			"rows": rows,
		}
	)
	doc.insert(ignore_permissions=True)


def _acc_row(
	display: str,
	ref: str,
	formula: str,
	indent: int = 0,
	bold: int = 0,
	balance_type: str = "Closing Balance",
) -> dict:
	return {
		"display_name": display,
		"reference_code": ref,
		"data_source": "Account Data",
		"balance_type": balance_type,
		"calculation_formula": formula,
		"indentation_level": indent,
		"bold_text": bold,
	}


def _header(display: str, ref: str, indent: int = 0) -> dict:
	return {
		"display_name": display,
		"reference_code": ref,
		"data_source": "Blank Line",
		"indentation_level": indent,
		"bold_text": 1,
	}


def _calc(display: str, ref: str, formula: str, indent: int = 0, bold: int = 1) -> dict:
	return {
		"display_name": display,
		"reference_code": ref,
		"data_source": "Calculated Amount",
		"calculation_formula": formula,
		"indentation_level": indent,
		"bold_text": bold,
	}


def _vuk_balance_sheet_rows() -> list[dict]:
	# account_number like filtreleri TDHP aralıklarıyla
	return [
		_header("1. DÖNEN VARLIKLAR", "DV"),
		_acc_row("Dönen Varlıklar (1xx)", "DV1", '["account_number", "like", "1%"]', 1),
		_header("2. DURAN VARLIKLAR", "DRV"),
		_acc_row("Duran Varlıklar (2xx)", "DRV2", '["account_number", "like", "2%"]', 1),
		_calc("TOPLAM AKTİF", "AKTIF", "DV1 + DRV2", 0, 1),
		_header("3. KISA VADELİ YABANCI KAYNAKLAR", "KVYK"),
		_acc_row("Kısa Vadeli YK (3xx)", "KVYK3", '["account_number", "like", "3%"]', 1),
		_header("4. UZUN VADELİ YABANCI KAYNAKLAR", "UVYK"),
		_acc_row("Uzun Vadeli YK (4xx)", "UVYK4", '["account_number", "like", "4%"]', 1),
		_header("5. ÖZ KAYNAKLAR", "OK"),
		_acc_row("Öz Kaynaklar (5xx)", "OK5", '["account_number", "like", "5%"]', 1),
		_calc("TOPLAM PASİF", "PASIF", "KVYK3 + UVYK4 + OK5", 0, 1),
	]


def _vuk_income_statement_rows() -> list[dict]:
	return [
		_header("GELİR TABLOSU (VUK / TDHP)", "GT"),
		_acc_row("60 Brüt Satışlar", "G60", '["account_number", "like", "60%"]', 1, balance_type="Period Movement (Debits - Credits)"),
		_acc_row("61 Satış İndirimleri", "G61", '["account_number", "like", "61%"]', 1, balance_type="Period Movement (Debits - Credits)"),
		_acc_row("62 Satışların Maliyeti", "G62", '["account_number", "like", "62%"]', 1, balance_type="Period Movement (Debits - Credits)"),
		_acc_row("63 Faaliyet Giderleri", "G63", '["account_number", "like", "63%"]', 1, balance_type="Period Movement (Debits - Credits)"),
		_acc_row("64 Diğer Faaliyet", "G64", '["account_number", "like", "64%"]', 1, balance_type="Period Movement (Debits - Credits)"),
		_acc_row("65 Finansman", "G65", '["account_number", "like", "65%"]', 1, balance_type="Period Movement (Debits - Credits)"),
		_acc_row("66 Olağandışı", "G66", '["account_number", "like", "66%"]', 1, balance_type="Period Movement (Debits - Credits)"),
		_acc_row("67 Olağanüstü", "G67", '["account_number", "like", "67%"]', 1, balance_type="Period Movement (Debits - Credits)"),
		_acc_row("68 Diğer", "G68", '["account_number", "like", "68%"]', 1, balance_type="Period Movement (Debits - Credits)"),
		_acc_row("69 Dönem Kârı/Zararı", "G69", '["account_number", "like", "69%"]', 1, balance_type="Period Movement (Debits - Credits)"),
		_acc_row("690 Dönem Kârı/Zararı", "G690", '["account_number", "like", "690%"]', 1, balance_type="Closing Balance"),
	]


def load_tax_offices_from_csv() -> int:
	"""data/tr_vergi_dairesi.csv yükler (fixtures/ yedek yolu)."""
	base = os.path.dirname(__file__)
	path = os.path.join(base, "data", "tr_vergi_dairesi.csv")
	if not os.path.exists(path):
		path = os.path.join(base, "fixtures", "tr_vergi_dairesi.csv")
	if not os.path.exists(path):
		return 0
	import csv

	count = 0
	with open(path, encoding="utf-8") as handle:
		reader = csv.DictReader(handle)
		for row in reader:
			kod = (row.get("kod") or "").strip()
			if not kod:
				continue
			if frappe.db.exists("TR Tax Office", kod):
				frappe.db.set_value(
					"TR Tax Office",
					kod,
					{
						"ad": row.get("ad") or "",
						"il": row.get("il") or "",
						"ilce": row.get("ilce") or "",
					},
					update_modified=False,
				)
			else:
				frappe.get_doc(
					{
						"doctype": "TR Tax Office",
						"kod": kod,
						"ad": row.get("ad") or "",
						"il": row.get("il") or "",
						"ilce": row.get("ilce") or "",
					}
				).insert(ignore_permissions=True)
			count += 1
	return count


def after_install() -> None:
	setup_custom_fields()
	load_tax_offices_from_csv()
	setup_tevkifat_rates()
	setup_closing_chains()
	setup_kdv_templates()
	setup_vuk_report_templates()
