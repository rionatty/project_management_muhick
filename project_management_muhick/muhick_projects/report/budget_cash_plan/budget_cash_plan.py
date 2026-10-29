# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Cash plan of a project's budget, month by month. Each line falls in the month it is needed on
site, or else is spread over its milestone's dates, day by day; a line with neither is shown apart.
By stage or by cost code, from the approved budget, or from the draft while there is none."""

from collections import defaultdict
from datetime import date

import frappe
from frappe import _
from frappe.utils import flt, formatdate

from project_management_muhick.muhick_projects import budget_engine
from project_management_muhick.muhick_projects.utils import get_phases
from project_management_muhick.utils import calc

UNSCHEDULED = "unscheduled"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	by_cost_code = filters.group_by == "Cost Code"
	label = {"fieldname": "label", "label": _("Cost Code") if by_cost_code else _("Stage"), "fieldtype": "Data", "width": 260}
	budget = budget_engine.get_approved_budget(filters.project) or frappe.db.get_value(
		"Project Budget", {"project": filters.project, "docstatus": 0}, "name", order_by="creation desc"
	)
	if not filters.project or not budget:
		return [label], [], _("Project {0} has no budget yet.").format(filters.project) if filters.project else None

	phases = {p.name: p for p in get_phases(filters.project, ("name", "type", "exp_start_date", "exp_end_date"))}
	by_stage = {}
	for phase in phases.values():
		if phase.type:
			by_stage.setdefault(phase.type, phase)
	cells, months = defaultdict(lambda: defaultdict(float)), set()
	for line in frappe.get_all(
		"Project Budget Line",
		filters={"parent": budget, "parenttype": "Project Budget"},
		fields=["stage", "phase", "cost_code", "amount", "required_by_date"],
	):
		key = line.cost_code if by_cost_code else line.stage or ""
		phase = phases.get(line.phase) or by_stage.get(line.stage)
		if line.required_by_date:
			shares = calc.month_shares(line.required_by_date, line.required_by_date)
		else:
			shares = calc.month_shares(phase.exp_start_date, phase.exp_end_date) if phase else {}
		for month, share in shares.items():
			cells[key][month] += flt(line.amount) * share
			months.add(month)
		if not shares:
			cells[key][UNSCHEDULED] += flt(line.amount)

	months = sorted(months)
	columns = [label] + [
		{"fieldname": f"m{year}_{month:02d}", "label": formatdate(date(year, month, 1), "MMM yyyy"), "fieldtype": "Currency", "width": 120}
		for year, month in months
	]
	unscheduled = any(row[UNSCHEDULED] for row in cells.values())
	if unscheduled:
		columns.append({"fieldname": UNSCHEDULED, "label": _("Not Scheduled"), "fieldtype": "Currency", "width": 120})
	columns.append({"fieldname": "total", "label": _("Total"), "fieldtype": "Currency", "width": 140})

	names = dict(frappe.get_all("Cost Code", fields=["name", "cost_code_name"], as_list=True)) if by_cost_code else {}
	data, totals = [], defaultdict(float)
	for key in sorted(cells, key=lambda k: (not k, k)):
		row = {"label": f"{key} {names.get(key, '')}".strip() if by_cost_code else key or _("No stage")}
		for year, month in months:
			row[f"m{year}_{month:02d}"] = cells[key][(year, month)]
		if unscheduled:
			row[UNSCHEDULED] = cells[key][UNSCHEDULED]
		row["total"] = sum(cells[key].values())
		for field, value in row.items():
			if field != "label":
				totals[field] += value
		data.append(row)
	data.append({"label": _("Total"), "bold": 1, **totals})

	chart = {
		"data": {
			"labels": [c["label"] for c in columns[1 : 1 + len(months)]],
			"datasets": [{"name": _("Budget"), "values": [totals[f"m{y}_{m:02d}"] for y, m in months]}],
		},
		"type": "bar",
		"fieldtype": "Currency",
	}
	draft = budget != budget_engine.get_approved_budget(filters.project)
	message = _("Draft budget {0}, not yet approved.").format(budget) if draft else None
	return columns, data, message, chart
