# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Project budget position: committed, actual and paid per cost code.

Definitions:

Committed   Every approved obligation, at full value, from the moment it is approved:
            purchase order lines, supplier invoices raised without an order, subcontract
            agreements, cash requisitions, casual sheets, expense claims, stock charged from
            the stores and what winning the bid cost.
Actual      Cost incurred: supplier invoices, accounted requisitions, casual sheets, expense
            claims, stock charged from the stores and what was spent winning the bid.
Paid        The part of the above that has been settled.
Available   Current budget less committed.
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import date_diff, flt, getdate, now_datetime, nowdate

from project_management_muhick.muhick_sales.bids import bid_costs_position, bid_price, project_bid
from project_management_muhick.utils import calc
from project_management_muhick.utils.common import setting, user_has_any_role

UNALLOCATED = ""
# the budget's sections that hold what is requested from procurement
GOODS_SECTIONS = ("Equipment", "Installation Materials", "Tools and Equipment")


# ------------------------------------------------------------------ lookups
def get_approved_budget(project) -> str | None:
	if not project:
		return None
	return frappe.db.get_value("Project Budget", {"project": project, "docstatus": 1}, "name")


def get_site_warehouses(project) -> list[str]:
	return frappe.get_all(
		"Warehouse",
		filters={"muhick_project": project, "muhick_store_type": ("in", ("Site Store", "Client Store"))},
		pluck="name",
	)


def get_budget_rows(budget) -> dict:
	"""Cost code summary rows of a project budget keyed by cost code."""
	rows = frappe.get_all(
		"Project Budget Cost Code",
		filters={"parent": budget, "parenttype": "Project Budget"},
		fields=[
			"name", "cost_code", "original_budget", "approved_variations", "current_budget",
			"opening_actual", "opening_paid", "etc_is_manual", "estimate_to_complete",
		],
	)
	return {r.cost_code: r for r in rows}


def get_budget_rate(project, item_code) -> float:
	"""Budgeted cost of one unit of an item on the project's approved budget, in the company's currency
	without VAT (0 when not budgeted)."""
	budget = get_approved_budget(project)
	if not budget or not item_code:
		return 0.0
	line = frappe.db.get_value(
		"Project Budget Line", {"parent": budget, "parenttype": "Project Budget", "item_code": item_code}, ["qty", "amount"], as_dict=True
	)
	return flt(line.amount) / flt(line.qty) if line and flt(line.qty) else 0.0


def line_places(project):
	"""What tells the milestone a budget line sits in: the one it was linked to, else the one named after its stage. A
	line in neither, whose stage is none of the project's milestones, belongs to no milestone in particular."""
	milestones = frappe.get_all(
		"Task",
		filters={"project": project, "is_group": 1, "parent_task": ("is", "not set"), "status": ("!=", "Cancelled")},
		fields=["name", "type"],
	)
	names = {m.name for m in milestones}
	by_stage = {}
	for m in milestones:
		if m.type:
			by_stage.setdefault(m.type, m.name)
	return lambda line: line.phase if line.phase in names else by_stage.get(line.stage)


def get_budget_cost_code(project, item_code, milestone=None) -> str | None:
	"""Cost code an item is budgeted under when it is budgeted under exactly one, looking first at a milestone if one
	is given; for an item not in the budget, the item's own Default Cost Code."""
	if not item_code:
		return None
	budget = get_approved_budget(project)
	lines = (
		frappe.get_all("Project Budget Line", filters={"parent": budget, "item_code": item_code}, fields=["cost_code", "stage", "phase"])
		if budget
		else []
	)
	codes = {line.cost_code for line in lines}
	if len(codes) > 1 and milestone:
		place_of = line_places(project)
		codes = {line.cost_code for line in lines if place_of(line) == milestone} or codes
	if len(codes) == 1:
		return codes.pop()
	# under several cost codes the user chooses
	return None if codes else frappe.get_cached_value("Item", item_code, "muhick_cost_code")


