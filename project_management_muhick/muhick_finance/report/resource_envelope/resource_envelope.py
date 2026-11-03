# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""The funds of each project, read from the postings on the bank and cash accounts: what came in and went out, what it has
allocated to or been allocated by other projects, and what it has available. It adds up to what the banks hold, money
posted with no project being shown apart, and can show how much of each project's money sits in each account."""

import frappe
from frappe import _
from frappe.utils import flt, nowdate

from project_management_muhick.muhick_finance import funds

MONEY = ("received", "paid_out", "own_funds", "allocated_out", "allocated_in", "available")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "project", "label": _("Project"), "fieldtype": "Link", "options": "Project", "width": 130},
		{"fieldname": "project_name", "label": _("Project Name"), "fieldtype": "Data", "width": 230},
		{"fieldname": "stage", "label": _("Stage"), "fieldtype": "Data", "width": 130},
		{"fieldname": "received", "label": _("Received"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "paid_out", "label": _("Paid Out"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "own_funds", "label": _("Own Funds"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "allocated_out", "label": _("Allocated to Other Projects"), "fieldtype": "Currency", "width": 190},
		{"fieldname": "allocated_in", "label": _("Allocated from Other Projects"), "fieldtype": "Currency", "width": 200},
		{"fieldname": "available", "label": _("Funds Available"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "committed_unpaid", "label": _("Committed, Not Yet Paid"), "fieldtype": "Currency", "width": 180},
		{"fieldname": "after_commitments", "label": _("After Commitments"), "fieldtype": "Currency", "width": 150},
	]
	positions = funds.positions(filters.company, filters.as_at or nowdate())
	accounts = sorted({account for position in positions.values() for account in position.by_account}) if filters.by_account else []
	columns += [{"fieldname": f"account_{i}", "label": account, "fieldtype": "Currency", "width": 170} for i, account in enumerate(accounts)]

	conditions = {"status": ("!=", "Cancelled")}
	if filters.company:
		conditions["company"] = filters.company
	committed = {
		b.project: max(flt(b.total_committed) - flt(b.total_paid), 0)
		for b in frappe.get_all("Project Budget", filters={"docstatus": 1}, fields=["project", "total_paid", "total_committed"])
	}

	def row_of(project, project_name, stage):
		position = positions.get(project) or frappe._dict(by_account={})
		row = frappe._dict(project=project or None, project_name=project_name, stage=stage)
		for field in MONEY:
			row[field] = flt(position.get(field))
		row.committed_unpaid = committed.get(project, 0)
		row.after_commitments = row.available - row.committed_unpaid
		for i, account in enumerate(accounts):
			row[f"account_{i}"] = flt(position.by_account.get(account))
		return row

	rows = []
	for p in frappe.get_all("Project", filters=conditions, fields=["name", "project_name", "muhick_stage"]):
		row = row_of(p.name, p.project_name, p.muhick_stage)
		if any(row[field] for field in (*MONEY, "committed_unpaid")):
			rows.append(row)
	rows.sort(key=lambda row: row.available)
	apart = row_of(funds.NOT_ON_A_PROJECT, _("Not on a Project"), None) if funds.NOT_ON_A_PROJECT in positions else None
	on_projects = sum(row.own_funds for row in rows)
	summary = [
		{"value": on_projects + (apart.own_funds if apart else 0), "label": _("In Bank and Cash"), "datatype": "Currency", "indicator": "Blue"},
		{"value": on_projects, "label": _("On Projects"), "datatype": "Currency", "indicator": "Green"},
		{"value": apart.own_funds if apart else 0, "label": _("Not on a Project"), "datatype": "Currency", "indicator": "Orange"},
		{"value": sum(row.allocated_out for row in rows), "label": _("Allocated Between Projects"), "datatype": "Currency", "indicator": "Red"},
	]
	chart = {
		"data": {
			"labels": [row.project_name or row.project for row in rows],
			"datasets": [
				{"name": _("Own Funds"), "values": [row.own_funds for row in rows]},
				{"name": _("Funds Available"), "values": [row.available for row in rows]},
			],
		},
		"type": "bar",
		"fieldtype": "Currency",
	}
	return columns, rows + ([apart] if apart else []), None, chart, summary
