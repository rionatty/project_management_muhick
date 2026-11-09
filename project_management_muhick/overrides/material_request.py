# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Material Request: tie the request to the project budget, phase and approved brands.

The result (Within Budget / Exceeds Budget / Not Budgeted) decides the approval route:
within budget goes to the COO only, anything else also needs the Finance Manager and the
General Manager. The company's own needs, with no project, go the administration way instead,
whoever raises them: local and international procurement are for projects.
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
	if not doc.get("muhick_request_origin"):
		doc.muhick_request_origin = "Project" if project else "User Department"
	doc.muhick_administration = _company_own(doc, project)
	if not project:
		doc.muhick_budget_status = "Not Applicable"
		doc.muhick_budget_remarks = ""
		return

	_set_cost_codes(doc, project)
	_check_budget(doc, project)
	_check_brands(doc, project)
	_check_phase(doc, project)
	_note_stock_on_hand(doc)

	needs_reason = doc.muhick_budget_status in ("Exceeds Budget", "Not Budgeted") or doc.get("muhick_out_of_phase")
	leaving_draft = doc.get("workflow_state") not in (None, "", "Draft")
	if needs_reason and leaving_draft and not doc.get("muhick_justification"):
		frappe.throw(
			_("This request is {0}. Enter a justification before sending it for approval.").format(
				_("outside the current phase") if doc.get("muhick_out_of_phase") else _("over budget")
			)
		)


def _company_own(doc, project) -> int:
	"""1 when the request takes the administration route: the Administration's own, or a department's with no project on
	it or on any line. Its approval, and the documents raised from it, follow (utils.common.administration_purchase)."""
	if doc.material_request_type == "Material Transfer":
		return 0
	origin = doc.get("muhick_request_origin")
	if origin == "Administration":
		return 1
	return int(origin == "User Department" and not project and not any(row.get("project") for row in doc.items))


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
			row.muhick_cost_code = budget_engine.get_budget_cost_code(row.project or project, row.item_code, doc.get("muhick_phase"))


def _row_amount(row, project) -> float:
	if flt(row.amount):
		return flt(row.amount)
	if flt(row.rate):
		return flt(row.qty) * flt(row.rate)
	return budget_engine.row_stock_qty(row) * budget_engine.get_budget_rate(project, row.item_code)


def _check_budget(doc, project):
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
	quantities = defaultdict(float)
	for row in doc.items:
		if row.item_code and (row.project or project) == project:
			quantities[row.item_code] += budget_engine.row_stock_qty(row)
	status, remarks = budget_engine.with_quantities(project, status, remarks, quantities, doc.get("muhick_phase"), doc.name)
	# a request has no supplier's price yet, so its items are checked and not their prices
	doc.muhick_budget_status, doc.muhick_budget_remarks = budget_engine.with_items(
		project, status, remarks, [(item, qty, 0, None) for item, qty in quantities.items()]
	)


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


def _check_phase(doc, project):
	"""Requests are raised per phase. A request for a later phase, or for items the budget places only
	in other milestones, needs an explanation."""
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
	elsewhere = _budgeted_elsewhere(doc, project)
	if elsewhere:
		doc.muhick_out_of_phase = 1
		note = _("Budgeted under another milestone: {0}").format("; ".join(elsewhere))
		doc.muhick_budget_remarks = "\n".join(filter(None, [doc.get("muhick_budget_remarks"), note]))


def _budgeted_elsewhere(doc, project) -> list[str]:
	"""The request's items that the approved budget places only in other milestones. A line in no milestone leaves
	its item free to be requested in any."""
	budget = budget_engine.get_approved_budget(project)
	items = {row.item_code for row in doc.items if row.item_code}
	if not doc.get("muhick_phase") or not budget or not items:
		return []
	place_of = budget_engine.line_places(project)
	places = defaultdict(set)
	for line in frappe.get_all(
		"Project Budget Line",
		filters={"parent": budget, "parenttype": "Project Budget", "item_code": ("in", list(items))},
		fields=["item_code", "stage", "phase"],
	):
		places[line.item_code].add(place_of(line))
	found = []
	for item, where in places.items():
		if doc.muhick_phase not in where and None not in where:
			subjects = sorted(frappe.db.get_value("Task", name, "subject") or name for name in where)
			found.append(f"{item} ({', '.join(subjects)})")
	return found


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
def get_phase_items(project: str, phase: str, material_request: str | None = None) -> dict:
	"""What a milestone still needs: what the approved activity plan lists for it and what the approved budget places in
	it, less what other requests for it already ask for. Quantities are in each item's stock unit. With nothing to
	load, a note says why."""
	frappe.has_permission("Material Request", "create", throw=True)
	frappe.get_doc("Project", project).check_permission("read")
	check_phase(project, phase)
	needs = _plan_needs(project, phase)
	planned = {need["item_code"] for need in needs}
	needs += [need for need in budget_engine.milestone_needs(project, phase) if need["item_code"] not in planned]
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
	starts = frappe.db.get_value("Task", phase, "exp_start_date")
	warehouse = frappe.db.get_value("Project", project, "muhick_site_warehouse")
	rows = []
	for need in needs:
		item_code = need["item_code"]
		remaining = flt(need["qty"]) - requested[item_code]
		if remaining <= 1e-9:
			continue
		requested[item_code] = max(requested[item_code] - flt(need["qty"]), 0)
		info = frappe.get_cached_value("Item", item_code, ["item_name", "stock_uom", "muhick_cost_code"], as_dict=True)
		needed_on = need.get("required_by") or starts
		rate = flt(need.get("rate"))
		rows.append(
			{
				"item_code": item_code,
				"item_name": info.item_name,
				"description": info.item_name,
				"qty": remaining,
				"uom": info.stock_uom,
				"stock_uom": info.stock_uom,
				"conversion_factor": 1,
				"stock_qty": remaining,
				"rate": rate,
				"amount": rate * remaining,
				"schedule_date": max(getdate(needed_on), today) if needed_on else today,
				"warehouse": warehouse,
				"project": project,
				"muhick_cost_code": need.get("cost_code") or budget_engine.get_budget_cost_code(project, item_code, phase) or info.muhick_cost_code,
			}
		)
	return {"rows": rows, "note": None if rows else _nothing_to_load(project, needs)}


def _plan_needs(project, phase) -> list:
	"""What the approved activity plan's Items Required list for a milestone."""
	plan_name = frappe.db.get_value("Project Activity Plan", {"project": project, "docstatus": 1, "is_current": 1}, "name")
	if not plan_name:
		return []
	plan = frappe.get_doc("Project Activity Plan", plan_name)
	row = next((r for r in plan.phases if r.phase == phase), None)
	if not row:
		return []
	return [
		{"item_code": item.item_code, "qty": item.qty, "required_by": item.required_by or row.planned_start}
		for item in plan.items
		if item.phase_name == row.phase_name
	]


def _nothing_to_load(project, needs) -> str:
	if needs:
		return _("Nothing left to request for this milestone.")
	if not budget_engine.get_approved_budget(project):
		return _("The activity plan lists no items for this milestone, and the project has no approved budget yet.")
	stages = budget_engine.unplaced_stages(project)
	if stages:
		return _("The budget places nothing in this milestone. These budget stages have no milestone yet: {0}. Link them on the budget: Budget Lines > Link Stages to Milestones.").format(
			", ".join(stage or _("No Stage") for stage in stages)
		)
	return _("Neither the activity plan nor the budget has items for this milestone.")


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
