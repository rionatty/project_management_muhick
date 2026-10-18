# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Phase plan of a project: each phase (a group task) with its dates, progress and target
valuation, the items the activity plan needs for it, and the materials, works and labour
budgeted for it against what has been requested so far. Shows which phase the project is in
and what the next one needs."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, getdate

from project_management_muhick.muhick_projects import budget_engine
from project_management_muhick.muhick_projects.utils import get_phases, phase_done


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "name", "label": _("Phase Task"), "fieldtype": "Link", "options": "Task", "width": 130},
		{"fieldname": "subject", "label": _("Phase"), "fieldtype": "Data", "width": 220},
		{"fieldname": "position", "label": _("Position"), "fieldtype": "Data", "width": 100},
		{"fieldname": "planned_start", "label": _("Planned Start"), "fieldtype": "Date", "width": 110},
		{"fieldname": "planned_end", "label": _("Planned End"), "fieldtype": "Date", "width": 110},
		{"fieldname": "progress", "label": _("% Complete"), "fieldtype": "Percent", "width": 100},
		{"fieldname": "muhick_planned_valuation", "label": _("Target Valuation"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "items_planned", "label": _("Items Planned"), "fieldtype": "Int", "width": 110},
		{"fieldname": "materials_budget", "label": _("Materials Budget"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "works_budget", "label": _("Works Budget"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "other_budget", "label": _("Administrative Budget"), "fieldtype": "Currency", "width": 160},
		{"fieldname": "labour_scheduled", "label": _("Labour Scheduled"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "materials_requested", "label": _("Materials Requested"), "fieldtype": "Currency", "width": 150},
	]
	if not filters.project:
		return columns, []
	phases = get_phases(
		filters.project,
		("name", "subject", "status", "progress", "exp_start_date", "exp_end_date", "muhick_planned_valuation"),
	)
	items = defaultdict(int)
	plan = frappe.db.get_value("Project Activity Plan", {"project": filters.project, "docstatus": 1, "is_current": 1}, "name")
	if plan:
		task_of = dict(
			frappe.get_all("Project Activity Plan Phase", filters={"parent": plan}, fields=["phase_name", "phase"], as_list=True)
		)
		for row in frappe.get_all("Project Activity Plan Item", filters={"parent": plan}, fields=["phase_name"]):
			items[task_of.get(row.phase_name)] += 1
	budget = defaultdict(lambda: defaultdict(float))
	approved = budget_engine.get_approved_budget(filters.project)
	if approved:
		for line in frappe.get_all(
			"Project Budget Line",
			filters={"parent": approved, "phase": ("is", "set")},
			fields=["phase", "budget_section", "amount"],
		):
			budget[line.phase][line.budget_section] += flt(line.amount)
	labour = defaultdict(float)
	for s in frappe.get_all(
		"Labour Schedule",
		filters={"project": filters.project, "docstatus": 1, "phase": ("is", "set")},
		fields=["phase", "total_amount"],
	):
		labour[s.phase] += flt(s.total_amount)
	requested = defaultdict(float)
	for r in frappe.db.sql(
		"""
		select mr.muhick_phase as phase, sum(mri.amount) as amount
		from `tabMaterial Request Item` mri inner join `tabMaterial Request` mr on mr.name = mri.parent
		where mr.docstatus = 1 and mr.muhick_project = %s and ifnull(mr.muhick_phase, '') != ''
		group by mr.muhick_phase
		""",
		(filters.project,),
		as_dict=True,
	):
		requested[r.phase] = flt(r.amount)
	current = next((p.name for p in phases if not phase_done(p)), None)
	for p in phases:
		p.position = _("Current") if p.name == current else _("Done") if phase_done(p) else _("Upcoming")
		p.planned_start = getdate(p.exp_start_date) if p.exp_start_date else None
		p.planned_end = getdate(p.exp_end_date) if p.exp_end_date else None
		p.items_planned = items[p.name]
		p.materials_budget = budget[p.name]["Materials"]
		p.works_budget = budget[p.name]["Works"]
		p.other_budget = budget[p.name]["Administrative"]
		p.labour_scheduled = labour[p.name]
		p.materials_requested = requested[p.name]
	return columns, phases
