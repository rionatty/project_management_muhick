# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Approval alerts, turnaround tracking and value-based approval routes."""

import frappe
from frappe import _
from frappe.utils import add_to_date, flt, get_datetime, now_datetime

from project_management_muhick.setup.workflows import ADM, DECISIONS, PENDING_STATES, WORKFLOW_DOCTYPES, approver_group, approving_roles
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
	"Supplier Evaluation": [PRO],
	# Finance may now schedule the supplier on the week's payment plan
	"Procurement Requisition": [PRO, PRM, FO],
	"Purchase Order": [PRO, PRM],
	"Purchase Receipt": [FM, FO, PRM, PRO],
	"Delivery Note": [FM, FO, PRO],
	"Payment Plan": [FM, FO],
	"Reimbursement Claim": [FM, FO],
	"Resource Allocation": [FM, FO],
	"Sales Requisition": [FM, FO],
	"Bid Security Request": [FM, FO],
	"Fuel Requisition": [FO],
	"Vehicle Service Request": [FO],
	"Project Budget": [PRM, FO],
	# its approval creates the project's tasks and milestones
	"Project Activity Plan": [COO, PRM],
	"Project Budget Revision": [PRM, FO],
	"Project Requisition": [FM, FO],
	"Labour Schedule": [FM, FO],
	"Casual Sheet": [FM, FO],
	"Subcontract RFQ": [PRM, FM],
	"Subcontract Agreement": [FM, FO, PM],
	# Finance may now schedule it on the week's payment plan
	"Subcontract Advance": [FM, FO, PM],
	"Project Variation Order": [FM, SE],
	"Project Handover": [COO],
}


# told as soon as the document is sent for approval, as well as the approver
NOTIFY_ON_PENDING = {
	"Purchase Receipt": [PRO, FM, FO],
	"Delivery Note": [PRO],
	"Procurement Requisition": [PRM],
	"Bid Security Request": [GM],
	"Payment Request": [FM, FO],
}

# an administration purchase is followed by the Administration Manager and the General Manager, not Procurement
ADMINISTRATION_ON_APPROVAL = {
	"Material Request": [ADM, GM],
	"Supplier Evaluation": [ADM, PRO],
	"Procurement Requisition": [ADM, FO],
	"Purchase Order": [ADM],
	"Purchase Receipt": [FM, FO],
}
ADMINISTRATION_ON_PENDING = {"Procurement Requisition": [ADM]}

# documents whose Project Manager is kept informed
INFORM_PROJECT_MANAGER = ("Material Request", "Purchase Receipt", "Procurement Requisition", "Stock Entry", "Resource Allocation")


def _project_managers(doc) -> list[str]:
	"""Project Managers of the projects a document touches."""
	if doc.doctype not in INFORM_PROJECT_MANAGER:
		return []
	projects = {doc.get("project"), doc.get("muhick_project"), doc.get("from_project"), doc.get("to_project")}
	projects.update(row.get("project") for row in doc.get("items") or [])
	return [pm for pm in (project_manager_of(p) for p in projects if p) if pm]


def _is_administration(doc) -> bool:
	return bool(
		doc.get("muhick_administration") or doc.get("administration_purchase") or doc.get("muhick_request_origin") == "Administration"
	)


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
		notify(approvers(get_approver_roles(doc.doctype, state)), subject, doc=doc)
		told = list((ADMINISTRATION_ON_PENDING if _is_administration(doc) else NOTIFY_ON_PENDING).get(doc.doctype, []))
		if doc.doctype == "Material Request" and _is_administration(doc):
			# the company's own request: the General Manager sees it, though only Finance approves it
			told.append(GM)
		notify_roles(told, _("{0} has been raised and is awaiting approval").format(label), doc=doc, extra_users=_project_managers(doc))
	elif state == "RFQ Issued":
		notify_roles([FM, PRM], _("{0} has been issued to subcontractors").format(label), doc=doc)
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
		told = (ADMINISTRATION_ON_APPROVAL if _is_administration(doc) else NOTIFY_ON_APPROVAL).get(doc.doctype, [])
		notify_roles(told, subject, doc=doc, extra_users=[doc.owner, *_project_managers(doc)])


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


def approvers(roles) -> list[str]:
	"""Who decides for these roles: the people each role's approver group names, or everyone with the role when it names
	none."""
	users = set()
	for role in roles:
		named = frappe.get_all("User Group Member", filters={"parent": approver_group(role)}, pluck="user")
		users.update(named or users_with_roles(role))
	return sorted(users)


def _role_of_group(group) -> str | None:
	"""The role an approver group names people for, or None for any other group: a role that decides a step, in the
	add-on's workflows or on one the site has changed."""
	suffix = approver_group("")
	if not group or not group.endswith(suffix):
		return None
	role = group[: -len(suffix)]
	if role in approving_roles() or frappe.db.exists("Workflow Transition", {"allowed": role, "action": ("in", DECISIONS)}):
		return role
	return None


def validate_approver_group(doc, method=None):
	"""User Group validate: an approver group names only enabled users who hold its role. Anyone else could never decide,
	and the step would wait on them."""
	role = _role_of_group(doc.name)
	if not role:
		return
	for row in doc.get("user_group_members") or []:
		if not frappe.db.get_value("User", row.user, "enabled"):
			frappe.throw(_("{0} is disabled, so cannot decide as {1}.").format(row.user, role))
		if role not in frappe.get_roles(row.user):
			frappe.throw(_("{0} does not have the role {1}, so cannot decide as {1}.").format(row.user, role))


def leave_approver_groups(doc, method=None):
	"""User on_update: someone disabled, or no longer holding a role, leaves that role's approver group, so no step waits on
	them. A group left empty is everyone's with the role again."""
	roles = {row.role for row in doc.get("roles") or []} if doc.get("enabled") else set()
	for row in frappe.get_all("User Group Member", filters={"user": doc.name}, fields=["parent"]):
		role = _role_of_group(row.parent)
		if role and role not in roles:
			group = frappe.get_doc("User Group", row.parent)
			group.set("user_group_members", [member for member in group.user_group_members if member.user != doc.name])
			group.flags.ignore_permissions = True
			group.save()


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
		users = approvers(roles) + (users_with_roles(escalate) if escalate else [])
		notify(users, subject, doc=frappe._dict(doctype=log.reference_doctype, name=log.reference_name))
		frappe.db.set_value("Approval Turnaround Log", log.name, "alert_sent_on", now)
	frappe.db.commit()


def _escalation_role(settings, doctype, state):
	for rule in settings.get("turnaround_rules") or []:
		if rule.document_type == doctype and rule.workflow_state in (state, None, "") and rule.escalate_to_role:
			return rule.escalate_to_role
	return settings.escalation_role or GM
