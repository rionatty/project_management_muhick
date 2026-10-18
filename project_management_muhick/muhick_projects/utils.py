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


PHASE_FIELDS = ("name", "subject", "status", "progress", "task_weight", "exp_start_date", "exp_end_date")


def get_phases(project, fields=PHASE_FIELDS):
	"""The project's phases: its top-level group tasks that are not cancelled, in date order."""
	return frappe.get_all(
		"Task",
		filters={"project": project, "is_group": 1, "parent_task": ("is", "not set"), "status": ("!=", "Cancelled")},
		fields=list(fields),
		order_by="exp_start_date asc, lft asc",
	)


def phase_done(phase) -> bool:
	return phase.get("status") == "Completed" or flt(phase.get("progress")) >= 100


def check_phase(project, phase, label=None):
	"""Throw unless phase is a phase (group task) of the project."""
	task = frappe.db.get_value("Task", phase, ["project", "is_group"], as_dict=True)
	if not task or task.project != project or not task.is_group:
		frappe.throw(_("{0}: {1} is not a milestone (phase) of project {2}.").format(label or _("Milestone / Phase"), phase, project))


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