# ------------------------------------------------------------------ position
def _empty():
	return {"committed": 0.0, "actual": 0.0, "paid": 0.0}


def get_position(project) -> dict:
	"""{cost_code: {committed, actual, paid}} from live transactions (opening figures excluded)."""
	pos = defaultdict(_empty)

	_purchase_orders(project, pos)
	_purchase_invoices(project, pos)
	_subcontracts(project, pos)
	_requisitions(project, pos)
	_casual_sheets(project, pos)
	_reimbursement_claims(project, pos)
	_equipment_hire(project, pos)
	_store_charges(project, pos)
	_bid_costs(project, pos)

	return {k or UNALLOCATED: v for k, v in pos.items()}


def _purchase_orders(project, pos):
	"""Approved purchase orders are commitments at full value. A closed order is only
	committed for what was actually received or billed."""
	rows = frappe.db.sql(
		"""
		select poi.parent as po, ifnull(poi.muhick_cost_code, '') as cost_code,
			po.status, po.conversion_rate, po.advance_paid, po.base_grand_total,
			sum(poi.base_net_amount) as base_net_amount,
			sum(greatest(ifnull(poi.billed_amt, 0), ifnull(poi.received_qty, 0) * ifnull(poi.rate, 0))) as used_amount
		from `tabPurchase Order Item` poi
		inner join `tabPurchase Order` po on po.name = poi.parent
		where po.docstatus = 1 and poi.project = %(project)s
		group by poi.parent, ifnull(poi.muhick_cost_code, '')
		""",
		{"project": project},
		as_dict=True,
	)
	invoice_paid = _invoice_paid_by_order(project)

	for r in rows:
		if r.status == "Closed":
			committed = flt(r.used_amount) * flt(r.conversion_rate or 1)
		else:
			committed = flt(r.base_net_amount)
		pos[r.cost_code]["committed"] += committed

		# paid on an order = the larger of its advance and what was paid on its invoices,
		# so an advance later allocated to an invoice is never counted twice
		advance_base = flt(r.advance_paid) * flt(r.conversion_rate or 1)
		advance_ratio = min(advance_base / flt(r.base_grand_total), 1) if flt(r.base_grand_total) > 0 else 0
		advance_net = flt(r.base_net_amount) * advance_ratio
		pos[r.cost_code]["paid"] += max(advance_net, invoice_paid.pop((r.po, r.cost_code), 0.0))

	# invoices paid against orders that carry no line for this project/cost code combination
	for (_po, cost_code), amount in invoice_paid.items():
		pos[cost_code]["paid"] += amount


def _invoice_paid_by_order(project) -> dict:
	"""Settled part of supplier invoice lines, keyed by (purchase order or '', cost code)."""
	rows = frappe.db.sql(
		"""
		select ifnull(pii.purchase_order, '') as po, ifnull(pii.muhick_cost_code, '') as cost_code,
			pii.base_net_amount, pi.grand_total, pi.outstanding_amount
		from `tabPurchase Invoice Item` pii
		inner join `tabPurchase Invoice` pi on pi.name = pii.parent
		where pi.docstatus = 1 and pi.is_return = 0 and pii.project = %(project)s
		""",
		{"project": project},
		as_dict=True,
	)
	paid = defaultdict(float)
	for r in rows:
		paid[(r.po, r.cost_code)] += flt(r.base_net_amount) * calc.paid_share(r.grand_total, r.outstanding_amount)
	return paid


def _purchase_invoices(project, pos):
	"""Every supplier invoice is actual cost. Invoices raised without a purchase order (and
	not against a subcontract, which is committed by its agreement) are also commitments."""
	rows = frappe.db.sql(
		"""
		select ifnull(pii.muhick_cost_code, '') as cost_code,
			sum(pii.base_net_amount) as actual,
			sum(case when ifnull(pii.purchase_order, '') = ''
					and ifnull(pi.muhick_subcontract_agreement, '') = ''
				then pii.base_net_amount else 0 end) as direct
		from `tabPurchase Invoice Item` pii
		inner join `tabPurchase Invoice` pi on pi.name = pii.parent
		where pi.docstatus = 1 and pii.project = %(project)s
		group by ifnull(pii.muhick_cost_code, '')
		""",
		{"project": project},
		as_dict=True,
	)
	for r in rows:
		pos[r.cost_code]["actual"] += flt(r.actual)
		pos[r.cost_code]["committed"] += flt(r.direct)


