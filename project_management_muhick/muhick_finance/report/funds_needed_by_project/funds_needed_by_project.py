# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""When each project needs what money, against what it has: its budget's cash plan month by month, once what has been paid
has covered the earliest months, next to the funds it has available and what it is short of. This is what allocations are
decided from: the projects short of money at the top, those with money to spare at the bottom."""

import re
from datetime import date

import frappe
from frappe import _
from frappe.utils import flt, formatdate, getdate, nowdate

from project_management_muhick.muhick_finance import funds
from project_management_muhick.muhick_projects.report.budget_cash_plan import budget_cash_plan as cash_plan
from project_management_muhick.utils import calc

MONTH = re.compile(r"^m(\d{4})_(\d{2})$")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "project", "label": _("Project"), "fieldtype": "Link", "options": "Project", "width": 130},
		{"fieldname": "project_name", "label": _("Project Name"), "fieldtype": "Data", "width": 220},
		{"fieldname": "available", "label": _("Funds Available"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "needed_now", "label": _("Needed Now"), "fieldtype": "Currency", "width": 140},
	]
	today = getdate(nowdate())
	current = (today.year, today.month)
	conditions = {"status": "Open"}
	if filters.company:
		conditions["company"] = filters.company
	projects = frappe.get_all("Project", filters=conditions, fields=["name", "project_name"])
	if not projects:
		return columns, []
	paid = dict(frappe.get_all("Project Budget", filters={"docstatus": 1}, fields=["project", "total_paid"], as_list=True))
	positions = funds.positions(filters.company)
	rows, months = [], set()
	for project in projects:
		plan, unscheduled = _plan_of(project.name)
		if not plan and not unscheduled:
			continue
		needs = calc.still_needed(plan, unscheduled, flt(paid.get(project.name)), current)
		months.update(needs["months"])
		rows.append(
			frappe._dict(
				project=project.name,
				project_name=project.project_name,
				available=flt(positions[project.name].available),
				needed_now=needs["now"],
				not_scheduled=needs["unscheduled"],
				total_needed=needs["total"],
				shortfall=max(needs["total"] - flt(positions[project.name].available), 0),
				**{f"m{year}_{month:02d}": amount for (year, month), amount in needs["months"].items()},
			)
		)
	months = sorted(months)
	columns += [
		{"fieldname": f"m{year}_{month:02d}", "label": formatdate(date(year, month, 1), "MMM yyyy"), "fieldtype": "Currency", "width": 130}
		for year, month in months
	]
	columns += [
		{"fieldname": "not_scheduled", "label": _("Not Scheduled"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "total_needed", "label": _("Total Still Needed"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "shortfall", "label": _("Funds Short"), "fieldtype": "Currency", "width": 150},
	]
	rows.sort(key=lambda row: -row.shortfall)
	chart = {
		"data": {
			"labels": [row.project_name or row.project for row in rows],
			"datasets": [
				{"name": _("Total Still Needed"), "values": [row.total_needed for row in rows]},
				{"name": _("Funds Available"), "values": [row.available for row in rows]},
			],
		},
		"type": "bar",
		"fieldtype": "Currency",
	}
	return columns, rows, None, chart


def _plan_of(project) -> tuple:
	"""{(year, month): what the project's budget has falling in it}, and what is not scheduled, from its cash plan."""
	_columns, data, *_rest = cash_plan.execute({"project": project})
	if not data:
		return {}, 0.0
	total = data[-1]
	plan = {}
	for field, value in total.items():
		match = MONTH.match(field)
		if match:
			plan[(int(match.group(1)), int(match.group(2)))] = flt(value)
	return plan, flt(total.get(cash_plan.UNSCHEDULED))
