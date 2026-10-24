# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Leads and opportunities follow the sales process: whether to pursue a lead is the Head of Sales'
decision, recorded with who made it and when, and only a qualified lead becomes an opportunity.

The opportunity is the bid: its tender, the three parts of the bid, the submission, the bid
security and the outcome. A bid is complete with all three parts before it is submitted. When it
is lost or closed, Finance is asked to cancel its bid security, because the bank charges for it
until it is cancelled."""

import frappe
from frappe import _
from frappe.utils import flt, today

from project_management_muhick.utils.common import FINANCE_ROLES, GM, notify_roles

DECIDED = ("Qualified", "Not Pursued")
DECIDERS = {"Head of Sales", "Sales Manager"}
HOS = "Head of Sales"
# stages at which the bid has gone in
SUBMITTED = ("Submitted", "Under Evaluation", "Awarded")
BID_PARTS = (
	("muhick_administrative_bid_ready", "administrative"),
	("muhick_technical_bid_ready", "technical"),
	("muhick_financial_bid_ready", "financial"),
)
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
	if doc.is_new() and doc.opportunity_from == "Lead" and doc.party_name:
		if frappe.db.get_value("Lead", doc.party_name, "qualification_status") != "Qualified":
			frappe.throw(
				_("Lead {0} has not been qualified yet. The Head of Sales qualifies a lead before it becomes an opportunity.").format(
					doc.party_name
				)
			)
	price, cost = flt(doc.opportunity_amount), flt(doc.get("muhick_estimated_cost"))
	doc.set("muhick_margin_percent", (price - cost) / price * 100 if price and cost else 0)
	if doc.sales_stage in SUBMITTED:
		missing = [_(label) for field, label in BID_PARTS if not doc.get(field)]
		if missing:
			frappe.throw(_("A bid is complete only with all three parts. Still to be marked ready: {0}.").format(", ".join(missing)))
		if not doc.get("muhick_submitted_on"):
			doc.set("muhick_submitted_on", today())
	if (doc.sales_stage == "Awarded" or doc.status in ("Lost", "Closed")) and not doc.get("muhick_outcome_date"):
		doc.set("muhick_outcome_date", today())


def on_update_opportunity(doc, method=None):
	status_changed = doc.has_value_changed("status")
	if status_changed and doc.status in ("Lost", "Closed"):
		request_security_cancellation(doc)
	if (doc.has_value_changed("sales_stage") and doc.sales_stage == "Awarded") or (status_changed and doc.status == "Lost"):
		outcome = _("lost") if doc.status == "Lost" else _("awarded")
		notify_roles(
			[HOS, GM],
			_("Bid {0} ({1}) was {2}: {3}").format(
				doc.name, doc.customer_name, outcome, doc.get("muhick_outcome_notes") or doc.order_lost_reason or ""
			),
			doc=doc,
			extra_users=[doc.opportunity_owner],
		)


def request_security_cancellation(doc):
	security = doc.get("muhick_bid_security")
	if not security or frappe.db.get_value("Bank Instrument", security, "status") not in SECURITY_RUNNING:
		return
	outcome = _(doc.status).lower()
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
def make_sales_requisition(source_name: str):
	"""Funds for preparing the bid on an opportunity."""
	opportunity = frappe.get_doc("Opportunity", source_name)
	opportunity.check_permission("read")
	doc = frappe.new_doc("Sales Requisition")
	doc.update({"opportunity": opportunity.name, "organisation": opportunity.customer_name, "company": opportunity.company})
	return doc


@frappe.whitelist()
def make_bid_security(source_name: str):
	opportunity = frappe.get_doc("Opportunity", source_name)
	opportunity.check_permission("read")
	if opportunity.get("muhick_bid_security"):
		frappe.throw(_("Bid security {0} already exists for this bid.").format(opportunity.muhick_bid_security))
	doc = frappe.new_doc("Bank Instrument")
	doc.update(
		{
			"title": _("Bid security: {0}").format(opportunity.customer_name),
			"instrument_type": "Bid Security",
			"opportunity": opportunity.name,
			"company": opportunity.company,
			"beneficiary": opportunity.customer_name,
			"amount": opportunity.get("muhick_bid_security_amount"),
		}
	)
	return doc
