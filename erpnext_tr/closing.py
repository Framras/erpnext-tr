# Copyright (c) 2026, Framras and contributors
# License: MIT
"""TR Dönem Kapanışı motoru — önizleme, kapatma, iptal."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from erpnext_tr.setup import _norm, find_account_by_number


class ClosingCycleError(frappe.ValidationError):
	pass


class ClosingLockError(frappe.ValidationError):
	pass


def get_period_balance(
	company: str,
	account: str,
	from_date: str,
	to_date: str,
) -> float:
	"""Hesap + alt hesaplar için dönem bakiyesi (borç − alacak)."""
	accounts = [account] + (frappe.db.get_descendants("Account", account) or [])
	from frappe.query_builder.functions import Sum

	GLE = frappe.qb.DocType("GL Entry")
	result = (
		frappe.qb.from_(GLE)
		.select((Sum(GLE.debit) - Sum(GLE.credit)).as_("bal"))
		.where(GLE.company == company)
		.where(GLE.account.isin(accounts))
		.where(GLE.is_cancelled == 0)
		.where(GLE.posting_date >= from_date)
		.where(GLE.posting_date <= to_date)
		.run()
	)
	return flt(result[0][0] if result else 0)


def build_closing_graph(company: str, method: str) -> dict[str, str]:
	"""Kaynak → hedef haritası; yöntem filtresi uygulanır."""
	rows = frappe.get_all(
		"Account",
		filters={"company": company, "custom_kapanis_hesabi": ("is", "set")},
		fields=["name", "account_number", "custom_kapanis_hesabi"],
	)
	graph: dict[str, str] = {}
	for row in rows:
		num = _norm(row.account_number)
		if not num:
			continue
		prefix = num[:3] if len(num) >= 3 else num
		if not prefix.isdigit():
			continue
		code = int(prefix)
		include = False
		if 600 <= code <= 690:
			include = True
		elif method == "7/A" and 710 <= code <= 781:
			include = True
		elif method == "7/B" and code in (798, 799):
			include = True
		if include:
			graph[row.name] = row.custom_kapanis_hesabi
	return graph


def detect_cycle(graph: dict[str, str]) -> list[str] | None:
	"""Döngü varsa düğüm listesi döner."""
	WHITE, GRAY, BLACK = 0, 1, 2
	color: dict[str, int] = defaultdict(int)
	parent: dict[str, str | None] = {}

	def dfs(node: str) -> list[str] | None:
		color[node] = GRAY
		nxt = graph.get(node)
		if nxt:
			if color[nxt] == GRAY:
				# cycle
				cycle = [nxt, node]
				return cycle
			if color[nxt] == WHITE:
				parent[nxt] = node
				found = dfs(nxt)
				if found:
					return found
		color[node] = BLACK
		return None

	for node in list(graph.keys()):
		if color[node] == WHITE:
			found = dfs(node)
			if found:
				return found
	return None


def topological_deepest_first(graph: dict[str, str]) -> list[str]:
	"""En derin kaynak önce — indegree tersine (hedeflere giden yapraklar önce)."""
	nodes = set(graph.keys()) | set(graph.values())
	# Kenar: source → target. Derinlik: target'a giden yolların uzunluğu
	depth: dict[str, int] = {n: 0 for n in nodes}

	changed = True
	while changed:
		changed = False
		for src, tgt in graph.items():
			new_depth = depth.get(tgt, 0) + 1
			# aslında source depth = target depth + 1 along edge src->tgt meaning src closes into tgt
			# deepest source = farthest from ultimate sink
			cand = depth[tgt] + 1
			if cand > depth[src]:
				depth[src] = cand
				changed = True

	sources = list(graph.keys())
	sources.sort(key=lambda n: (-depth.get(n, 0), n))
	return sources


def compute_preview(
	company: str,
	from_date: str,
	to_date: str,
	vergi_karsiligi: float = 0.0,
) -> dict[str, Any]:
	"""Önizleme satırları üretir; kayıt atmaz."""
	method = frappe.db.get_value("Company", company, "custom_maliyet_yontemi") or "7/A"
	graph = build_closing_graph(company, method)
	cycle = detect_cycle(graph)
	if cycle:
		frappe.throw(
			_("Kapanış hesabı döngüsü tespit edildi: {0}").format(" → ".join(cycle)),
			exc=ClosingCycleError,
		)

	order = topological_deepest_first(graph)
	balances: dict[str, float] = {}
	for account in set(list(graph.keys()) + list(graph.values())):
		balances[account] = get_period_balance(company, account, from_date, to_date)

	rows: list[dict[str, Any]] = []
	for source in order:
		target = graph.get(source)
		if not target:
			continue

		# Grup kaynak: bakiyesi olan leaf'ler ayrı satır; leaf yoksa grup bakiyesi
		source_is_group = cint(frappe.db.get_value("Account", source, "is_group"))
		source_items: list[tuple[str, float]] = []
		if source_is_group:
			desc = list(frappe.db.get_descendants("Account", source) or [])
			leaves = [d for d in desc if not frappe.db.get_value("Account", d, "is_group")]
			for leaf in leaves:
				leaf_bal = get_period_balance(company, leaf, from_date, to_date)
				# simülasyondan gelen aktarımlar leaf'te değil grupta tutulduğu için
				# yalnızca gerçek leaf bakiyesini kullan
				if abs(flt(leaf_bal)) >= 0.00001:
					source_items.append((leaf, flt(leaf_bal)))
			if not source_items:
				bal = flt(balances.get(source, 0))
				if abs(bal) >= 0.00001:
					source_items.append((source, bal))
		else:
			bal = flt(balances.get(source, 0))
			if abs(bal) >= 0.00001:
				source_items.append((source, bal))

		for src_account, bal in source_items:
			row_target = target
			src_num = _norm(frappe.db.get_value("Account", source, "account_number"))
			effective_bal = bal
			# 690 → 590 (kâr / alacak bakiye) veya 591 (zarar / borç bakiye)
			if src_num.startswith("690"):
				if bal > 0:
					# Borç bakiyesi = dönem zararı → 591
					target_591 = find_account_by_number(company, "591")
					if target_591:
						row_target = target_591
				elif flt(vergi_karsiligi):
					# Kâr: vergi karşılığı düşülür
					profit = abs(bal)
					net = profit - flt(vergi_karsiligi)
					if net >= 0:
						effective_bal = -net
					else:
						effective_bal = abs(net)
						target_591 = find_account_by_number(company, "591")
						if target_591:
							row_target = target_591

			amount = abs(flt(effective_bal))
			if amount < 0.00001:
				continue

			rows.append(
				{
					"kaynak_hesap": src_account,
					"hedef_hesap": row_target,
					"tutar": amount,
					"kaynak_bakiye": bal,
				}
			)
			balances[source] = 0.0
			if bal > 0:
				balances[row_target] = flt(balances.get(row_target, 0)) + amount
			else:
				balances[row_target] = flt(balances.get(row_target, 0)) - amount

	acc_690 = find_account_by_number(company, "690")
	donem_kari = 0.0
	if acc_690:
		raw = balances.get(acc_690)
		if raw is None:
			raw = get_period_balance(company, acc_690, from_date, to_date)
		donem_kari = -flt(raw)

	return {"rows": rows, "donem_kari": donem_kari, "method": method}


def assert_no_pcv_conflict(company: str, from_date: str, to_date: str) -> None:
	"""Gönderilmiş PCV aynı dönemde varsa hata."""
	if not frappe.db.exists("DocType", "Period Closing Voucher"):
		return
	conflicts = frappe.get_all(
		"Period Closing Voucher",
		filters={
			"company": company,
			"docstatus": 1,
			"period_start_date": ("<=", to_date),
			"period_end_date": (">=", from_date),
		},
		fields=["name"],
		limit=1,
	)
	if conflicts:
		frappe.throw(
			_(
				"Bu dönemde gönderilmiş Period Closing Voucher var ({0}). "
				"TR Dönem Kapanışı PCV ile birlikte çalışmaz."
			).format(conflicts[0].name)
		)


def assert_accounting_period_open(company: str, from_date: str, to_date: str) -> None:
	"""closed_documents child'ında Journal Entry kapalıysa motor çalışmaz."""
	periods = frappe.get_all(
		"Accounting Period",
		filters={
			"company": company,
			"start_date": ("<=", to_date),
			"end_date": (">=", from_date),
			"disabled": 0,
		},
		fields=["name"],
	)
	for p in periods:
		closed_rows = frappe.get_all(
			"Closed Document",
			filters={"parent": p.name, "document_type": "Journal Entry", "closed": 1},
			limit=1,
		)
		if closed_rows:
			frappe.throw(
				_("Muhasebe dönemi {0} içinde Journal Entry kapalı; TR Dönem Kapanışı çalıştırılamaz.").format(
					p.name
				)
			)


