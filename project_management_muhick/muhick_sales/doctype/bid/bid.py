# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""A bid or tender from the moment the lead is identified to the outcome: qualification, the
three parts of the bid, submission, bid security, follow-ups and the reason it was won or lost.
Every bid has a reference number and an outcome on record, so past bids can be looked up.

When a bid is lost, cancelled or not pursued, Finance is asked to cancel its bid security, because
the bank keeps charging for it until it is cancelled."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate

from project_management_muhick.utils.common import FINANCE_ROLES, GM, notify, notify_roles

HOS = "Head of Sales"
CLOSED = ("Won", "Lost", "Cancelled", "Not Pursued")
SUBMITTED = ("Submitted", "Under Evaluation", "Won", "Lost")
SECURITY_RUNNING = ("Requested", "Active")
# bid statuses that are also the sales stages of its opportunity
OPPORTUNITY_STAGES = ("Qualified", "In Preparation", "Submitted", "Under Evaluation")


class Bid(Document):
	def validate(self):
		price = flt(self.bid_price)
		self.margin_percent = (price - flt(self.estimated_cost)) / price * 100 if price and flt(self.estimated_cost) else 0
		self.set_follow_up()
		if self.status in SUBMITTED:
			missing = [
				label
				for field, label in (
					("administrative_bid_ready", _("administrative")),
					("technical_bid_ready", _("technical")),
					("financial_bid_ready", _("financial")),
				)
				if not self.get(field)
			]
			if missing:
				frappe.throw(_("A bid is complete only with all three parts. Still to be marked ready: {0}.").format(", ".join(missing)))
			if not self.submitted_on:
				self.submitted_on = nowdate()
		if self.status == "Not Pursued" and not (self.qualification_notes or "").strip():
			frappe.throw(_("Say why this lead is not being pursued."))
		if self.status in ("Won", "Lost", "Cancelled"):
			if not (self.outcome_reason or "").strip():
				frappe.throw(_("Record why the bid was {0}.").format(_(self.status).lower()))
			if not self.outcome_date:
				self.outcome_date = nowdate()
		self.flags.status_changed = not self.is_new() and self.has_value_changed("status")

	def set_follow_up(self):
		for row in self.follow_ups:
			if not row.followed_by:
				row.followed_by = frappe.session.user
		latest = max(self.follow_ups, key=lambda r: getdate(r.follow_up_date), default=None)
		self.next_follow_up = latest.next_follow_up if latest and self.status not in CLOSED else None

	def on_update(self):
		if not self.flags.status_changed:
			return
		if self.opportunity and self.status in OPPORTUNITY_STAGES:
			frappe.db.set_value("Opportunity", self.opportunity, "sales_stage", self.status)
		if self.status in ("Lost", "Cancelled", "Not Pursued"):
			self.request_security_cancellation()
		if self.status in ("Won", "Lost"):
			notify_roles(
				[HOS, GM],
				_("Bid {0} ({1}) was {2}: {3}").format(self.name, self.title, _(self.status).lower(), self.outcome_reason),
				doc=self,
				extra_users=[self.assigned_to],
			)

	def request_security_cancellation(self):
		if not self.bid_security:
			return
		if frappe.db.get_value("Bank Instrument", self.bid_security, "status") not in SECURITY_RUNNING:
			return
		frappe.db.set_value(
			"Bank Instrument",
			self.bid_security,
			{"status": "Cancellation Requested", "closing_reason": _("Bid {0} was {1}.").format(self.name, _(self.status).lower())},
		)
		notify_roles(
			FINANCE_ROLES,
			_("Cancel bid security {0}: bid {1} was {2}. The bank charges for it until it is cancelled.").format(
				self.bid_security, self.title, _(self.status).lower()
			),
			doc=frappe._dict(doctype="Bank Instrument", name=self.bid_security),
		)


@frappe.whitelist()
def make_sales_requisition(source_name: str):
	bid = frappe.get_doc("Bid", source_name)
	bid.check_permission("read")
	doc = frappe.new_doc("Sales Requisition")
	doc.update({"bid": bid.name, "bid_title": bid.title, "company": bid.company})
	return doc


@frappe.whitelist()
def make_bid_security(source_name: str):
	bid = frappe.get_doc("Bid", source_name)
	bid.check_permission("read")
	if bid.bid_security:
		frappe.throw(_("Bid security {0} already exists for this bid.").format(bid.bid_security))
	doc = frappe.new_doc("Bank Instrument")
	doc.update(
		{
			"title": _("Bid security: {0}").format(bid.title),
			"instrument_type": "Bid Security",
			"bid": bid.name,
			"company": bid.company,
			"beneficiary": bid.procuring_entity,
			"amount": bid.bid_security_amount,
		}
	)
	return doc
