# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Accountability for the payment plans: every approved line against what was actually paid,
and the reason for anything held, not executed or paid at a different amount."""

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "plan", "label": _("Payment Plan"), "fieldtype": "Link", "options": "Payment Plan", "width": 150},
		{"fieldname": "period_to", "label": _("Period Ending"), "fieldtype": "Date", "width": 110},
		{"fieldname": "reference_doctype", "label": _("Document Type"), "fieldtype": "Data", "width": 150},
		{"fieldname": "reference_name", "label": _("Document"), "fieldtype": "Dynamic Link", "options": "reference_doctype", "width": 170},
		{"fieldname": "party", "label": _("Pay To"), "fieldtype": "Data", "width": 190},
		{"fieldname": "project", "label": _("Project"), "fieldtype": "Link", "options": "Project", "width": 120},
		{"fieldname": "proposed_amount", "label": _("Proposed"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "approved_amount", "label": _("Approved"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "paid_amount", "label": _("Paid"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "not_paid", "label": _("Approved, Not Paid"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "line_status", "label": _("Line Status"), "fieldtype": "Data", "width": 120},
		{"fieldname": "mode_of_payment", "label": _("Mode of Payment"), "fieldtype": "Data", "width": 140},
		{"fieldname": "payment_entry", "label": _("Payment Entry"), "fieldtype": "Link", "options": "Payment Entry", "width": 160},
		{"fieldname": "hold_reason", "label": _("Reason Held / Not Executed"), "fieldtype": "Data", "width": 280},
	]
	conditions, params = ["p.docstatus = 1"], {}
	if filters.plan:
		conditions.append("p.name = %(plan)s")
		params["plan"] = filters.plan
	if filters.company:
		conditions.append("p.company = %(company)s")
		params["company"] = filters.company
	if filters.from_date and filters.to_date:
		conditions.append("p.period_to between %(from_date)s and %(to_date)s")
		params.update(from_date=filters.from_date, to_date=filters.to_date)
	rows = frappe.db.sql(
		f"""
		select p.name as plan, p.period_to, l.reference_doctype, l.reference_name, l.party, l.project,
			l.proposed_amount, l.approved_amount, l.paid_amount, l.line_status, l.mode_of_payment,
			l.payment_entry, l.hold_reason
		from `tabPayment Plan Line` l
		inner join `tabPayment Plan` p on p.name = l.parent
		where {" and ".join(conditions)}
		order by p.period_to desc, p.name, l.idx
		""",
		params,
		as_dict=True,
	)
	data = []
	for r in rows:
		r.not_paid = max(flt(r.approved_amount) - flt(r.paid_amount), 0)
		if filters.only_unpaid and r.not_paid <= 0.005 and r.line_status == "Paid":
			continue
		data.append(r)
	return columns, data
