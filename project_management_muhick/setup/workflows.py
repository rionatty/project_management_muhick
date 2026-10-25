# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Approval workflows for the project, procurement, stores and finance documents.

Each workflow is created once. After that it belongs to the site: an administrator can change
steps and roles in the Workflow screen and a later migrate will not overwrite the change.
"""

import frappe

from project_management_muhick.utils.common import COO, FM, FO, GM, PM, PRM, PRO, SE, SK, SSK

ADM = "Administration Manager"
HOS = "Head of Sales"
FLEET = "Fleet Officer"
P_HOS, P_ADM = "Pending Head of Sales", "Pending Administration Manager"

DRAFT, APPROVED, REJECTED, CANCELLED = "Draft", "Approved", "Rejected", "Cancelled"
P_COO, P_FM, P_GM, P_PRM = "Pending COO", "Pending Finance Manager", "Pending General Manager", "Pending Procurement Manager"
SUBMIT, APPROVE, REJECT, CANCEL = "Submit for Approval", "Approve", "Reject", "Cancel"
DIRECT = "Submit"

# every state used below and its list-view colour
STATE_STYLES = {
	DRAFT: "",
	P_COO: "Warning",
	P_FM: "Warning",
	P_GM: "Warning",
	P_PRM: "Warning",
	P_HOS: "Warning",
	P_ADM: "Warning",
	APPROVED: "Success",
	REJECTED: "Danger",
	CANCELLED: "Inverse",
	"RFQ Issued": "Info",
	"Evaluation Returned": "Danger",
	"Pending Acceptance": "Warning",
	"Accepted": "Success",
	"Returned": "Danger",
}
ACTIONS = [
	SUBMIT, DIRECT, APPROVE, REJECT, CANCEL, "Issue RFQ", "Submit Evaluation", "Submit for Acceptance",
	"Accept", "Return", "Select Supplier",
]

PENDING_STATES = (P_COO, P_FM, P_GM, P_PRM, P_HOS, P_ADM, "Pending Acceptance")


def _state(state, doc_status, *roles):
	return [dict(state=state, doc_status=str(doc_status), allow_edit=role) for role in roles]


def _t(state, action, next_state, roles, condition=None):
	if isinstance(roles, str):
		roles = [roles]
	# nobody approves or accepts a document they raised themselves (segregation of duties)
	self_approval = 0 if action in (APPROVE, "Accept") else 1
	return [
		dict(state=state, action=action, next_state=next_state, allowed=role, allow_self_approval=self_approval, condition=condition)
		for role in roles
	]


def _chain(originators, approvers, post_approval_editors=(), pending_editors=(), submit_action=SUBMIT):
	"""Draft -> one pending step per approver -> Approved, with a Reject at every step.

	approvers: ordered (pending_state, role) pairs.
	pending_editors: roles that may still edit while the document is under approval.
	"""
	states = _state(DRAFT, 0, *originators)
	transitions = []
	first = approvers[0][0]
	transitions += _t(DRAFT, submit_action, first, originators)
	for i, (pending, role) in enumerate(approvers):
		states += _state(pending, 0, role, *pending_editors)
		next_state = approvers[i + 1][0] if i + 1 < len(approvers) else APPROVED
		transitions += _t(pending, APPROVE, next_state, role)
		transitions += _t(pending, REJECT, REJECTED, role)
	final_role = approvers[-1][1]
	states += _state(APPROVED, 1, final_role, *post_approval_editors)
	states += _state(REJECTED, 0, *originators)
	states += _state(CANCELLED, 2, final_role)
	transitions += _t(REJECTED, submit_action, first, originators)
	transitions += _t(APPROVED, CANCEL, CANCELLED, final_role)
	return states, transitions


FULL_CHAIN = [(P_COO, COO), (P_FM, FM), (P_GM, GM)]


def _requisition():
	"""Project Requisition: PM -> COO -> Finance -> GM, shortened by the approval thresholds.
	An unbudgeted (exception) claim goes COO -> GM."""
	originators = [PM, SSK]
	states = (
		_state(DRAFT, 0, *originators)
		+ _state(P_COO, 0, COO)
		+ _state(P_FM, 0, FM)
		+ _state(P_GM, 0, GM)
		+ _state(APPROVED, 1, GM, FM, FO, *originators)
		+ _state(REJECTED, 0, *originators)
		+ _state(CANCELLED, 2, GM)
	)
	route = "doc.approval_route"
	transitions = (
		_t(DRAFT, SUBMIT, P_COO, originators)
		+ _t(P_COO, APPROVE, APPROVED, COO, f'{route} == "First Approver Only"')
		+ _t(P_COO, APPROVE, P_GM, COO, f'{route} == "Unbudgeted Exception"')
		+ _t(P_COO, APPROVE, P_FM, COO, f'{route} not in ("First Approver Only", "Unbudgeted Exception")')
		+ _t(P_COO, REJECT, REJECTED, COO)
		+ _t(P_FM, APPROVE, APPROVED, FM, f'{route} == "Up to Second Approver"')
		+ _t(P_FM, APPROVE, P_GM, FM, f'{route} != "Up to Second Approver"')
		+ _t(P_FM, REJECT, REJECTED, FM)
		+ _t(P_GM, APPROVE, APPROVED, GM)
		+ _t(P_GM, REJECT, REJECTED, GM)
		+ _t(REJECTED, SUBMIT, P_COO, originators)
		+ _t(APPROVED, CANCEL, CANCELLED, GM)
	)
	return states, transitions


def _subcontract_rfq():
	"""RFQ issued, quotations recorded, then the evaluation approved by the COO and the General Manager."""
	returned = "Evaluation Returned"
	states = (
		_state(DRAFT, 0, PM)
		+ _state("RFQ Issued", 0, PM)
		+ _state(P_COO, 0, COO)
		+ _state(P_GM, 0, GM)
		+ _state(APPROVED, 1, GM)
		+ _state(returned, 0, PM)
		+ _state(CANCELLED, 2, GM)
	)
	transitions = (
		_t(DRAFT, "Issue RFQ", "RFQ Issued", PM)
		+ _t("RFQ Issued", "Submit Evaluation", P_COO, PM)
		+ _t(P_COO, APPROVE, P_GM, COO)
		+ _t(P_COO, REJECT, returned, COO)
		+ _t(P_GM, APPROVE, APPROVED, GM)
		+ _t(P_GM, REJECT, returned, GM)
		+ _t(returned, "Submit Evaluation", P_COO, PM)
		+ _t(APPROVED, CANCEL, CANCELLED, GM)
	)
	return states, transitions


def _handover():
	"""Sales hands the won bid to the Project Manager, who accepts or returns the pack."""
	states = (
		_state(DRAFT, 0, SE)
		+ _state("Pending Acceptance", 0, PM)
		+ _state("Accepted", 1, PM)
		+ _state("Returned", 0, SE)
		+ _state(CANCELLED, 2, COO)
	)
	transitions = (
		_t(DRAFT, "Submit for Acceptance", "Pending Acceptance", SE)
		+ _t("Pending Acceptance", "Accept", "Accepted", PM)
		+ _t("Pending Acceptance", "Return", "Returned", PM)
		+ _t("Returned", "Submit for Acceptance", "Pending Acceptance", SE)
		+ _t("Accepted", CANCEL, CANCELLED, COO)
	)
	return states, transitions


def _material_request():
	"""Material Request approval routes.

	Purchase or issue for a project / user department : COO, then Finance and GM when over budget.
	Fixed asset                                       : COO, Finance Manager and General Manager, always.
	Administration request                            : Finance Manager.
	Transfer to a site store                          : Procurement Manager.
	"""
	originators = ["Stock User", "Purchase User", PM, SK, SSK, ADM]
	is_transfer = 'doc.material_request_type == "Material Transfer"'
	is_admin = 'doc.muhick_request_origin == "Administration"'
	coo_only = (
		'doc.muhick_budget_status in ("Within Budget", "Not Applicable", "", None)'
		' and doc.muhick_request_origin != "Fixed Asset"'
	)
	states = (
		_state(DRAFT, 0, *originators)
		+ _state(P_COO, 0, COO)
		+ _state(P_FM, 0, FM)
		+ _state(P_GM, 0, GM)
		+ _state(P_PRM, 0, PRM)
		+ _state(APPROVED, 1, PRM)
		+ _state(REJECTED, 0, *originators)
		+ _state(CANCELLED, 2, PRM)
	)
	transitions = []
	for start in (DRAFT, REJECTED):
		transitions += _t(start, SUBMIT, P_PRM, originators, is_transfer)
		transitions += _t(start, SUBMIT, P_FM, originators, f"not ({is_transfer}) and {is_admin}")
		transitions += _t(start, SUBMIT, P_COO, originators, f"not ({is_transfer}) and not ({is_admin})")
	transitions += (
		_t(P_COO, APPROVE, APPROVED, COO, coo_only)
		+ _t(P_COO, APPROVE, P_FM, COO, f"not ({coo_only})")
		+ _t(P_COO, REJECT, REJECTED, COO)
		+ _t(P_FM, APPROVE, APPROVED, FM, is_admin)
		+ _t(P_FM, APPROVE, P_GM, FM, f"not ({is_admin})")
		+ _t(P_FM, REJECT, REJECTED, FM)
		+ _t(P_GM, APPROVE, APPROVED, GM)
		+ _t(P_GM, REJECT, REJECTED, GM)
		+ _t(P_PRM, APPROVE, APPROVED, PRM)
		+ _t(P_PRM, REJECT, REJECTED, PRM)
		+ _t(APPROVED, CANCEL, CANCELLED, [PRM, COO, GM])
	)
	return states, transitions


def _supplier_quotation():
	"""Quotations are recorded as drafts. The officer sends the chosen one for approval, which is
	the supplier selection; the Procurement Manager approves or rejects it."""
	officers = ["Purchase User", PRO]
	return _chain(officers, [(P_PRM, PRM)], submit_action="Select Supplier")


def _purchase_order():
	officers = ["Purchase User", PRO, PRM]
	states = (
		_state(DRAFT, 0, *officers)
		+ _state(P_GM, 0, GM)
		+ _state(APPROVED, 1, GM, "Purchase User", "Purchase Manager")
		+ _state(REJECTED, 0, *officers)
		+ _state(CANCELLED, 2, GM)
	)
	transitions = (
		_t(DRAFT, SUBMIT, P_GM, officers)
		+ _t(P_GM, APPROVE, APPROVED, GM)
		+ _t(P_GM, REJECT, REJECTED, GM)
		+ _t(REJECTED, SUBMIT, P_GM, officers)
		+ _t(APPROVED, CANCEL, CANCELLED, [GM, "Purchase Manager"])
	)
	return states, transitions


def _purchase_receipt():
	"""Goods received note: raised by the storekeeper, approved by the Procurement Manager."""
	receivers = ["Stock User", "Purchase User", SK, SSK]
	states = (
		_state(DRAFT, 0, *receivers)
		+ _state(P_PRM, 0, PRM)
		+ _state(APPROVED, 1, PRM, "Stock User")
		+ _state(REJECTED, 0, *receivers)
		+ _state(CANCELLED, 2, PRM)
	)
	transitions = (
		_t(DRAFT, SUBMIT, P_PRM, receivers)
		+ _t(P_PRM, APPROVE, APPROVED, PRM)
		+ _t(P_PRM, REJECT, REJECTED, PRM)
		+ _t(REJECTED, SUBMIT, P_PRM, receivers)
		+ _t(APPROVED, CANCEL, CANCELLED, [PRM, "Stock Manager"])
	)
	return states, transitions


def _delivery_note():
	"""A delivery is approved by the Procurement Manager; a return from a customer by Finance."""
	raisers = ["Stock User", "Sales User", SK]
	is_return = "doc.is_return"
	finance = [FM, FO]
	states = (
		_state(DRAFT, 0, *raisers)
		+ _state(P_PRM, 0, PRM)
		+ _state(P_FM, 0, *finance)
		+ _state(APPROVED, 1, PRM, "Stock User")
		+ _state(REJECTED, 0, *raisers)
		+ _state(CANCELLED, 2, PRM)
	)
	transitions = []
	for start in (DRAFT, REJECTED):
		transitions += _t(start, SUBMIT, P_FM, raisers, is_return)
		transitions += _t(start, SUBMIT, P_PRM, raisers, f"not {is_return}")
	transitions += (
		_t(P_PRM, APPROVE, APPROVED, PRM)
		+ _t(P_PRM, REJECT, REJECTED, PRM)
		+ _t(P_FM, APPROVE, APPROVED, finance)
		+ _t(P_FM, REJECT, REJECTED, finance)
		+ _t(APPROVED, CANCEL, CANCELLED, [PRM, "Stock Manager"])
	)
	return states, transitions


def _stock_entry():
	"""Most stock entries are submitted directly. Two need approval first: a return of materials
	from a site store (Procurement Manager) and a disposal (Finance)."""
	keepers = ["Stock User", "Stock Manager", SK, SSK]
	route = "doc.muhick_approval_route"
	finance = [FM, FO]
	states = (
		_state(DRAFT, 0, *keepers)
		+ _state(P_PRM, 0, PRM)
		+ _state(P_FM, 0, *finance)
		+ _state(APPROVED, 1, "Stock User", "Stock Manager")
		+ _state(REJECTED, 0, *keepers)
		+ _state(CANCELLED, 2, "Stock Manager")
	)
	transitions = []
	for start in (DRAFT, REJECTED):
		transitions += _t(start, DIRECT, APPROVED, keepers, f'{route} in ("", None)')
		transitions += _t(start, SUBMIT, P_PRM, keepers, f'{route} == "Procurement Manager"')
		transitions += _t(start, SUBMIT, P_FM, keepers, f'{route} == "Finance"')
	transitions += (
		_t(P_PRM, APPROVE, APPROVED, PRM)
		+ _t(P_PRM, REJECT, REJECTED, PRM)
		+ _t(P_FM, APPROVE, APPROVED, finance)
		+ _t(P_FM, REJECT, REJECTED, finance)
		+ _t(APPROVED, CANCEL, CANCELLED, ["Stock Manager", PRM])
	)
	return states, transitions


def _reimbursement_claim():
	"""Expense claim: a project expense goes COO then General Manager; an administration expense
	goes to the General Manager. An emergency site purchase has one approver, the COO."""
	raisers = [ADM, PM, SSK]
	emergency = 'doc.claim_type == "Emergency Site Purchase"'
	to_coo = f"{emergency} or doc.project"
	states = (
		_state(DRAFT, 0, *raisers)
		+ _state(P_COO, 0, COO)
		+ _state(P_GM, 0, GM)
		+ _state(APPROVED, 1, GM, FM, FO)
		+ _state(REJECTED, 0, *raisers)
		+ _state(CANCELLED, 2, GM)
	)
	transitions = []
	for start in (DRAFT, REJECTED):
		transitions += _t(start, SUBMIT, P_COO, raisers, to_coo)
		transitions += _t(start, SUBMIT, P_GM, raisers, f"not ({to_coo})")
	transitions += (
		_t(P_COO, APPROVE, APPROVED, COO, emergency)
		+ _t(P_COO, APPROVE, P_GM, COO, f"not ({emergency})")
		+ _t(P_COO, REJECT, REJECTED, COO)
		+ _t(P_GM, APPROVE, APPROVED, GM)
		+ _t(P_GM, REJECT, REJECTED, GM)
		+ _t(APPROVED, CANCEL, CANCELLED, GM)
	)
	return states, transitions


def _fleet(final_step_gm):
	"""Fuel and vehicle servicing: the Administration Manager first, then Finance and (for
	servicing) the General Manager, shortened by the approval thresholds."""
	raisers = [FLEET, ADM]
	route = "doc.approval_route"
	states = (
		_state(DRAFT, 0, *raisers)
		+ _state(P_ADM, 0, ADM)
		+ _state(P_FM, 0, FM)
		+ (_state(P_GM, 0, GM) if final_step_gm else [])
		+ _state(APPROVED, 1, ADM, FLEET)
		+ _state(REJECTED, 0, *raisers)
		+ _state(CANCELLED, 2, ADM)
	)
	transitions = (
		_t(DRAFT, SUBMIT, P_ADM, raisers)
		+ _t(REJECTED, SUBMIT, P_ADM, raisers)
		+ _t(P_ADM, APPROVE, APPROVED, ADM, f'{route} == "First Approver Only"')
		+ _t(P_ADM, APPROVE, P_FM, ADM, f'{route} != "First Approver Only"')
		+ _t(P_ADM, REJECT, REJECTED, ADM)
		+ _t(P_FM, REJECT, REJECTED, FM)
		+ _t(APPROVED, CANCEL, CANCELLED, ADM)
	)
	if final_step_gm:
		transitions += (
			_t(P_FM, APPROVE, APPROVED, FM, f'{route} == "Up to Second Approver"')
			+ _t(P_FM, APPROVE, P_GM, FM, f'{route} != "Up to Second Approver"')
			+ _t(P_GM, APPROVE, APPROVED, GM)
			+ _t(P_GM, REJECT, REJECTED, GM)
		)
	else:
		transitions += _t(P_FM, APPROVE, APPROVED, FM)
	return states, transitions


def get_workflows():
	return {
		# budget: COO, Finance Manager, General Manager
		"Project Budget": _chain([PM], FULL_CHAIN, post_approval_editors=[PM, COO]),
		# cost control sheet and other budget changes
		"Project Budget Revision": _chain([PM, PRO], FULL_CHAIN),
		# activity plan: COO, Finance Manager, General Manager
		"Project Activity Plan": _chain([PM], FULL_CHAIN),
		"Project Requisition": _requisition(),
		# labour: COO, then Finance Manager
		"Labour Schedule": _chain([PM], [(P_COO, COO), (P_FM, FM)]),
		"Casual Sheet": _chain([PM], [(P_COO, COO), (P_FM, FM)], post_approval_editors=[COO]),
		"Subcontract RFQ": _subcontract_rfq(),
		# subcontract agreement: COO, then General Manager
		"Subcontract Agreement": _chain([PRO, PM], [(P_COO, COO), (P_GM, GM)], post_approval_editors=[PM, COO]),
		"Project Variation Order": _chain([PM, SE], [(P_COO, COO), (P_GM, GM)]),
		"Project Handover": _handover(),
		"Material Request": _material_request(),
		# procurement: supplier selection, requisition, order, goods received
		"Supplier Quotation": _supplier_quotation(),
		# the officer may still correct prices while it is under approval; the change is logged
		"Procurement Requisition": _chain([PRO, PRM], FULL_CHAIN, post_approval_editors=[PRO, PRM], pending_editors=[PRO]),
		"Purchase Order": _purchase_order(),
		"Purchase Receipt": _purchase_receipt(),
		# stores
		"Delivery Note": _delivery_note(),
		"Stock Entry": _stock_entry(),
		# finance: weekly or monthly payment plan, expense claims
		"Payment Plan": _chain([FO, FM], [(P_FM, FM), (P_GM, GM)], post_approval_editors=[FO, FM]),
		"Reimbursement Claim": _reimbursement_claim(),
		"Project Fund Transfer": _chain([FO, FM], [(P_FM, FM), (P_GM, GM)], post_approval_editors=[FO, FM]),
		# sales: funds for a bid
		"Sales Requisition": _chain([SE], [(P_HOS, HOS), (P_GM, GM)], post_approval_editors=[FM, FO, SE]),
		# a rejected request is amended and sent again, or left closed while the bid goes on
		"Bid Security Request": _chain([SE], [(P_FM, FM)], post_approval_editors=[FO]),
		# the outcome of a bid, won or lost: the Head of Sales, then the General Manager
		"Bid Outcome": _chain([SE], [(P_HOS, HOS), (P_GM, GM)]),
		# administration
		"Fuel Requisition": _fleet(final_step_gm=False),
		"Vehicle Service Request": _fleet(final_step_gm=True),
	}


WORKFLOW_DOCTYPES = tuple(get_workflows())


def workflow_name(doctype):
	return f"Muhick {doctype} Approval"


def setup_workflows(force=False, doctypes=None):
	for state, style in STATE_STYLES.items():
		if not frappe.db.exists("Workflow State", state):
			frappe.get_doc(doctype="Workflow State", workflow_state_name=state, style=style).insert(ignore_permissions=True)
	for action in ACTIONS:
		if not frappe.db.exists("Workflow Action Master", action):
			frappe.get_doc(doctype="Workflow Action Master", workflow_action_name=action).insert(ignore_permissions=True)

	for doctype, (states, transitions) in get_workflows().items():
		if doctypes and doctype not in doctypes:
			continue
		name = workflow_name(doctype)
		if frappe.db.exists("Workflow", name):
			if not force:
				continue
			frappe.delete_doc("Workflow", name, ignore_permissions=True, force=True)
		# only take over the document if no other workflow is already active on it
		active_elsewhere = frappe.db.exists("Workflow", {"document_type": doctype, "is_active": 1})
		frappe.get_doc(
			doctype="Workflow",
			workflow_name=name,
			document_type=doctype,
			is_active=0 if active_elsewhere else 1,
			# built-in workflow emails need an outgoing email account; the app sends its own alerts
			send_email_alert=0,
			workflow_state_field="workflow_state",
			states=states,
			transitions=transitions,
		).insert(ignore_permissions=True)
