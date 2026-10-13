# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Where every document is in its approval, who it is waiting on and for how long. Also shows
completed approval steps, to measure turnaround against the allowed time."""

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, now_datetime

from project_management_muhick.utils import calc
from project_management_muhick.utils.approval import get_approver_roles


def execute(filters=None):
	filters = frappe._dict(filters or {})
	pending = (filters.status or "Pending") == "Pending"
	columns = [
		{"fieldname": "reference_doctype", "label": _("Document Type"), "fieldtype": "Data", "width": 190},
		{"fieldname": "reference_name", "label": _("Document"), "fieldtype": "Dynamic Link", "options": "reference_doctype", "width": 170},
		{"fieldname": "project", "label": _("Project"), "fieldtype": "Link", "options": "Project", "width": 120},
		{"fieldname": "workflow_state", "label": _("Approval Step"), "fieldtype": "Data", "width": 190},
		{"fieldname": "waiting_on", "label": _("Waiting On") if pending else _("Actioned By"), "fieldtype": "Data", "width": 200},
		{"fieldname": "entered_on", "label": _("Since"), "fieldtype": "Datetime", "width": 160},
		{"fieldname": "hours", "label": _("Hours in Step"), "fieldtype": "Float", "precision": 1, "width": 110},
		{"fieldname": "allowed_hours", "label": _("Allowed Hours"), "fieldtype": "Float", "precision": 1, "width": 110},
		{"fieldname": "overdue", "label": _("Overdue"), "fieldtype": "Data", "width": 90},
	]
	conditions = {"is_open": 1 if pending else 0}
	if filters.document_type:
		conditions["reference_doctype"] = filters.document_type
	if filters.project:
		conditions["project"] = filters.project
	if not pending and filters.from_date and filters.to_date:
		conditions["entered_on"] = ("between", [filters.from_date, filters.to_date])
	logs = frappe.get_all(
		"Approval Turnaround Log",
		filters=conditions,
		fields=[
			"reference_doctype", "reference_name", "project", "workflow_state", "entered_on", "hours_in_state",
			"allowed_hours", "actioned_by", "next_state",
		],
		order_by="entered_on asc",
		limit=5000,
	)
	now = now_datetime()
	roles = {}
	rows = []
	for log in logs:
		if pending:
			key = (log.reference_doctype, log.workflow_state)
			if key not in roles:
				roles[key] = ", ".join(get_approver_roles(*key))
			log.waiting_on = roles[key]
			log.hours = calc.hours_between(get_datetime(log.entered_on), now)
		else:
			log.waiting_on = log.actioned_by
			log.hours = flt(log.hours_in_state)
		log.overdue = _("Yes") if log.hours > flt(log.allowed_hours) else ""
		if filters.only_overdue and not log.overdue:
			continue
		rows.append(log)
	return columns, rows
