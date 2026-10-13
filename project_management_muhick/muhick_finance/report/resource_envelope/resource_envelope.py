# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""The funds of each project: what the client has paid in, what has been paid out, and what the
project has lent to or borrowed from other projects. Funds are held project by project, so this
shows which project has money to lend and which is running on another project's money."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt

OPEN = ("Outstanding", "Partly Refunded")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "project", "label": _("Project"), "fieldtype": "Link", "options": "Project", "width": 130},
		{"fieldname": "project_name", "label": _("Project Name"), "fieldtype": "Data", "width": 230},
		{"fieldname": "stage", "label": _("Stage"), "fieldtype": "Data", "width": 150},
		{"fieldname": "received", "label": _("Received from Client"), "fieldtype": "Currency", "width": 170},
		{"fieldname": "paid_out", "label": _("Paid Out"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "own_balance", "label": _("Own Funds Left"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "lent", "label": _("Lent to Other Projects"), "fieldtype": "Currency", "width": 180},
		{"fieldname": "borrowed", "label": _("Borrowed from Other Projects"), "fieldtype": "Currency", "width": 210},
		{"fieldname": "available", "label": _("Funds Available"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "committed_unpaid", "label": _("Committed, Not Yet Paid"), "fieldtype": "Currency", "width": 190},
	]
	conditions = {"status": ("!=", "Cancelled")}
	if filters.company:
		conditions["company"] = filters.company
	projects = frappe.get_all("Project", filters=conditions, fields=["name", "project_name", "muhick_stage"])
	if not projects:
		return columns, []

	received = defaultdict(float)
	for r in frappe.db.sql(
		"""
		select project, sum(base_grand_total - outstanding_amount * conversion_rate) as amount
		from `tabSales Invoice` where docstatus = 1 and ifnull(project, '') != '' group by project
		""",
		as_dict=True,
	):
		received[r.project] = flt(r.amount)
	budgets = {
		b.project: b
		for b in frappe.get_all("Project Budget", filters={"docstatus": 1}, fields=["project", "total_paid", "total_committed"])
	}
	lent, borrowed = defaultdict(float), defaultdict(float)
	for t in frappe.get_all(
		"Project Fund Transfer",
		filters={"docstatus": 1, "status": ("in", OPEN)},
		fields=["from_project", "to_project", "outstanding_amount"],
	):
		lent[t.from_project] += flt(t.outstanding_amount)
		borrowed[t.to_project] += flt(t.outstanding_amount)

	rows = []
	for p in projects:
		budget = budgets.get(p.name) or frappe._dict()
		row = frappe._dict(
			project=p.name,
			project_name=p.project_name,
			stage=p.muhick_stage,
			received=received.get(p.name, 0),
			paid_out=flt(budget.total_paid),
			lent=lent.get(p.name, 0),
			borrowed=borrowed.get(p.name, 0),
			committed_unpaid=max(flt(budget.total_committed) - flt(budget.total_paid), 0),
		)
		row.own_balance = row.received - row.paid_out
		row.available = row.own_balance - row.lent + row.borrowed
		if any(row.get(f) for f in ("received", "paid_out", "lent", "borrowed", "committed_unpaid")):
			rows.append(row)
	rows.sort(key=lambda r: r.available)
	return columns, rows
