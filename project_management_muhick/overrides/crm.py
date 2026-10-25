# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Leads and opportunities follow the sales process: whether to pursue a lead is the Head of Sales'
decision, recorded with who made it and when, and only a qualified lead becomes an opportunity.

The opportunity is the bid: its tender, the three parts of the bid, the submission, the bid
security and the outcome. A bid is complete with all three parts before it is submitted. Its status
(the Sales Stage) moves by itself with what is recorded on it, from Qualified to Won, Lost, Not
Pursued or Cancelled; won and lost come only from an outcome report approved by the Head of Sales
and the General Manager. When a bid is lost or closed, Finance is asked to cancel its bid security,
because the bank charges for it until it is cancelled."""

import frappe
from frappe import _
from frappe.utils import flt, format_datetime, get_datetime, getdate, now_datetime, today

from project_management_muhick.setup.workflows import PENDING_STATES
from project_management_muhick.utils.common import FINANCE_ROLES, GM, notify_roles

DECIDED = ("Qualified", "Not Pursued")
DECIDERS = {"Head of Sales", "Sales Manager"}
HOS = "Head of Sales"
BID_PARTS = (
	("muhick_administrative_bid_ready", "Administrative"),
	("muhick_technical_bid_ready", "Technical"),
	("muhick_financial_bid_ready", "Financial"),
)
# the bid statuses of a bid still going; it ends Won, Lost, Not Pursued or Cancelled
IN_PROGRESS = ("Qualified", "In Preparation", "Submitted", "Under Evaluation", "Outcome Pending Approval")
SECURITY_RUNNING = ("Requested", "Active")


def validate_lead(doc, method=None):
	if not doc.has_value_changed("qualification_status"):
		return
	before = doc.get_doc_before_save()
	deciding = doc.qualification_status in DECIDED or (before and before.qualification_status in DECIDED)
	if deciding and not DECIDERS & set(frappe.get_roles()):
		frappe.throw(_("Only the Head of Sales decides whether a lead is pursued."))
	if doc.qualification_status in DECIDED:
		doc.qualified_by, doc.qualified_on = frappe.session.user, today()
	else:
		doc.qualified_by = doc.qualified_on = None


def validate_opportunity(doc, method=None):
	if doc.is_new() and doc.opportunity_from not in ("Lead", "Customer"):
		frappe.throw(_("An opportunity comes from a qualified lead or from an existing customer."))
	if doc.is_new() and doc.opportunity_from == "Lead" and doc.party_name:
		if frappe.db.get_value("Lead", doc.party_name, "qualification_status") != "Qualified":
			frappe.throw(
				_("Lead {0} has not been qualified yet. The Head of Sales qualifies a lead before it becomes an opportunity.").format(
					doc.party_name
				)
			)
	if doc.get("items"):
		doc.opportunity_amount = flt(doc.total)
		doc.base_opportunity_amount = flt(doc.total) * flt(doc.conversion_rate or 1)
	price, cost = flt(doc.opportunity_amount), flt(doc.get("muhick_estimated_cost"))
	doc.set("muhick_margin_percent", (price - cost) / price * 100 if price and cost else 0)
	kinds = requirement_kinds(doc.get("muhick_financial_requirements"))
	securities = [r for r in doc.get("muhick_financial_requirements") or [] if kinds.get(r.requirement_type) == "Bid Security"]
	doc.set("muhick_bid_security_required", 1 if securities else 0)
	doc.set("muhick_bid_security_amount", sum(flt(r.amount) for r in securities))
	if doc.get("muhick_technical_bid_ready"):
		still_open = [str(r.idx) for r in doc.get("muhick_requirements") or [] if r.compliance in (None, "", "Clarification Needed")]
		if still_open:
			frappe.throw(
				_("The technical bid is ready only when every requirement is answered. Still open: row {0}.").format(", ".join(still_open))
			)
	check_parts_ready(doc)
	record_submission(doc)
	check_outcome_changes(doc)
	if doc.status == "Closed" and doc.has_value_changed("status") and not (doc.get("muhick_outcome_notes") or "").strip():
		frappe.throw(_("Give the reason the bid is being closed."))
	set_bid_status(doc)
	if doc.sales_stage in IN_PROGRESS:
		doc.set("muhick_outcome_date", None)
	elif doc.status in ("Lost", "Closed") and not doc.get("muhick_outcome_date"):
		doc.set("muhick_outcome_date", today())


def check_parts_ready(doc):
	"""A part is marked ready only once its documents are listed, each with its file."""
	for field, part in BID_PARTS:
		if not (doc.get(field) and doc.has_value_changed(field)):
			continue
		rows = [r for r in doc.get("muhick_documents") or [] if r.part == part]
		if not rows:
			frappe.throw(_("List the documents of the {0} bid before marking it ready.").format(_(part).lower()))
		without_file = [r.document_type for r in rows if not r.file]
		if without_file:
			frappe.throw(_("{0} bid: attach the file of {1} before marking it ready.").format(_(part), ", ".join(without_file)))


def record_submission(doc):
	"""A bid is submitted once its submission is recorded with the acknowledgement, and only a complete
	bid goes in. A submission after the deadline is flagged."""
	if doc.get("muhick_acknowledgement") and not doc.get("muhick_submitted_at"):
		doc.set("muhick_submitted_at", now_datetime())
	if not (doc.has_value_changed("muhick_submitted_at") or doc.has_value_changed("muhick_acknowledgement")):
		return
	if doc.get("muhick_submitted_at") and not doc.get("muhick_acknowledgement"):
		frappe.msgprint(
			_("The bid counts as submitted once the acknowledgement is attached: the stamped receipt, the e-GP confirmation or the email."),
			indicator="orange",
			alert=True,
		)
	if is_submitted(doc):
		missing = [_(part).lower() for field, part in BID_PARTS if not doc.get(field)]
		if missing:
			frappe.throw(_("A bid is complete only with all three parts. Still to be marked ready: {0}.").format(", ".join(missing)))
	deadline, submitted = doc.get("muhick_submission_deadline"), doc.get("muhick_submitted_at")
	if deadline and submitted and doc.has_value_changed("muhick_submitted_at") and get_datetime(submitted) > get_datetime(deadline):
		frappe.msgprint(
			_("This bid went in after its submission deadline of {0}.").format(format_datetime(deadline)),
			title=_("Submitted Late"),
			indicator="orange",
		)


def check_outcome_changes(doc):
	"""Won and lost come only from an approved outcome report, and only cancelling it reopens the bid."""
	if doc.is_new() or doc.flags.get("muhick_outcome"):
		return
	before = doc.get_doc_before_save()
	if not before:
		return
	if (doc.get("muhick_bid_outcome") or None) != (before.get("muhick_bid_outcome") or None):
		frappe.throw(_("The outcome report of a bid is set by its approval."))
	if doc.status == "Lost" and before.status != "Lost":
		frappe.throw(
			_("A lost bid is reported with Outcome > Lost on the opportunity, for the Head of Sales and the General Manager to approve."),
			title=_("Outcome Needs Approval"),
		)
	if before.status == "Lost" and doc.status != "Lost" and doc.get("muhick_bid_outcome"):
		frappe.throw(_("The loss of this bid was approved in {0}. Cancel that outcome report to reopen the bid.").format(doc.muhick_bid_outcome))


def is_submitted(doc) -> bool:
	return bool(doc.get("muhick_submitted_at") and doc.get("muhick_acknowledgement"))


def is_preparing(doc) -> bool:
	"""Work on the bid has started: its documents, a part ready, or money requested for it."""
	if doc.get("muhick_documents") or any(doc.get(field) for field, _part in BID_PARTS):
		return True
	return not doc.is_new() and any(
		frappe.db.exists(doctype, {"opportunity": doc.name, "docstatus": ("<", 2)})
		for doctype in ("Sales Requisition", "Bid Security Request")
	)


def bid_status(doc) -> str:
	"""Where a bid stands, from what is recorded on it and its outcome report."""
	if doc.status == "Lost":
		return "Lost"
	if doc.status == "Closed":
		return "Cancelled" if is_submitted(doc) else "Not Pursued"
	outcome = doc.get("muhick_bid_outcome")
	if outcome and frappe.db.get_value("Bid Outcome", outcome, "outcome") == "Won":
		return "Won"
	if not doc.is_new() and frappe.db.exists(
		"Bid Outcome", {"opportunity": doc.name, "docstatus": 0, "workflow_state": ("in", PENDING_STATES)}
	):
		return "Outcome Pending Approval"
	if is_submitted(doc):
		deadline = doc.get("muhick_submission_deadline")
		return "Under Evaluation" if deadline and get_datetime(deadline) < now_datetime() else "Submitted"
	return "In Preparation" if is_preparing(doc) else "Qualified"


def set_bid_status(doc):
	doc.sales_stage = bid_status(doc)
	if doc.has_value_changed("sales_stage") or not doc.get("muhick_stage_since"):
		doc.set("muhick_stage_since", today())


def refresh_bid_status(opportunity):
	"""A bid's status after something recorded elsewhere: a requisition, a bid security request, its
	outcome report, or the submission deadline passing."""
	if not opportunity:
		return
	doc = frappe.get_doc("Opportunity", opportunity)
	stage = bid_status(doc)
	if stage != doc.sales_stage:
		doc.db_set({"sales_stage": stage, "muhick_stage_since": today()}, notify=True)
		doc.add_comment("Info", _("Bid status: {0}").format(_(stage)))


def refresh_bid_statuses():
	"""Daily: a submitted bid goes under evaluation once its submission deadline has passed."""
	for name in frappe.get_all(
		"Opportunity", filters={"sales_stage": "Submitted", "muhick_submission_deadline": ("<", now_datetime())}, pluck="name"
	):
		refresh_bid_status(name)


def requirement_kinds(rows, field="requirement_type") -> dict:
	"""{financial requirement type: its kind} for the types on these lines."""
	types = list({r.get(field) for r in rows or [] if r.get(field)})
	if not types:
		return {}
	return dict(frappe.get_all("Financial Requirement Type", filters={"name": ("in", types)}, fields=["name", "kind"], as_list=True))


def on_update_opportunity(doc, method=None):
	before = doc.get_doc_before_save()
	if is_submitted(doc) and not (before and is_submitted(before)):
		notify_roles(
			[HOS, GM],
			_("Bid {0} ({1}) was submitted on {2}{3}.").format(
				doc.name,
				doc.customer_name,
				format_datetime(doc.get("muhick_submitted_at")),
				f" ({_(doc.muhick_submission_mode)})" if doc.get("muhick_submission_mode") else "",
			),
			doc=doc,
			extra_users=[doc.opportunity_owner],
		)
	if doc.has_value_changed("status") and doc.status in ("Lost", "Closed"):
		request_security_cancellation(doc)


def request_security_cancellation(doc):
	outcome = _(doc.status).lower()
	for security in frappe.get_all(
		"Bank Instrument",
		filters={"opportunity": doc.name, "instrument_type": "Bid Security", "status": ("in", SECURITY_RUNNING)},
		pluck="name",
	):
		frappe.db.set_value(
			"Bank Instrument", security, {"status": "Cancellation Requested", "closing_reason": _("Bid {0} was {1}.").format(doc.name, outcome)}
		)
		notify_roles(
			FINANCE_ROLES,
			_("Cancel bid security {0}: bid {1} ({2}) was {3}. The bank charges for it until it is cancelled.").format(
				security, doc.name, doc.customer_name, outcome
			),
			doc=frappe._dict(doctype="Bank Instrument", name=security),
		)


@frappe.whitelist()
def make_bid_outcome(source_name: str):
	"""The outcome report of a submitted bid, won or lost, for the Head of Sales and then the General
	Manager to approve. A won bid's BOQ comes priced at the lowest of its supplier quotations."""
	opportunity = frappe.get_doc("Opportunity", source_name)
	opportunity.check_permission("read")
	outcome = (frappe.flags.args or {}).get("outcome")
	doc = frappe.new_doc("Bid Outcome")
	doc.update({"opportunity": opportunity.name, "outcome": outcome if outcome in ("Won", "Lost") else None})
	doc.check_bid(opportunity)
	doc.prepare(opportunity)
	return doc