def _subcontracts(project, pos):
	"""An approved subcontract is committed at its contract amount; once completed, at what
	was certified. Its cost and payments arrive through the purchase invoices."""
	rows = frappe.get_all(
		"Subcontract Agreement",
		filters={"project": project, "docstatus": 1},
		fields=["cost_code", "status", "contract_amount", "certified_to_date"],
	)
	for r in rows:
		amount = r.certified_to_date if r.status == "Completed" else r.contract_amount
		pos[r.cost_code or UNALLOCATED]["committed"] += flt(amount)


def _requisitions(project, pos):
	"""Approved cash requisitions are committed at the approved amount until they are
	accounted for, then at what was actually spent."""
	reqs = frappe.get_all(
		"Project Requisition",
		filters={"project": project, "docstatus": 1, "status": ("not in", ("Rejected", "Cancelled"))},
		fields=["name", "status", "total_amount", "amount_issued", "returned_amount"],
	)
	if not reqs:
		return
	names = [r.name for r in reqs]
	items = defaultdict(lambda: defaultdict(float))
	for row in frappe.get_all(
		"Project Requisition Item", filters={"parent": ("in", names)}, fields=["parent", "cost_code", "amount"]
	):
		items[row.parent][row.cost_code] += flt(row.amount)
	expenses = defaultdict(lambda: defaultdict(float))
	for row in frappe.get_all(
		"Project Requisition Expense", filters={"parent": ("in", names)}, fields=["parent", "cost_code", "amount"]
	):
		expenses[row.parent][row.cost_code] += flt(row.amount)

	for r in reqs:
		accounted = r.status in ("Accounted", "Closed")
		if accounted:
			for cost_code, amount in expenses[r.name].items():
				pos[cost_code]["committed"] += amount
				pos[cost_code]["actual"] += amount
				pos[cost_code]["paid"] += amount
		else:
			issued_ratio = min(flt(r.amount_issued) / flt(r.total_amount), 1) if flt(r.total_amount) else 0
			for cost_code, amount in items[r.name].items():
				pos[cost_code]["committed"] += amount
				pos[cost_code]["paid"] += amount * issued_ratio


def _casual_sheets(project, pos):
	rows = frappe.get_all(
		"Casual Sheet",
		filters={"project": project, "docstatus": 1},
		fields=["cost_code", "status", "total_amount"],
	)
	for r in rows:
		bucket = pos[r.cost_code or UNALLOCATED]
		bucket["committed"] += flt(r.total_amount)
		bucket["actual"] += flt(r.total_amount)
		if r.status == "Paid":
			bucket["paid"] += flt(r.total_amount)


def _reimbursement_claims(project, pos):
	"""An approved expense claim for the project is committed and incurred; paid once refunded."""
	claims = frappe.get_all(
		"Reimbursement Claim", filters={"project": project, "docstatus": 1}, fields=["name", "status"]
	)
	if not claims:
		return
	paid = {c.name for c in claims if c.status == "Paid"}
	for row in frappe.get_all(
		"Reimbursement Claim Item",
		filters={"parent": ("in", [c.name for c in claims])},
		fields=["parent", "cost_code", "amount"],
	):
		bucket = pos[row.cost_code or UNALLOCATED]
		bucket["committed"] += flt(row.amount)
		bucket["actual"] += flt(row.amount)
		if row.parent in paid:
			bucket["paid"] += flt(row.amount)


