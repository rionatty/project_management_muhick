# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Approval alerts, turnaround tracking and value-based approval routes."""

import frappe
from frappe import _
from frappe.utils import add_to_date, flt, get_datetime, now_datetime

from project_management_muhick.setup.workflows import P_FM, PENDING_STATES, WORKFLOW_DOCTYPES
from project_management_muhick.utils import calc
from project_management_muhick.utils.common import (
	COO, FM, FO, GM, PM, PRM, PRO, SE, SK, get_settings, notify, notify_roles, project_manager_of, users_with_roles,
)

APPROVED_STATES = ("Approved", "Accepted")
RETURNED_STATES = ("Rejected", "Evaluation Returned", "Returned")
APPROVE_ACTIONS = ("Approve", "Accept")

# who is told when a document is finally approved
NOTIFY_ON_APPROVAL = {
	"Material Request": [PRM, PRO, SK],
	"Supplier Quotation": [PRO],
	"Procurement Requisition": [PRO, PRM],
	"Purchase Order": [PRO, PRM],
	"Purchase Receipt": [FM, FO, PRM, PRO],
	"Delivery Note": [FM, FO, PRO],
	"Payment Plan": [FM, FO],
	"Reimbursement Claim": [FM, FO],
	"Project Fund Transfer": [FM, FO],
	"Sales Requisition": [FM, FO],
	"Fuel Requisition": [FO],
	"Vehicle Service Request": [FO],
	"Project Budget": [PRM, FO],
	"Project Budget Revision": [PRM, FO],
	"Project Requisition": [FM, FO],
	"Labour Schedule": [FM, FO],
	"Casual Sheet": [FM, FO],
	"Subcontract RFQ": [PRM, FM],
	"Subcontract Agreement": [FM, FO, PM],
	"Project Variation Order": [FM, SE],
	"Project Handover": [COO],
}


# told as soon as the document is sent for approval, as well as the approver; a {state: roles} entry
# only for that step
NOTIFY_ON_PENDING = {
	"Purchase Receipt": [PRO, FM, FO],
	"Delivery Note": [PRO],
	"Procurement Requisition": [PRM],
	# a bid security request: the General Manager is told as well as the Finance Manager
	"Sales Requisition": {P_FM: [GM]},
}

# documents whose Project Manager is kept informed
INFORM_PROJECT_MANAGER = ("Material Request", "Purchase Receipt", "Procurement Requisition", "Stock Entry")


def _project_managers(doc) -> list[str]:
	"""Project Managers of the projects a document touches."""
	if doc.doctype not in INFORM_PROJECT_MANAGER:
		return []
	projects = {doc.get("project"), doc.get("muhick_project")}
	projects.update(row.get("project") for row in doc.get("items") or [])
	return [pm for pm in (project_manager_of(p) for p in projects if p) if pm]


def _is_urgent(doc) -> bool:
	return "Urgent" in (doc.get("priority"), doc.get("muhick_priority"))


# ------------------------------------------------------------------ routes
def get_route(doctype, amount, risk_class="Any") -> str:
	"""Approval route for a document total, from the thresholds in Muhick Settings."""
	thresholds = [
		t.as_dict() for t in get_settings().get("approval_thresholds") or [] if t.document_type == doctype
	]
	return calc.approval_route(amount, thresholds, risk_class)


# ------------------------------------------------------------------ tracking
def track(doc, method=None):
	"""doc_event (on_update / on_submit / on_cancel): react when the approval step changes."""
	if doc.doctype not in WORKFLOW_DOCTYPES or frappe.flags.in_install or frappe.flags.in_migrate:
		return
	state = doc.get("workflow_state")
	before = doc.get_doc_before_save()
	previous = before.get("workflow_state") if before else None
	if not state or state == previous:
		return
	try:
		_on_state_change(doc, state, previous)
	except Exception:
		# alerts and logs must never stop an approval
		frappe.log_error(title=f"Muhick: approval tracking failed for {doc.doctype} {doc.name}")


