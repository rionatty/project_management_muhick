# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Procurement plan: each material line of the approved budget with the date it is needed on
site, its lead time and therefore the date it must be ordered by, against what has been ordered.
Lines to order now, or already late, are flagged so Procurement is ahead of each phase."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, nowdate

from project_management_muhick.muhick_projects import budget_engine


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "milestone_name", "label": _("Milestone / Phase"), "fieldtype": "Data", "width": 180},
		{"fieldname": "cost_code", "label": _("Cost Code"), "fieldtype": "Link", "options": "Cost Code", "width": 100},
		{"fieldname": "item_code", "label": _("Item"), "fieldtype": "Link", "options": "Item", "width": 140},
		{"fieldname": "description", "label": _("Description"), "fieldtype": "Data", "width": 220},
		{"fieldname": "procurement_type", "label": _("Source"), "fieldtype": "Data", "width": 110},
		{"fieldname": "qty", "label": _("Budget Qty"), "fieldtype": "Float", "width": 100},
		{"fieldname": "ordered_qty", "label": _("Ordered Qty"), "fieldtype": "Float", "width": 100},
		{"fieldname": "amount", "label": _("Budget Amount"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "required_by", "label": _("Required on Site"), "fieldtype": "Date", "width": 120},
		{"fieldname": "lead_time_days", "label": _("Lead Time (Days)"), "fieldtype": "Int", "width": 120},
		{"fieldname": "order_by", "label": _("Order By"), "fieldtype": "Date", "width": 110},
		{"fieldname": "plan_status", "label": _("Status"), "fieldtype": "Data", "width": 130},
	]
	if not filters.project:
		return columns, []
	budget = budget_engine.get_approved_budget(filters.project)
	if not budget:
		frappe.msgprint(_("Project {0} has no approved budget.").format(filters.project))
		return columns, []
	lines = frappe.get_all(
		"Project Budget Line",
		filters={"parent": budget, "budget_section": "Materials"},
		fields=[
			"cost_code", "item_code", "description", "procurement_type", "qty", "amount", "milestone",
			"required_by_date", "lead_time_days",
		],
		order_by="idx asc",
	)
	milestones = {
		m.name: m
		for m in frappe.get_all(
			"Project Milestone", filters={"project": filters.project}, fields=["name", "milestone_name", "planned_start"]
		)
	}
	ordered = defaultdict(float)
	for r in frappe.db.sql(
		"""
		select i.item_code, sum(i.qty) as qty from `tabPurchase Order Item` i
		inner join `tabPurchase Order` p on p.name = i.parent
		where p.docstatus = 1 and i.project = %s group by i.item_code
		""",
		(filters.project,),
		as_dict=True,
	):
		ordered[r.item_code] = flt(r.qty)
	today = getdate(nowdate())
	rows = []
	for line in lines:
		milestone = milestones.get(line.milestone)
		line.milestone_name = milestone.milestone_name if milestone else None
		# needed on site by its own date, otherwise when its phase starts
		line.required_by = line.required_by_date or (milestone.planned_start if milestone else None)
		line.order_by = add_days(line.required_by, -int(line.lead_time_days or 0)) if line.required_by else None
		line.ordered_qty = min(ordered.get(line.item_code, 0), flt(line.qty)) if line.item_code else 0
		if line.item_code:
			ordered[line.item_code] = max(ordered.get(line.item_code, 0) - flt(line.qty), 0)
		line.plan_status = _status(line, today)
		if filters.only_action and line.plan_status not in (_("Order Now"), _("Late")):
			continue
		rows.append(line)
	return columns, rows


def _status(line, today):
	if line.procurement_type in ("From Stock", "Not Applicable"):
		return _(line.procurement_type)
	if line.item_code and flt(line.ordered_qty) >= flt(line.qty) - 1e-9:
		return _("Ordered")
	if not line.order_by:
		return _("Not Scheduled")
	order_by = getdate(line.order_by)
	if order_by < today:
		return _("Late")
	if (order_by - today).days <= 7:
		return _("Order Now")
	return _("Planned")
