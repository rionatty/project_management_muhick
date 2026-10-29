# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Material Request: tie the request to the project budget, phase and approved brands.

The result (Within Budget / Exceeds Budget / Not Budgeted) decides the approval route:
within budget goes to the COO only, anything else also needs the Finance Manager and the
General Manager.
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from project_management_muhick.muhick_projects import budget_engine
from project_management_muhick.muhick_projects.utils import check_phase, get_phases, phase_done
from project_management_muhick.utils.common import get_settings


def validate(doc, method=None):
	project = _resolve_project(doc)
	if doc.get("muhick_priority") == "Urgent" and not (doc.get("muhick_priority_reason") or "").strip():
		frappe.throw(_("Give the reason this request is urgent."))
	_check_stock(doc)
	if not project:
		doc.muhick_budget_status = "Not Applicable"
		doc.muhick_budget_remarks = ""
		if not doc.get("muhick_request_origin"):
			doc.muhick_request_origin = "User Department"
		return

	if not doc.get("muhick_request_origin"):
		doc.muhick_request_origin = "Project"
	_set_cost_codes(doc, project)
	stage = frappe.db.get_value("Task", doc.muhick_phase, "type") if doc.get("muhick_phase") else None
	_check_budget(doc, project, stage)
	_check_brands(doc, project)
	_check_phase(doc, project, stage)
	_note_stock_on_hand(doc)

	needs_reason = doc.muhick_budget_status in ("Exceeds Budget", "Not Budgeted") or doc.get("muhick_out_of_phase")
	leaving_draft = doc.get("workflow_state") not in (None, "", "Draft")
	if needs_reason and leaving_draft and not doc.get("muhick_justification"):
		frappe.throw(
			_("This request is {0}. Enter a justification before sending it for approval.").format(
				_("outside the current phase") if doc.get("muhick_out_of_phase") else _(doc.muhick_budget_status).lower()
			)
		)


def _resolve_project(doc):
	project = doc.get("muhick_project")
	if project:
		for row in doc.items:
			if not row.project:
				row.project = project
		return project
	projects = {row.project for row in doc.items if row.project}
	if len(projects) == 1:
		doc.muhick_project = projects.pop()
	return doc.get("muhick_project")


def _set_cost_codes(doc, project):
	for row in doc.items:
		if not row.get("muhick_cost_code") and row.item_code:
			row.muhick_cost_code = budget_engine.get_budget_cost_code(row.project or project, row.item_code)


def _row_amount(row, project) -> float:
	if flt(row.amount):
		return flt(row.amount)
	rate = flt(row.rate) or budget_engine.get_budget_rate(project, row.item_code)
	return flt(row.qty) * rate


def _check_budget(doc, project, stage=None):
	if doc.material_request_type != "Purchase":
		# issues and transfers move stock that is already paid for or already committed
		doc.muhick_budget_status = "Not Applicable"
		doc.muhick_budget_remarks = ""
		return
	amounts = defaultdict(float)
	for row in doc.items:
		if (row.project or project) == project:
			amounts[row.get("muhick_cost_code") or ""] += _row_amount(row, project)
	status, remarks = budget_engine.evaluate(
		project, amounts, pending_requests=True, exclude_material_request=doc.name
	)
	over_qty = _quantity_overruns(doc, project, stage) if status == "Within Budget" else []
	if over_qty:
		status = "Exceeds Budget"
		remarks = "; ".join(over_qty)
	doc.muhick_budget_status = status
	doc.muhick_budget_remarks = remarks


def _quantity_overruns(doc, project, stage=None) -> list[str]:
	"""Requested quantity to date against the budgeted quantity of each budgeted item. An item the
	budget places in stages is counted within the request's stage (its lines without a stage count for
	every stage); any other item over the whole project. An item budgeted only under other stages is
	left to _check_phase."""
	budgeted, staged = _budgeted_quantities(doc, project, stage)
	if not budgeted:
		return []
	in_stage = {item for item in budgeted if item in staged}
	requested = _requested_to_date(project, set(budgeted) - in_stage, doc.name)
	requested.update(_requested_to_date(project, in_stage, doc.name, stage))
	for row in doc.items:
		if row.item_code in budgeted:
			requested[row.item_code] = requested.get(row.item_code, 0) + flt(row.qty)
	over = []
	for item, qty in budgeted.items():
		if requested.get(item, 0) <= qty + 1e-9:
			continue
		if item in in_stage:
			over.append(
				_("{0}: {1} requested to date for {2} against {3} budgeted for it").format(item, f"{requested[item]:g}", stage, f"{qty:g}")
			)
		else:
			over.append(_("{0}: {1} requested to date against {2} budgeted").format(item, f"{requested[item]:g}", f"{qty:g}"))
	return over


