# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Helpers shared by the project documents."""

import frappe
from frappe import _
from frappe.utils import flt

from project_management_muhick.muhick_projects import budget_engine

DRAFT_STATES = (None, "", "Draft")
RETURNED_STATES = ("Rejected", "Evaluation Returned", "Returned")


def leaving_draft(doc) -> bool:
	"""True once the document has been sent for approval (or is being submitted)."""
	return doc.docstatus == 1 or doc.get("workflow_state") not in (*DRAFT_STATES, *RETURNED_STATES)


def draft_status(doc) -> str:
	"""Status of an unsubmitted document, derived from its approval step."""
	state = doc.get("workflow_state")
	if state in DRAFT_STATES:
		return "Draft"
	if state in RETURNED_STATES:
		return "Rejected"
	return "Pending Approval"


def set_amounts(rows, qty_field="qty", rate_field="rate", amount_field="amount") -> float:
	total = 0.0
	for row in rows:
		row.set(amount_field, flt(row.get(qty_field)) * flt(row.get(rate_field)))
		total += flt(row.get(amount_field))
	return total


def set_budget_status(doc, amounts):
	"""Fill budget_status / budget_remarks on a document from {cost_code: amount}."""
	status, remarks = budget_engine.evaluate(doc.project, amounts)
	doc.budget_status = status
	doc.budget_remarks = remarks
	return status, remarks


def validate_dates(start, end, start_label, end_label):
	if start and end and frappe.utils.getdate(end) < frappe.utils.getdate(start):
		frappe.throw(_("{0} cannot be before {1}.").format(end_label, start_label))


def require_stage(project, allowed, action):
	stage = frappe.db.get_value("Project", project, "muhick_stage")
	if stage not in allowed:
		frappe.throw(
			_("{0} is not possible while project {1} is in {2}.").format(action, project, _(stage or "Planning"))
		)


def new_mapped(doctype, values):
	"""A new unsaved document for frappe.model.open_mapped_doc."""
	doc = frappe.new_doc(doctype)
	doc.update(values)
	return doc