def _equipment_hire(project, pos):
	"""Company equipment is charged to a project at a daily hire rate for the days it is held.
	It is an internal charge, so it counts as cost and is never outstanding."""
	today = getdate(nowdate())
	for a in frappe.get_all(
		"Project Equipment Allocation",
		filters={"project": project, "daily_hire_rate": (">", 0), "cost_code": ("is", "set"), "status": ("!=", "Lost")},
		fields=["cost_code", "allocated_on", "returned_on", "daily_hire_rate", "quantity"],
	):
		days = max(date_diff(getdate(a.returned_on) if a.returned_on else today, getdate(a.allocated_on)) + 1, 0)
		charge = days * flt(a.daily_hire_rate) * flt(a.quantity or 1)
		bucket = pos[a.cost_code]
		bucket["committed"] += charge
		bucket["actual"] += charge
		bucket["paid"] += charge


def _store_charges(project, pos):
	"""Stock drawn from the company's own stores is charged to the project at its stock value.

	Charged rows are flagged on the stock entry ("Charge to Project Budget"); material bought on
	a project purchase order is already committed by that order and is not charged again.
	Stock returned from site is not credited: it was bought for the project.
	"""
	site = tuple(get_site_warehouses(project)) or ("",)
	rows = frappe.db.sql(
		"""
		select ifnull(sed.muhick_cost_code, '') as cost_code, sum(sed.amount) as amount
		from `tabStock Entry Detail` sed
		inner join `tabStock Entry` se on se.name = sed.parent
		where se.docstatus = 1 and sed.muhick_charge_to_project = 1
			and (
				(se.purpose = 'Material Transfer' and sed.t_warehouse in %(site)s
					and ifnull(sed.s_warehouse, '') not in %(site)s)
				or (se.purpose = 'Material Issue'
					and ifnull(nullif(sed.project, ''), se.project) = %(project)s
					and ifnull(sed.s_warehouse, '') not in %(site)s)
			)
		group by ifnull(sed.muhick_cost_code, '')
		""",
		{"project": project, "site": site},
		as_dict=True,
	)
	for r in rows:
		bucket = pos[r.cost_code]
		bucket["committed"] += flt(r.amount)
		bucket["actual"] += flt(r.amount)
		bucket["paid"] += flt(r.amount)


def _bid_costs(project, pos):
	"""What winning the bid cost (its sales requisitions and bid security charges) is the project's own
	cost once the project starts, under the cost code chosen in Muhick Settings."""
	opportunity = project_bid(project)
	if not opportunity:
		return
	bucket = pos[setting("bid_cost_code") or UNALLOCATED]
	for key, amount in bid_costs_position([opportunity])[opportunity].items():
		bucket[key] += amount


# ------------------------------------------------------------------ persist
def update_budget(project):
	"""Recompute the position of the project's approved budget and store it on the budget."""
	budget = get_approved_budget(project)
	if not budget:
		return None
	rows = get_budget_rows(budget)
	pos = get_position(project)

	totals = defaultdict(float)
	for cost_code, row in rows.items():
		p = pos.pop(cost_code, _empty())
		committed = flt(row.opening_actual) + p["committed"]
		actual = flt(row.opening_actual) + p["actual"]
		paid = flt(row.opening_paid) + p["paid"]
		etc = flt(row.estimate_to_complete) if row.etc_is_manual else max(flt(row.current_budget) - committed, 0)
		forecast = calc.forecast_final_cost(row.current_budget, committed, etc)
		values = {
			"committed": committed,
			"actual": actual,
			"paid": paid,
			"available": calc.available_budget(row.current_budget, committed),
			"estimate_to_complete": etc,
			"forecast_final_cost": forecast,
			"forecast_variance": flt(row.current_budget) - forecast,
		}
		frappe.db.set_value("Project Budget Cost Code", row.name, values, update_modified=False)
		for key in ("committed", "actual", "paid", "forecast_final_cost"):
			totals[key] += values[key]
		totals["original"] += flt(row.original_budget)
		totals["variations"] += flt(row.approved_variations)
		totals["current"] += flt(row.current_budget)

	# anything left was committed on a cost code that is not in the budget (or with no cost code)
	unbudgeted = sum(p["committed"] for p in pos.values())
	totals["committed"] += unbudgeted
	totals["actual"] += sum(p["actual"] for p in pos.values())
	totals["paid"] += sum(p["paid"] for p in pos.values())
	totals["forecast_final_cost"] += unbudgeted

	contract_value = revised_contract_value(project)
	frappe.db.set_value(
		"Project Budget",
		budget,
		{
			"total_approved_variations": totals["variations"],
			"total_current_budget": totals["current"],
			"total_committed": totals["committed"],
			"total_actual": totals["actual"],
			"total_paid": totals["paid"],
			"total_available": totals["current"] - totals["committed"],
			"total_forecast_final_cost": totals["forecast_final_cost"],
			"unbudgeted_committed": unbudgeted,
			"contract_value": contract_value,
			"planned_margin": contract_value - totals["current"],
			"forecast_margin": contract_value - totals["forecast_final_cost"],
			"planned_margin_percent": calc.margin_percent(contract_value, totals["current"]),
			"forecast_margin_percent": calc.margin_percent(contract_value, totals["forecast_final_cost"]),
			"last_recalculated_on": now_datetime(),
		},
		update_modified=False,
	)
	return budget