def _budgeted_quantities(doc, project, stage=None):
	"""({item: quantity budgeted for the request's stage}, {items the budget places in stages}). Without
	a stage on the request, every line of an item counts."""
	budget = budget_engine.get_approved_budget(project)
	items = {row.item_code for row in doc.items if row.item_code}
	budgeted, staged = defaultdict(float), set()
	if not budget or not items:
		return {}, staged
	for line in frappe.get_all(
		"Project Budget Line",
		filters={"parent": budget, "parenttype": "Project Budget", "item_code": ("in", list(items))},
		fields=["item_code", "qty", "stage"],
	):
		if stage and line.stage:
			staged.add(line.item_code)
		if not (stage and line.stage) or line.stage == stage:
			budgeted[line.item_code] += flt(line.qty)
	return {item: qty for item, qty in budgeted.items() if qty > 0}, staged


def _requested_to_date(project, items, name, stage=None) -> dict:
	"""{item: quantity on the project's approved purchase requests}, counting only requests raised for a
	milestone of the stage when one is given."""
	if not items:
		return {}
	by_stage = "inner join `tabTask` phase on phase.name = mr.muhick_phase and phase.type = %(stage)s" if stage else ""
	rows = frappe.db.sql(
		f"""
		select mri.item_code, sum(mri.qty) as qty
		from `tabMaterial Request Item` mri
		inner join `tabMaterial Request` mr on mr.name = mri.parent
		{by_stage}
		where mr.docstatus = 1 and mr.material_request_type = 'Purchase'
			and mr.status not in ('Stopped', 'Cancelled')
			and mri.project = %(project)s and mri.item_code in %(items)s and mr.name != %(name)s
		group by mri.item_code
		""",
		{"project": project, "items": tuple(items), "name": name or "", "stage": stage},
		as_dict=True,
	)
	return {r.item_code: flt(r.qty) for r in rows}


def _check_brands(doc, project):
	"""Clients pre-approve brands; a request must match them."""
	approved = frappe.get_all(
		"Project Approved Brand",
		filters={"parent": project, "parenttype": "Project"},
		fields=["item_code", "item_group", "brand"],
	)
	exceptions = []
	for row in doc.items:
		allowed = {a.brand for a in approved if a.item_code and a.item_code == row.item_code}
		if not allowed:
			allowed = {a.brand for a in approved if not a.item_code and a.item_group and a.item_group == row.item_group}
		if not allowed:
			continue
		brand = row.get("brand") or frappe.get_cached_value("Item", row.item_code, "brand")
		if brand not in allowed:
			exceptions.append(
				_("{0}: brand {1} is not the client-approved brand ({2})").format(
					row.item_code, brand or _("not set"), ", ".join(sorted(allowed))
				)
			)
	doc.muhick_spec_exception = "\n".join(exceptions)


def _check_phase(doc, project, stage=None):
	"""Requests are raised per phase. A request for a later phase, or for items the budget places only
	under other stages, needs an explanation."""
	doc.muhick_out_of_phase = 0
	phase = doc.get("muhick_phase")
	if not phase:
		return
	check_phase(project, phase)
	phases = get_phases(project)
	current = next((p for p in phases if not phase_done(p)), None)
	selected = next((p for p in phases if p.name == phase), None)
	if current and selected and selected.name != current.name and selected.exp_start_date and current.exp_end_date:
		if getdate(selected.exp_start_date) > getdate(current.exp_end_date):
			doc.muhick_out_of_phase = 1
	elsewhere = _budgeted_elsewhere(doc, project, stage)
	if elsewhere:
		doc.muhick_out_of_phase = 1
		note = _("Budgeted under another stage: {0}").format("; ".join(elsewhere))
		doc.muhick_budget_remarks = "\n".join(filter(None, [doc.get("muhick_budget_remarks"), note]))