def assert_not_already_closed(company: str, from_date: str, to_date: str, exclude: str | None = None) -> None:
	filters: dict[str, Any] = {
		"sirket": company,
		"durum": "Kapatıldı",
		"donem_baslangic": ("<=", to_date),
		"donem_bitis": (">=", from_date),
	}
	rows = frappe.get_all("TR Period Closing", filters=filters, fields=["name"])
	for row in rows:
		if exclude and row.name == exclude:
			continue
		frappe.throw(
			_("Bu dönem zaten kapatılmış ({0}). Önce iptal edin.").format(row.name),
			exc=ClosingLockError,
		)


def ensure_postable_account(company: str, account: str) -> str:
	"""Grup hesaba yevmiye yazılamaz; leaf yoksa kapanış leaf'i oluşturur."""
	if not account:
		frappe.throw(_("Hesap boş; yevmiye yazılamaz."))
	is_group = frappe.db.get_value("Account", account, "is_group")
	if not is_group:
		return account

	desc = list(frappe.db.get_descendants("Account", account) or [])
	leaves = [d for d in desc if not frappe.db.get_value("Account", d, "is_group")]
	if leaves:
		# Numaralı leaf tercih
		leaves.sort()
		return leaves[0]

	parent = frappe.get_doc("Account", account)
	number = (parent.account_number or "").strip()
	leaf_number = f"{number} 001" if number else ""
	leaf = frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": _("{0} (Kapanış)").format(parent.account_name),
			"parent_account": parent.name,
			"company": company,
			"account_number": leaf_number,
			"is_group": 0,
			"root_type": parent.root_type,
			"report_type": parent.report_type,
			"account_currency": parent.account_currency,
		}
	)
	leaf.flags.ignore_permissions = True
	leaf.insert()
	from frappe.utils.nestedset import rebuild_tree

	rebuild_tree("Account")
	return leaf.name


