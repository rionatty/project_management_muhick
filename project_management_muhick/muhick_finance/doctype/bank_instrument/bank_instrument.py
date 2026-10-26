# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""One instrument issued by the bank: a letter of credit, bid security, performance bond, advance
payment guarantee or import loan. It runs against a facility's limit from its start date to its
end date, and the bank charges a fee each quarter until it is cancelled or released, so each
instrument carries its fee schedule and the date the next fee falls due."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_months, flt, getdate, nowdate

from project_management_muhick.muhick_finance.doctype.bank_facility.bank_facility import RUNNING, get_utilised, update_utilisation
from project_management_muhick.muhick_projects.utils import validate_dates
from project_management_muhick.overrides.crm import refresh_bid_status

CLOSED = ("Cancelled", "Released", "Expired")


class BankInstrument(Document):
	def validate(self):
		validate_dates(self.issue_date, self.expiry_date, _("Start Date"), _("End Date"))
		if flt(self.amount) <= 0:
			frappe.throw(_("Enter the amount of the instrument."))
		if self.status in RUNNING:
			self.check_facility_limit()
		if self.status == "Cancellation Requested" and not (self.closing_reason or "").strip():
			frappe.throw(_("Give the reason for the cancellation."))
		if self.status in ("Cancelled", "Released") and not self.closed_on:
			self.closed_on = nowdate()
		if flt(self.fee_percent_per_quarter):
			self.quarterly_fee = flt(self.amount) * flt(self.fee_percent_per_quarter) / 100
		self.build_fee_schedule()
		self.total_fees = sum(flt(f.amount) for f in self.fees)
		self.fees_charged = sum(flt(f.amount) for f in self.fees if f.paid)
		unpaid = [getdate(f.due_date) for f in self.fees if not f.paid]
		self.next_fee_due = min(unpaid) if unpaid and self.status not in CLOSED else None
		before = self.get_doc_before_save()
		self.flags.previous_facility = before.bank_facility if before else None

	def check_facility_limit(self):
		limit, disabled = frappe.db.get_value("Bank Facility", self.bank_facility, ["limit_amount", "disabled"])
		if disabled:
			frappe.throw(_("Bank facility {0} is closed.").format(self.bank_facility))
		in_use = get_utilised(self.bank_facility, exclude=self.name)
		if in_use + flt(self.amount) > flt(limit) + 0.5:
			frappe.throw(
				_("This instrument takes facility {0} over its limit: {1} in use, limit {2}.").format(
					self.bank_facility, frappe.format_value(in_use, "Currency"), frappe.format_value(limit, "Currency")
				),
				title=_("Facility Limit Exceeded"),
			)

	def build_fee_schedule(self):
		"""One fee per quarter from the start date to the end date. A cancelled or released
		instrument keeps the fees already charged and drops those falling after it closed."""
		if self.status in ("Cancelled", "Released") and self.closed_on:
			keep = [f for f in self.fees if f.paid or getdate(f.due_date) <= getdate(self.closed_on)]
			if len(keep) != len(self.fees):
				self.set("fees", [f.as_dict() for f in keep])
			return
		if self.fees or flt(self.quarterly_fee) <= 0:
			return
		due, end = getdate(self.issue_date), getdate(self.expiry_date)
		while due <= end:
			self.append("fees", {"due_date": due, "amount": self.quarterly_fee})
			due = getdate(add_months(due, 3))

	def on_update(self):
		update_utilisation(self.bank_facility)
		if self.flags.previous_facility and self.flags.previous_facility != self.bank_facility:
			update_utilisation(self.flags.previous_facility)
		if self.opportunity and self.instrument_type == "Bid Security":
			if not frappe.db.get_value("Opportunity", self.opportunity, "muhick_bid_security"):
				frappe.db.set_value(
					"Opportunity", self.opportunity, {"muhick_bid_security": self.name, "muhick_bid_security_required": 1}
				)
		# the line of the request it was issued for: the next one not yet issued
		if self.bid_security_request and not frappe.db.exists("Bid Security Line", {"parent": self.bid_security_request, "bank_instrument": self.name}):
			line = frappe.db.get_value(
				"Bid Security Line", {"parent": self.bid_security_request, "bank_instrument": ("is", "not set")}, "name", order_by="idx asc"
			)
			if line:
				frappe.db.set_value("Bid Security Line", line, "bank_instrument", self.name, update_modified=False)
		# the bid's Bid Security Issued milestone
		if self.opportunity and self.instrument_type == "Bid Security":
			refresh_bid_status(self.opportunity)

	def after_delete(self):
		update_utilisation(self.bank_facility)
		if self.opportunity and frappe.db.get_value("Opportunity", self.opportunity, "muhick_bid_security") == self.name:
			frappe.db.set_value("Opportunity", self.opportunity, "muhick_bid_security", None)
		frappe.db.set_value("Bid Security Line", {"bank_instrument": self.name}, "bank_instrument", None, update_modified=False)