def _budgeted_elsewhere(doc, project, stage) -> list[str]:
	"""The request's items that the approved budget places only under stages other than the request's."""
	budget = budget_engine.get_approved_budget(project)
	items = {row.item_code for row in doc.items if row.item_code}
	if not stage or not budget or not items:
		return []
	stages = defaultdict(set)
	for line in frappe.get_all(
		"Project Budget Line",
		filters={"parent": budget, "parenttype": "Project Budget", "item_code": ("in", list(items))},
		fields=["item_code", "stage"],
	):
		stages[line.item_code].add(line.stage or "")
	return [f"{item} ({', '.join(sorted(found))})" for item, found in stages.items() if stage not in found and "" not in found]


def _note_stock_on_hand(doc):
	"""Flag items already held in the central store so they are not bought again."""
	if doc.material_request_type != "Purchase":
		return  # for store requests the note holds the shortfall instead
	doc.muhick_stock_note = ""
	items = tuple({row.item_code for row in doc.items if row.item_code})
	if not items:
		return
	held = frappe.db.sql(
		"""
		select b.item_code, sum(b.actual_qty) as qty
		from `tabBin` b inner join `tabWarehouse` w on w.name = b.warehouse
		where w.muhick_store_type = 'Central Store' and b.item_code in %(items)s
		group by b.item_code having sum(b.actual_qty) > 0
		""",
		{"items": items},
		as_dict=True,
	)
	if held:
		doc.muhick_stock_note = ", ".join(f"{h.item_code}: {flt(h.qty):g}" for h in held)
		frappe.msgprint(
			_("Already in the central store: {0}. Consider issuing from stock before buying.").format(doc.muhick_stock_note),
			indicator="orange",
			alert=True,
		)


# ------------------------------------------------------------------ stock check
def _source_warehouse(doc, row):
	"""Store a request is drawn from: the row's source, the request's, or the central store."""
	if doc.material_request_type == "Material Issue":
		return row.warehouse or doc.get("set_warehouse")
	return row.get("from_warehouse") or doc.get("set_from_warehouse") or get_settings().central_store_warehouse


def _shortfalls(doc) -> list[frappe._dict]:
	shortfalls = []
	for row in doc.items:
		warehouse = _source_warehouse(doc, row)
		if not row.item_code or not warehouse:
			continue
		on_hand = flt(frappe.db.get_value("Bin", {"item_code": row.item_code, "warehouse": warehouse}, "actual_qty"))
		needed = flt(row.stock_qty) or flt(row.qty)
		if on_hand < needed:
			shortfalls.append(frappe._dict(row=row, warehouse=warehouse, on_hand=on_hand, short=needed - on_hand))
	return shortfalls


def _check_stock(doc):
	"""For a request drawn from the stores: is there enough stock to issue or transfer?"""
	if doc.material_request_type not in ("Material Transfer", "Material Issue"):
		doc.muhick_stock_status = "Not Applicable"
		return
	shortfalls = _shortfalls(doc)
	doc.muhick_stock_status = "Insufficient Stock" if shortfalls else "In Stock"
	doc.muhick_stock_note = ", ".join(
		_("{0}: {1} short in {2}").format(s.row.item_code, f"{s.short:g}", s.warehouse) for s in shortfalls
	)


@frappe.whitelist()
def make_purchase_request(source_name: str):
	"""Not enough stock for a store request: start the procurement process for the shortfall."""
	source = frappe.get_doc("Material Request", source_name)
	source.check_permission("read")
	shortfalls = _shortfalls(source)
	if not shortfalls:
		frappe.throw(_("The stores hold enough stock for this request."))
	request = frappe.new_doc("Material Request")
	request.update(
		{
			"material_request_type": "Purchase",
			"company": source.company,
			"schedule_date": source.schedule_date,
			"muhick_project": source.get("muhick_project"),
			"muhick_phase": source.get("muhick_phase"),
			"muhick_request_origin": source.get("muhick_request_origin"),
			"muhick_justification": _("Shortfall on store request {0}").format(source.name),
		}
	)
	for s in shortfalls:
		request.append(
			"items",
			{
				"item_code": s.row.item_code,
				"qty": s.short,
				"schedule_date": s.row.schedule_date,
				"project": s.row.project,
				"muhick_cost_code": s.row.get("muhick_cost_code"),
			},
		)
	return request