def revised_contract_value(project) -> float:
	"""The project's contract value with its approved variations, without VAT. Until the project has one (its
	handover sets it), what its bid is priced at."""
	value = frappe.db.get_value(
		"Project", project, ["muhick_contract_value", "muhick_approved_variations"], as_dict=True
	)
	if not value:
		return 0.0
	return (flt(value.muhick_contract_value) or bid_price(project)) + flt(value.muhick_approved_variations)


def refresh_projects(projects):
	"""Recalculate budgets after a transaction changed. Never blocks the transaction."""
	for project in {p for p in projects if p}:
		try:
			update_budget(project)
		except Exception:
			frappe.log_error(title=f"Muhick: budget position update failed for {project}")


def refresh_all_budgets():
	"""Nightly safety net so the stored position never drifts from the transactions."""
	for project in frappe.get_all("Project Budget", filters={"docstatus": 1}, pluck="project"):
		refresh_projects([project])
	frappe.db.commit()


@frappe.whitelist()
def recalculate(project: str):
	frappe.has_permission("Project Budget", "read", throw=True)
	budget = update_budget(project)
	if not budget:
		frappe.throw(_("Project {0} has no approved budget.").format(project))
	return budget


# ------------------------------------------------------------------ checks
def get_available(project, pending_requests=False, exclude_material_request=None) -> dict | None:
	"""{cost_code: available} for the approved budget, or None when there is no approved budget."""
	budget = get_approved_budget(project)
	if not budget:
		return None
	rows = get_budget_rows(budget)
	pos = get_position(project)
	pending = _pending_material_requests(project, exclude_material_request) if pending_requests else {}
	return {
		cost_code: flt(row.current_budget)
		- flt(row.opening_actual)
		- pos.get(cost_code, _empty())["committed"]
		- flt(pending.get(cost_code))
		for cost_code, row in rows.items()
	}


def _pending_material_requests(project, exclude=None) -> dict:
	"""Approved purchase requests not yet ordered, so several requests cannot each pass the check."""
	rows = frappe.db.sql(
		"""
		select ifnull(mri.muhick_cost_code, '') as cost_code,
			sum(mri.amount * greatest(1 - ifnull(mri.ordered_qty, 0) / nullif(mri.stock_qty, 0), 0)) as amount
		from `tabMaterial Request Item` mri
		inner join `tabMaterial Request` mr on mr.name = mri.parent
		where mr.docstatus = 1 and mr.material_request_type = 'Purchase'
			and mr.status not in ('Stopped', 'Cancelled')
			and mri.project = %(project)s and mr.name != %(exclude)s
		group by ifnull(mri.muhick_cost_code, '')
		""",
		{"project": project, "exclude": exclude or ""},
		as_dict=True,
	)
	return {r.cost_code: flt(r.amount) for r in rows}