@frappe.whitelist()
def make_sales_requisition(source_name: str):
	"""Funds for preparing the bid on an opportunity, filled in from its financial requirements."""
	opportunity = frappe.get_doc("Opportunity", source_name)
	opportunity.check_permission("read")
	costs = bid_costs(opportunity)
	if not costs["items"]:
		frappe.msgprint(costs["note"], alert=True, indicator="orange")
	doc = frappe.new_doc("Sales Requisition")
	doc.update(
		{
			"opportunity": opportunity.name,
			"organisation": opportunity.customer_name,
			"company": opportunity.company,
			"required_by": costs["required_by"],
		}
	)
	for line in costs["items"]:
		doc.append("items", line)
	return doc


@frappe.whitelist()
def get_bid_costs(opportunity: str) -> dict:
	"""For a new sales requisition where the opportunity is picked: its cost lines and date."""
	doc = frappe.get_doc("Opportunity", opportunity)
	doc.check_permission("read")
	return bid_costs(doc)


def bid_costs(opportunity) -> dict:
	"""The cost lines of an opportunity's financial requirements, which a sales requisition pays,
	and the date the money is needed by: the site visit or, failing that, the submission deadline."""
	rows = opportunity.get("muhick_financial_requirements") or []
	kinds = requirement_kinds(rows)
	needed_by = opportunity.get("muhick_site_visit_date") or opportunity.get("muhick_submission_deadline")
	return {
		"items": [
			{"expense_type": r.requirement_type, "description": r.description, "amount": r.amount}
			for r in rows
			if kinds.get(r.requirement_type) == "Cost"
		],
		"required_by": getdate(needed_by) if needed_by else None,
		"note": _(
			"Opportunity {0} has no cost lines in its financial requirements. The bid security has a request of its own: "
			"Create > Bid Security Request on the opportunity."
		).format(opportunity.name),
	}