@frappe.whitelist()
def get_phase_items(project: str, phase: str, material_request: str | None = None) -> list:
	"""What the approved activity plan needs for one phase, less what other requests for that
	phase already ask for. Quantities are in each item's stock unit."""
	frappe.has_permission("Material Request", "create", throw=True)
	frappe.get_doc("Project", project).check_permission("read")
	check_phase(project, phase)
	plan_name = frappe.db.get_value("Project Activity Plan", {"project": project, "docstatus": 1, "is_current": 1}, "name")
	if not plan_name:
		frappe.throw(_("Project {0} has no approved activity plan.").format(project))
	plan = frappe.get_doc("Project Activity Plan", plan_name)
	phase_row = next((r for r in plan.phases if r.phase == phase), None)
	if not phase_row:
		frappe.throw(_("{0} is not a milestone of the approved activity plan {1}.").format(phase, plan_name))
	requested = defaultdict(float)
	for r in frappe.db.sql(
		"""
		select mri.item_code, sum(mri.stock_qty) as qty
		from `tabMaterial Request Item` mri inner join `tabMaterial Request` mr on mr.name = mri.parent
		where mr.docstatus < 2 and mr.muhick_project = %(project)s and mr.muhick_phase = %(phase)s
			and mr.name != %(exclude)s
		group by mri.item_code
		""",
		{"project": project, "phase": phase, "exclude": material_request or ""},
		as_dict=True,
	):
		requested[r.item_code] = flt(r.qty)
	today = getdate(nowdate())
	warehouse = frappe.db.get_value("Project", project, "muhick_site_warehouse")
	rows = []
	for item in plan.items:
		if item.phase_name != phase_row.phase_name:
			continue
		remaining = flt(item.qty) - requested[item.item_code]
		if remaining <= 1e-9:
			continue
		requested[item.item_code] = max(requested[item.item_code] - flt(item.qty), 0)
		info = frappe.get_cached_value("Item", item.item_code, ["item_name", "stock_uom", "muhick_cost_code"], as_dict=True)
		needed_on = getdate(item.required_by or phase_row.planned_start)
		rows.append(
			{
				"item_code": item.item_code,
				"item_name": info.item_name,
				"description": info.item_name,
				"qty": remaining,
				"uom": info.stock_uom,
				"stock_uom": info.stock_uom,
				"conversion_factor": 1,
				"stock_qty": remaining,
				"schedule_date": max(needed_on, today),
				"warehouse": warehouse,
				"project": project,
				"muhick_cost_code": budget_engine.get_budget_cost_code(project, item.item_code) or info.muhick_cost_code,
			}
		)
	return rows


@frappe.whitelist()
def get_frequent_items(limit: int = 40, item_group: str | None = None):
	"""Items bought most often in the last twelve months, for quick selection on a request."""
	frappe.has_permission("Material Request", "create", throw=True)
	params = {"since": frappe.utils.add_months(frappe.utils.nowdate(), -12), "limit": min(int(limit or 40), 200)}
	group = ""
	if item_group:
		group = "and poi.item_group = %(item_group)s"
		params["item_group"] = item_group
	return frappe.db.sql(
		f"""
		select poi.item_code, max(poi.item_name) as item_name, max(poi.stock_uom) as uom,
			count(distinct po.name) as orders, 0 as qty
		from `tabPurchase Order Item` poi
		inner join `tabPurchase Order` po on po.name = poi.parent
		where po.docstatus = 1 and po.transaction_date >= %(since)s {group}
		group by poi.item_code
		order by count(distinct po.name) desc
		limit %(limit)s
		""",
		params,
		as_dict=True,
	)