# ------------------------------------------------------------------ quantities
def in_stock_unit(item_code, qty, uom) -> float:
	from erpnext.stock.get_item_details import get_conversion_factor

	if not flt(qty) or not uom:
		return flt(qty)
	return flt(qty) * flt(get_conversion_factor(item_code, uom).get("conversion_factor") or 1)


def row_stock_qty(row) -> float:
	return flt(row.get("stock_qty")) or flt(row.qty) * flt(row.get("conversion_factor") or 1)


def budgeted_quantities(project, items=None, milestone=None) -> tuple[dict, set]:
	"""({item: budgeted quantity in its stock unit}, {items the budget places in milestones}). An approved
	revision adds to the budget's lines and leaves them as they are. With a milestone, a line in another does not
	count; a line in none, and a revision, count for every milestone. All items unless some are named."""
	budget = get_approved_budget(project)
	budgeted, placed, revised = defaultdict(float), set(), set()
	if not budget or (items is not None and not items):
		return {}, placed
	place_of = line_places(project) if milestone else None
	named = ("in", list(items)) if items is not None else ("is", "set")
	for line in frappe.get_all(
		"Project Budget Line",
		filters={"parent": budget, "parenttype": "Project Budget", "item_code": named},
		fields=["item_code", "qty", "people", "uom", "stage", "phase", "contract_percent"],
	):
		place = place_of(line) if milestone else None
		if place:
			placed.add(line.item_code)
		if not place or place == milestone:
			qty = calc.budget_line_quantity(line.qty, line.people, line.contract_percent)
			budgeted[line.item_code] += in_stock_unit(line.item_code, qty, line.uom)
	revisions = frappe.get_all("Project Budget Revision", filters={"project_budget": budget, "docstatus": 1}, pluck="name")
	if revisions:
		for line in frappe.get_all(
			"Project Budget Revision Line",
			filters={"parent": ("in", revisions), "parenttype": "Project Budget Revision", "item_code": named},
			fields=["item_code", "change_qty"],
		):
			if flt(line.change_qty):
				budgeted[line.item_code] += flt(line.change_qty)
				revised.add(line.item_code)
	return {item: max(qty, 0.0) for item, qty in budgeted.items() if qty > 0 or item in revised}, placed


def quantity_to_date(project, items, exclude_request=None, milestone=None) -> dict:
	"""{item: stock quantity} asked for or bought on the project: approved purchase requests (a stopped one
	for what was ordered from it), and orders and invoices raised without a request or order behind them.
	With a milestone, only the requests raised for it: nothing else names one."""
	if not items:
		return {}
	by_milestone = "and mr.muhick_phase = %(milestone)s" if milestone else ""
	queries = [
		f"""
		select mri.item_code,
			sum(case when mr.status = 'Stopped' then ifnull(mri.ordered_qty, 0)
				else greatest(ifnull(mri.stock_qty, 0), ifnull(mri.ordered_qty, 0)) end) as qty
		from `tabMaterial Request Item` mri
		inner join `tabMaterial Request` mr on mr.name = mri.parent
		where mr.docstatus = 1 and mr.material_request_type = 'Purchase' {by_milestone}
			and mri.project = %(project)s and mri.item_code in %(items)s and mr.name != %(name)s
		group by mri.item_code
		"""
	]
	if not milestone:
		queries += [
			# a closed order only for what was received, as in its commitment
			"""
			select poi.item_code,
				sum(case when po.status = 'Closed' then ifnull(poi.received_qty, 0) * ifnull(poi.conversion_factor, 1)
					else poi.stock_qty end) as qty
			from `tabPurchase Order Item` poi
			inner join `tabPurchase Order` po on po.name = poi.parent
			where po.docstatus = 1 and poi.project = %(project)s and poi.item_code in %(items)s
				and ifnull(poi.material_request_item, '') = ''
			group by poi.item_code
			""",
			"""
			select pii.item_code, sum(pii.stock_qty) as qty
			from `tabPurchase Invoice Item` pii
			inner join `tabPurchase Invoice` pi on pi.name = pii.parent
			where pi.docstatus = 1 and pii.project = %(project)s and pii.item_code in %(items)s
				and ifnull(pii.purchase_order, '') = '' and ifnull(pi.muhick_subcontract_agreement, '') = ''
			group by pii.item_code
			""",
		]
	params = {"project": project, "items": tuple(items), "name": exclude_request or "", "milestone": milestone}
	total = defaultdict(float)
	for query in queries:
		for r in frappe.db.sql(query, params, as_dict=True):
			total[r.item_code] += flt(r.qty)
	return total