@frappe.whitelist()
def make_bid_security_request(source_name: str):
	"""The request for the bid security, from the Bid Security lines of the financial requirements,
	needed by the submission deadline. It goes to the Finance Manager for approval."""
	opportunity = frappe.get_doc("Opportunity", source_name)
	opportunity.check_permission("read")
	raised = frappe.db.get_value(
		"Bid Security Request", {"opportunity": opportunity.name, "docstatus": ("<", 2), "status": ("!=", "Rejected")}, "name"
	)
	if raised:
		frappe.throw(_("Bid security request {0} is already raised for this bid.").format(raised))
	rows = opportunity.get("muhick_financial_requirements") or []
	kinds = requirement_kinds(rows)
	deadline = opportunity.get("muhick_submission_deadline")
	doc = frappe.new_doc("Bid Security Request")
	doc.update(
		{
			"opportunity": opportunity.name,
			"organisation": opportunity.customer_name,
			"company": opportunity.company,
			"beneficiary": opportunity.customer_name,
			"required_by": getdate(deadline) if deadline else None,
		}
	)
	for r in rows:
		if kinds.get(r.requirement_type) == "Bid Security":
			doc.append("securities", {"security_type": r.requirement_type, "description": r.description, "amount": r.amount})
		elif kinds.get(r.requirement_type) == "Bid Security Expense":
			doc.append("expenses", {"expense_type": r.requirement_type, "description": r.description, "amount": r.amount})
	return doc
