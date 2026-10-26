# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""A request for a bid security. The Sales Executive raises it from the bid (the opportunity); the
Finance Manager and the General Manager are told, and the Finance Manager approves it or rejects it
with the reason: a rejected request is amended and sent again, or left closed while the bid goes on.
Once it is approved, the funds needed to obtain the securities (the one-off expenses and the first
payment of the recurring ones) go on the weekly payment plan and are issued from there, and Finance
records each security when the bank or insurer has issued it; a recurring expense becomes that
security's quarterly fee, which the payment plan picks up as it falls due. A request with no expenses needs no
funds: its securities are recorded as soon as it is approved."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate, today

from project_management_muhick.muhick_finance.doctype.bank_facility.bank_facility import get_utilised
from project_management_muhick.muhick_finance.doctype.payment_plan.payment_plan import settle_plan_line
from project_management_muhick.muhick_projects.utils import draft_status, validate_dates
from project_management_muhick.overrides.crm import refresh_bid_status
from project_management_muhick.utils.common import FINANCE_ROLES, notify, require_roles

# how many times a year a recurring expense falls due
PER_YEAR = {"Month": 12, "Quarter": 4, "Year": 1}


class BidSecurityRequest(Document):
	def validate(self):
		if not self.requested_by:
			self.requested_by = frappe.session.user
		validate_dates(self.request_date, self.required_by, _("Date"), _("Required By"))
		self.amount = sum(flt(r.amount) for r in self.securities)
		if flt(self.amount) <= 0:
			frappe.throw(_("Enter the bid securities and their amounts."))
		self.funds_required = sum(flt(r.amount) for r in self.expenses)
		self.facility_available = facility_headroom(self.bank_facility, self.name)["available"] if self.bank_facility else 0
		self.status = draft_status(self)
		if self.has_value_changed("workflow_state") and self.workflow_state == "Rejected" and not (self.rejection_reason or "").strip():
			frappe.throw(_("Give the reason for the rejection, and say whether the request can be amended and sent again."))

	def after_insert(self):
		# the bid security asked for: the bid's preparation has started
		refresh_bid_status(self.opportunity)

	def before_submit(self):
		self.check_facility()
		self.status = "Approved"

	def check_facility(self):
		"""The securities must fit in what the bank facility has left."""
		if not self.bank_facility:
			frappe.throw(_("Choose the bank facility the securities will be drawn on."))
		room = facility_headroom(self.bank_facility, self.name)
		if room["closed"]:
			frappe.throw(_("Bank facility {0} is closed.").format(self.bank_facility))
		if flt(self.amount) > room["available"] + 0.5:
			amounts = [
				frappe.format_value(value, "Currency")
				for value in (self.amount, room["available"], room["limit"], room["in_use"], room["reserved"])
			]
			frappe.throw(
				_("These securities ({0}) do not fit in facility {5}: {1} is available of its {2} limit, with {3} in use and {4} approved but not yet issued.").format(
					*amounts, self.bank_facility
				),
				title=_("Facility Limit Exceeded"),
			)

	def on_cancel(self):
		if flt(self.amount_issued):
			frappe.throw(_("Funds have already been issued for this request; it cannot be cancelled."))
		self.db_set("status", "Cancelled")

	def issue_funds(self, amount_issued: float, issued_on: str | None = None, payment_reference: str | None = None):
		"""Funds issued from the request's line on an approved payment plan."""
		require_roles(*FINANCE_ROLES)
		if self.docstatus != 1 or self.status != "Approved":
			frappe.throw(_("Funds are issued once the request is approved."))
		if not flt(self.funds_required):
			frappe.throw(_("This request needs no funds. Record each security once the bank or insurer has issued it."))
		if flt(amount_issued) <= 0 or flt(amount_issued) > flt(self.funds_required) + 0.005:
			frappe.throw(_("The amount issued must be more than zero and not more than the funds required."))
		self.db_set(
			{
				"amount_issued": flt(amount_issued),
				"issued_on": issued_on or nowdate(),
				"payment_reference": payment_reference,
				"status": "Funds Issued",
			}
		)
		settle_plan_line(self.doctype, self.name, amount_issued)
		notify([self.requested_by], _("Funds for bid security request {0} have been issued.").format(self.name), doc=self)


def ready_to_record(request) -> bool:
	"""Approved, with its funds issued or none needed."""
	return request.docstatus == 1 and (
		request.status == "Funds Issued" or (request.status == "Approved" and not flt(request.funds_required))
	)


@frappe.whitelist()
def get_facility_headroom(bank_facility: str, request: str | None = None) -> dict:
	frappe.has_permission("Bid Security Request", "read", throw=True)
	return facility_headroom(bank_facility, request)


def facility_headroom(bank_facility, exclude=None) -> dict:
	"""A facility's limit, the securities running on it, those of approved requests not yet issued
	(other than the excluded request), and what is left."""
	limit, closed = frappe.db.get_value("Bank Facility", bank_facility, ["limit_amount", "disabled"])
	in_use = get_utilised(bank_facility)
	reserved = flt(
		frappe.db.sql(
			"""select sum(line.amount) from `tabBid Security Line` line
			inner join `tabBid Security Request` request on request.name = line.parent
			where request.docstatus = 1 and request.bank_facility = %s and request.name != %s
				and ifnull(line.bank_instrument, '') = ''""",
			(bank_facility, exclude or ""),
		)[0][0]
	)
	return {"limit": flt(limit), "in_use": in_use, "reserved": reserved, "available": flt(limit) - in_use - reserved, "closed": closed}


@frappe.whitelist()
def make_bank_instrument(source_name: str):
	"""The next security of the request as issued by the bank or insurer, recorded by Finance. Its
	quarterly fee is its share of the recurring expenses."""
	request = frappe.get_doc("Bid Security Request", source_name)
	request.check_permission("read")
	if not ready_to_record(request):
		frappe.throw(_("A security is recorded once the request is approved and its funds are issued."))
	line = next((r for r in request.securities if not r.bank_instrument), None)
	if not line:
		frappe.throw(_("Every security on {0} is already recorded as issued.").format(request.name))
	per_quarter = sum(flt(r.amount) * PER_YEAR.get(r.frequency, 4) / 4 for r in request.expenses if r.recurring)
	share = flt(line.amount) / flt(request.amount) if flt(request.amount) else 1
	doc = frappe.new_doc("Bank Instrument")
	doc.update(
		{
			"title": _("Bid security: {0}").format(" - ".join(filter(None, (request.organisation, line.description)))),
			"instrument_type": "Bid Security",
			"opportunity": request.opportunity,
			"bid_security_request": request.name,
			"bank_facility": request.bank_facility,
			"company": request.company,
			"beneficiary": request.beneficiary,
			"amount": line.amount,
			"issue_date": today(),
			"expiry_date": line.valid_until,
			"quarterly_fee": per_quarter * share,
		}
	)
	return doc