def quantity_overruns(project, quantities, milestone=None, exclude_request=None) -> list[str]:
	"""Each budgeted item a document takes over its budgeted quantity; quantities: {item: stock quantity
	it adds}. An item the budget places in milestones is counted within the document's milestone; any other over
	the whole project. An item placed only in other milestones is left to the request's phase check."""
	budgeted, placed = budgeted_quantities(project, set(quantities), milestone)
	counted = set(quantities) & set(budgeted)
	to_date = dict(quantity_to_date(project, counted - placed, exclude_request))
	to_date.update(quantity_to_date(project, counted & placed, exclude_request, milestone))
	over = []
	for item, total in calc.quantity_excess(budgeted, to_date, quantities).items():
		if item in placed:
			subject = frappe.db.get_value("Task", milestone, "subject")
			over.append(
				_("{0}: {1} requested to date for {2} against {3} budgeted for it").format(item, f"{total:g}", subject, f"{budgeted[item]:g}")
			)
		else:
			over.append(_("{0}: {1} requested or ordered to date against {2} budgeted").format(item, f"{total:g}", f"{budgeted[item]:g}"))
	return over


def beyond_requests(rows) -> dict:
	"""{item: stock quantity} on the (item, stock quantity, request row) rows of a requisition or order
	that no approved request covers."""
	sources = tuple({row[2] for row in rows if row[2]})
	open_qty = {}
	if sources:
		for r in frappe.db.sql(
			"""
			select mri.name, mri.stock_qty, mri.ordered_qty
			from `tabMaterial Request Item` mri
			inner join `tabMaterial Request` mr on mr.name = mri.parent
			where mr.docstatus = 1 and mr.status != 'Stopped' and mri.name in %(rows)s
			""",
			{"rows": sources},
			as_dict=True,
		):
			open_qty[r.name] = max(flt(r.stock_qty) - flt(r.ordered_qty), 0)
	return calc.beyond_requests(rows, open_qty)


def milestone_needs(project, milestone) -> list:
	"""What the approved budget places in a milestone to request: one row per item and cost code, in the item's
	stock unit, with what a unit is budgeted at and when it is needed."""
	budget = get_approved_budget(project)
	if not budget:
		return []
	place_of = line_places(project)
	needs = {}
	for line in frappe.get_all(
		"Project Budget Line",
		filters={"parent": budget, "parenttype": "Project Budget", "item_code": ("is", "set"), "section": ("in", GOODS_SECTIONS)},
		fields=["item_code", "qty", "people", "uom", "stage", "phase", "contract_percent", "amount", "cost_code", "required_by_date", "procurement_type"],
		order_by="parentfield asc, idx asc",
	):
		qty = in_stock_unit(line.item_code, calc.budget_line_quantity(line.qty, line.people, line.contract_percent), line.uom)
		if qty <= 0 or line.procurement_type == "Not Applicable" or place_of(line) != milestone:
			continue
		need = needs.setdefault(
			(line.item_code, line.cost_code),
			{"item_code": line.item_code, "cost_code": line.cost_code, "qty": 0.0, "amount": 0.0, "required_by": line.required_by_date},
		)
		need["qty"] += qty
		need["amount"] += flt(line.amount)
	return [{**need, "rate": need["amount"] / need["qty"]} for need in needs.values()]