def create_closing_jv(
	company: str,
	posting_date: str,
	source: str,
	target: str,
	amount: float,
	source_balance: float,
	user_remark: str,
) -> str:
	"""Zincir adımı için tek JV. amount > 0. Grup hesaplar leaf'e çözülür."""
	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("Yevmiye tutarı sıfır olamaz ({0} → {1})").format(source, target))

	source = ensure_postable_account(company, source)
	target = ensure_postable_account(company, target)

	# Borç bakiyesi: kaynak Alacak, hedef Borç; Alacak bakiyesi tersi
	if source_balance >= 0:
		source_debit, source_credit = 0.0, amount
		target_debit, target_credit = amount, 0.0
	else:
		source_debit, source_credit = amount, 0.0
		target_debit, target_credit = 0.0, amount

	je = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"company": company,
			"posting_date": posting_date,
			"user_remark": user_remark,
			"accounts": [
				{
					"account": source,
					"debit_in_account_currency": source_debit,
					"credit_in_account_currency": source_credit,
				},
				{
					"account": target,
					"debit_in_account_currency": target_debit,
					"credit_in_account_currency": target_credit,
				},
			],
		}
	)
	je.flags.ignore_permissions = True
	je.insert()
	je.submit()
	return je.name


def reverse_jv(je_name: str, posting_date: str) -> str:
	"""Ters kayıt JV'si oluşturur."""
	original = frappe.get_doc("Journal Entry", je_name)
	accounts = []
	for row in original.accounts:
		accounts.append(
			{
				"account": row.account,
				"debit_in_account_currency": flt(row.credit_in_account_currency),
				"credit_in_account_currency": flt(row.debit_in_account_currency),
				"party_type": row.party_type,
				"party": row.party,
				"cost_center": row.cost_center,
			}
		)
	je = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"company": original.company,
			"posting_date": posting_date,
			"user_remark": _("İptal: {0}").format(je_name),
			"accounts": accounts,
		}
	)
	je.flags.ignore_permissions = True
	je.insert()
	je.submit()
	return je.name