def _on_state_change(doc, state, previous=None):
	now = now_datetime()
	project = doc.get("project") or doc.get("muhick_project")
	_close_open_logs(doc, now, state)
	label = f"{_(doc.doctype)} {doc.name}"

	if state in PENDING_STATES:
		frappe.get_doc(
			doctype="Approval Turnaround Log",
			reference_doctype=doc.doctype,
			reference_name=doc.name,
			project=project,
			workflow_state=state,
			entered_on=now,
			is_open=1,
			allowed_hours=_allowed_hours(doc.doctype, state),
		).insert(ignore_permissions=True)
		subject = _("{0}{1} is waiting for your approval").format(_("URGENT: ") if _is_urgent(doc) else "", label)
		notify_roles(get_approver_roles(doc.doctype, state), subject, doc=doc)
		watchers = NOTIFY_ON_PENDING.get(doc.doctype, [])
		notify_roles(
			watchers.get(state, []) if isinstance(watchers, dict) else watchers,
			_("{0} has been raised and is awaiting approval").format(label),
			doc=doc,
			extra_users=_project_managers(doc),
		)
	elif state in RETURNED_STATES:
		reason = (doc.get("rejection_reason") or "").strip()
		notify([doc.owner], _("{0} was returned: {1}").format(label, f"{_(state)}. {reason}" if reason else _(state)), doc=doc)
	elif state in APPROVED_STATES:
		if doc.doctype == "Stock Entry" and previous not in PENDING_STATES:
			# submitted directly with no approval step: only an issue to a project is announced
			if doc.purpose == "Material Issue" and doc.project:
				notify_roles(PRO, _("{0}: materials issued to project {1}.").format(label, doc.project), doc=doc)
			return
		subject = _("{0} has been approved").format(label)
		notify_roles(
			NOTIFY_ON_APPROVAL.get(doc.doctype, []), subject, doc=doc, extra_users=[doc.owner, *_project_managers(doc)]
		)


def _close_open_logs(doc, now, next_state):
	for log in frappe.get_all(
		"Approval Turnaround Log",
		filters={"reference_doctype": doc.doctype, "reference_name": doc.name, "is_open": 1},
		fields=["name", "entered_on"],
	):
		frappe.db.set_value(
			"Approval Turnaround Log",
			log.name,
			{
				"is_open": 0,
				"exited_on": now,
				"hours_in_state": calc.hours_between(get_datetime(log.entered_on), now),
				"next_state": next_state,
				"actioned_by": frappe.session.user,
			},
		)


def _allowed_hours(doctype, state) -> float:
	settings = get_settings()
	rules = [r for r in settings.get("turnaround_rules") or [] if r.document_type == doctype]
	for rule in rules:
		if rule.workflow_state == state:
			return flt(rule.max_hours)
	for rule in rules:
		if not rule.workflow_state:
			return flt(rule.max_hours)
	return flt(settings.default_turnaround_hours) or 72.0


def get_approver_roles(doctype, state) -> list[str]:
	from frappe.model.workflow import get_workflow_name

	workflow = get_workflow_name(doctype)
	if not workflow:
		return []
	return frappe.get_all(
		"Workflow Transition",
		filters={"parent": workflow, "state": state, "action": ("in", APPROVE_ACTIONS)},
		pluck="allowed",
		distinct=True,
	)


# ------------------------------------------------------------------ scheduled
def send_overdue_alerts():
	"""Hourly: chase approvals that have sat in one step longer than allowed, once a day each."""
	settings = get_settings()
	if not settings.send_turnaround_alerts:
		return
	now = now_datetime()
	logs = frappe.get_all(
		"Approval Turnaround Log",
		filters={"is_open": 1},
		fields=["name", "reference_doctype", "reference_name", "workflow_state", "entered_on", "allowed_hours", "alert_sent_on"],
	)
	for log in logs:
		waited = calc.hours_between(get_datetime(log.entered_on), now)
		if waited <= flt(log.allowed_hours):
			continue
		if log.alert_sent_on and get_datetime(log.alert_sent_on) > add_to_date(now, hours=-24):
			continue
		if not frappe.db.exists(log.reference_doctype, log.reference_name):
			frappe.db.set_value("Approval Turnaround Log", log.name, "is_open", 0)
			continue
		roles = get_approver_roles(log.reference_doctype, log.workflow_state)
		escalate = _escalation_role(settings, log.reference_doctype, log.workflow_state)
		subject = _("Overdue approval: {0} {1} has waited {2} hours at {3} (allowed {4})").format(
			_(log.reference_doctype), log.reference_name, round(waited), _(log.workflow_state), round(flt(log.allowed_hours))
		)
		users = users_with_roles(*roles, escalate) if escalate else users_with_roles(*roles)
		notify(users, subject, doc=frappe._dict(doctype=log.reference_doctype, name=log.reference_name))
		frappe.db.set_value("Approval Turnaround Log", log.name, "alert_sent_on", now)
	frappe.db.commit()


def _escalation_role(settings, doctype, state):
	for rule in settings.get("turnaround_rules") or []:
		if rule.document_type == doctype and rule.workflow_state in (state, None, "") and rule.escalate_to_role:
			return rule.escalate_to_role
	return settings.escalation_role or GM