def unplaced_stages(project, names=()) -> list:
	"""The stages of the project's budget whose goods sit in no milestone, so that no request per milestone reaches them.
	names: milestones not created yet, of a plan still being prepared, that a stage's name may match."""
	budget = frappe.db.get_value("Project Budget", {"project": project, "docstatus": ("<", 2)}, "name")
	if not budget:
		return []
	place_of = line_places(project)
	stages = set()
	for line in frappe.get_all(
		"Project Budget Line",
		filters={"parent": budget, "parenttype": "Project Budget", "item_code": ("is", "set"), "section": ("in", GOODS_SECTIONS)},
		fields=["stage", "phase"],
	):
		if not place_of(line) and (line.stage or "") not in names:
			stages.add(line.stage or "")
	return sorted(stages)


def with_quantities(project, status, remarks, quantities, milestone=None, exclude_request=None) -> tuple[str, str]:
	"""A value check's result with the quantities checked too: an item over its budgeted quantity is over
	budget however much its cost code has left."""
	over = quantity_overruns(project, quantities, milestone, exclude_request)
	if not over:
		return status, remarks
	return (status if status == "Not Budgeted" else "Exceeds Budget"), "; ".join(filter(None, [remarks, *over]))


def evaluate(project, amounts, pending_requests=False, exclude_material_request=None, allowance=None) -> tuple[str, str]:
	"""Budget status and an explanation for a set of {cost_code: amount} about to be committed.

	allowance: {cost_code: amount} already approved over budget (an over-budget Material Request
	that went through the extended approval route), which may be committed without a second approval.
	"""
	amounts = {k or UNALLOCATED: flt(v) for k, v in (amounts or {}).items() if flt(v)}
	if not project or not amounts:
		return "Not Applicable", ""
	available = get_available(project, pending_requests, exclude_material_request)
	if available is None:
		return "Not Budgeted", _("Project {0} has no approved budget.").format(project)
	for cost_code, extra in (allowance or {}).items():
		# an approved over-budget request also covers a cost code that was never budgeted
		available[cost_code or UNALLOCATED] = flt(available.get(cost_code or UNALLOCATED)) + flt(extra)

	if setting("budget_check_level", "Cost Code") == "Project Total":
		total, free = sum(amounts.values()), sum(available.values())
		status = calc.budget_status(total, free)
		return status, _("Requested {0} against {1} available on the project.").format(
			frappe.format_value(total, "Currency"), frappe.format_value(free, "Currency")
		)

	not_budgeted = [cc or _("(no cost code)") for cc in amounts if cc not in available]
	exceeded = [
		_("{0}: {1} requested, {2} available").format(
			cc, frappe.format_value(amount, "Currency"), frappe.format_value(available[cc], "Currency")
		)
		for cc, amount in amounts.items()
		if cc in available and calc.budget_status(amount, available[cc]) == "Exceeds Budget"
	]
	if not_budgeted:
		return "Not Budgeted", _("Not in the approved budget: {0}").format(", ".join(not_budgeted))
	if exceeded:
		return "Exceeds Budget", "; ".join(exceeded)
	return "Within Budget", ""


def enforce(doc, action_setting, status, remarks):
	"""Apply the configured action (Stop / Warn / Ignore) to a document that is over budget."""
	if status not in ("Exceeds Budget", "Not Budgeted"):
		return
	action = setting(action_setting, "Warn")
	if action == "Ignore":
		return
	message = _("{0} {1}: {2}. {3}").format(_(doc.doctype), doc.name or "", _(status), remarks)
	override_role = setting("budget_override_role")
	if action == "Stop" and not (override_role and user_has_any_role(override_role)):
		frappe.throw(
			message + " " + _("Raise a Project Budget Revision (Cost Control Sheet) and have it approved first."),
			title=_("Budget Exceeded"),
		)
	frappe.msgprint(message, title=_("Budget Check"), indicator="orange")
