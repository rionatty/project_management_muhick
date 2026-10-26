# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""The outcome of a bid, won or lost, reported by the sales engineer and approved by the Head of
Sales, then the General Manager. Only the approved outcome marks the opportunity won or lost, and
cancelling it reopens the bid.

For a won bid the report reviews the margin: the BOQ priced at the suppliers' latest quotations for
the bid (the lowest to begin with; a line can take another of them, and a line no supplier has quoted
takes the last purchase price or an estimate), less what was spent winning the bid, which the project
carries once it starts. For a lost bid it gives the reasons, the competitors and who won it, at what
price."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, strip_html_tags

from project_management_muhick.muhick_projects.utils import draft_status, leaving_draft
from project_management_muhick.muhick_sales.bids import (
	bid_spent, boq_factor, boq_quotes, last_purchase_rate, latest_by_supplier, lowest,
)
from project_management_muhick.overrides.crm import is_submitted, refresh_bid_status
from project_management_muhick.utils import calc
from project_management_muhick.utils.common import COO, FINANCE_ROLES, FM, notify_roles


class BidOutcome(Document):
	def validate(self):
		if not self.prepared_by:
			self.prepared_by = frappe.session.user
		bid = frappe.get_doc("Opportunity", self.opportunity)
		self.check_bid(bid)
		self.prepare(bid)
		if self.docstatus == 0:
			self.status = draft_status(self)
		if self.has_value_changed("workflow_state") and self.workflow_state == "Rejected" and not (self.rejection_reason or "").strip():
			frappe.throw(_("Give the reason for returning the outcome report."))
		if leaving_draft(self):
			self.check_complete()

	def check_bid(self, bid):
		if bid.status in ("Lost", "Closed") and self.docstatus == 0:
			frappe.throw(_("Bid {0} is {1}. Reopen it before reporting its outcome.").format(bid.name, _(bid.status).lower()))
		if not is_submitted(bid):
			frappe.throw(
				_("Bid {0} has no recorded submission. Record its submission, with the acknowledgement, before its outcome.").format(bid.name)
			)
		raised = frappe.db.get_value(
			"Bid Outcome", {"opportunity": self.opportunity, "docstatus": ("<", 2), "name": ("!=", self.name or "")}, "name"
		)
		if raised:
			frappe.throw(_("Outcome report {0} is already raised for this bid.").format(raised))

	def prepare(self, bid):
		"""The bid's figures and, for a won bid, its BOQ at the suppliers' prices (loaded the first time)."""
		self.take_from_bid(bid)
		if self.outcome == "Won":
			if not self.lines:
				self.load_lines(bid)
			self.price_lines()
		else:
			self.set("lines", [])
		self.set_totals()

	def take_from_bid(self, bid):
		"""The bid's price, estimate and margin and what was spent on it, in the company currency."""
		rate = flt(bid.conversion_rate) or 1
		self.organisation, self.company = bid.customer_name, bid.company
		self.bid_price = flt(bid.base_opportunity_amount) or flt(bid.opportunity_amount) * rate
		self.estimated_cost = flt(bid.get("muhick_estimated_cost")) * rate
		self.margin_at_bid = flt(bid.get("muhick_margin_percent"))
		self.bid_costs = bid_spent([bid.name]).get(bid.name, 0)

	def load_lines(self, bid):
		"""The bid's BOQ, each line at the lowest valid quotation, or else the last purchase price."""
		quotes = boq_quotes(bid.name)
		for item in bid.get("items") or []:
			best = lowest(list(latest_by_supplier(quotes.get(item.item_code, [])).values()))
			self.append(
				"lines",
				{
					"item_code": item.item_code,
					"item_name": item.item_name,
					"stage": item.get("muhick_stage"),
					"qty": item.qty,
					"uom": item.uom,
					"bid_rate": item.base_rate,
					"bid_amount": item.base_amount,
					"supplier_quotation": best.supplier_quotation if best else None,
					"cost_rate": 0 if best else last_purchase_rate(item.item_code) * boq_factor(item.item_code, item.uom),
				},
			)

	@frappe.whitelist()
	def refresh_prices(self):
		"""The BOQ again, at today's lowest quotations."""
		if self.docstatus != 0:
			frappe.throw(_("Prices are refreshed only before the outcome is approved."))
		self.set("lines", [])
		self.save()

	def price_lines(self):
		"""Each line at its chosen quotation; a line without one keeps the cost rate entered."""
		quotes = boq_quotes(self.opportunity)
		for line in self.lines:
			offers = quotes.get(line.item_code, [])
			line.quotes = len(latest_by_supplier(offers))
			if line.supplier_quotation:
				quote = next((q for q in offers if q.supplier_quotation == line.supplier_quotation), None)
				if not quote:
					frappe.throw(
						_("BOQ row {0}: supplier quotation {1} is not one of this bid's quotations for {2}.").format(
							line.idx, line.supplier_quotation, line.item_code
						)
					)
				line.supplier, line.valid_till = quote.supplier, quote.valid_till
				line.cost_rate = quote.stock_rate * boq_factor(line.item_code, line.uom)
			else:
				line.supplier = line.valid_till = None
			line.cost_amount = flt(line.qty) * flt(line.cost_rate)
			line.margin = flt(line.bid_amount) - line.cost_amount
			line.margin_percent = calc.margin_percent(line.bid_amount, line.cost_amount)

	def set_totals(self):
		won = self.outcome == "Won"
		self.cost_of_works = sum(flt(line.cost_amount) for line in self.lines)
		self.total_cost = self.cost_of_works + flt(self.bid_costs) if won else 0
		self.gross_profit = flt(self.bid_price) - self.total_cost if won else 0
		self.gross_margin = calc.margin_percent(self.bid_price, self.total_cost) if won else 0
		self.lines_without_quotation = sum(1 for line in self.lines if not line.supplier_quotation)
		self.price_gap = 0 if won else calc.price_gap_percent(self.bid_price, self.winning_price)

	def check_complete(self):
		if not strip_html_tags(self.explanation or "").strip():
			frappe.throw(_("Write the outcome report: why the bid was won or lost, and the lessons."))
		if self.outcome == "Lost":
			if not self.lost_reasons:
				frappe.throw(_("Give the reasons the bid was lost."))
			return
		if not self.notice:
			frappe.throw(_("Attach the best evaluated bidder notice."))
		if not self.lines:
			frappe.throw(_("Opportunity {0} has no BOQ. Add its BOQ lines to review the margin.").format(self.opportunity))
		unpriced = [str(line.idx) for line in self.lines if flt(line.cost_rate) <= 0]
		if unpriced:
			frappe.throw(
				_("BOQ rows {0} have no cost. Choose a supplier quotation, or enter the estimated cost rate.").format(", ".join(unpriced))
			)

	def before_submit(self):
		self.status = "Approved"

	def on_update(self):
		# sent for approval, passed on or returned: the bid's status follows
		if self.docstatus == 0:
			refresh_bid_status(self.opportunity)

	def on_submit(self):
		bid = frappe.get_doc("Opportunity", self.opportunity)
		report = strip_html_tags(self.explanation or "").strip()
		bid.update(
			{
				"muhick_bid_outcome": self.name,
				"muhick_outcome_date": self.outcome_date,
				"muhick_award_notice": self.notice,
				"muhick_outcome_notes": report,
			}
		)
		bid.status = self.outcome
		if self.outcome == "Lost":
			bid.order_lost_reason = report
			bid.set("lost_reasons", [{"lost_reason": r.lost_reason} for r in self.lost_reasons])
			bid.set("competitors", [{"competitor": r.competitor} for r in self.competitors])
		self.save_bid(bid)
		if self.outcome == "Won":
			notify_roles(
				[COO, FM],
				_("Bid {0} ({1}) was won, at a gross profit margin of {2}% on today's supplier prices. The {3} spent winning it goes to the project's cost.").format(
					self.opportunity,
					self.organisation,
					flt(self.gross_margin, 1),
					frappe.format_value(self.bid_costs, "Currency"),
				),
				doc=self,
			)

	def on_cancel(self):
		bid = frappe.get_doc("Opportunity", self.opportunity)
		if self.outcome == "Won":
			quotation = frappe.db.get_value("Quotation Item", {"prevdoc_docname": bid.name, "docstatus": 1}, "parent") or frappe.db.get_value(
				"Quotation", {"opportunity": bid.name, "docstatus": 1}, "name"
			)
			if quotation:
				frappe.throw(_("Quotation {0} was made from this bid. Cancel it before cancelling the outcome.").format(quotation))
		bid.update({"muhick_bid_outcome": None, "muhick_outcome_date": None, "muhick_award_notice": None, "muhick_outcome_notes": None})
		if bid.status == self.outcome:
			bid.status = "Open"
		if self.outcome == "Lost":
			bid.order_lost_reason = None
			bid.set("lost_reasons", [])
			bid.set("competitors", [])
			self.withdraw_security_cancellation()
		self.save_bid(bid)
		self.db_set("status", "Cancelled")

	def save_bid(self, bid):
		bid.flags.muhick_outcome = self.name
		bid.flags.ignore_mandatory = True
		bid.save(ignore_permissions=True)

	def withdraw_security_cancellation(self):
		"""The loss is withdrawn: a bid security put up for cancellation and not yet cancelled runs on."""
		for name in frappe.get_all(
			"Bank Instrument",
			filters={"opportunity": self.opportunity, "instrument_type": "Bid Security", "status": "Cancellation Requested"},
			pluck="name",
		):
			frappe.db.set_value("Bank Instrument", name, {"status": "Active", "closing_reason": None})
			notify_roles(
				FINANCE_ROLES,
				_("Bid security {0} is no longer to be cancelled: the loss of bid {1} was withdrawn.").format(name, self.opportunity),
				doc=frappe._dict(doctype="Bank Instrument", name=name),
			)


@frappe.whitelist()
def get_quote_price(opportunity: str, supplier_quotation: str, item_code: str, uom: str | None = None) -> dict:
	"""A BOQ line's cost at one of the bid's quotations, for the form to show before it is saved."""
	frappe.has_permission("Opportunity", "read", opportunity, throw=True)
	quote = next((q for q in boq_quotes(opportunity).get(item_code, []) if q.supplier_quotation == supplier_quotation), None)
	if not quote:
		frappe.throw(_("Supplier quotation {0} is not one of this bid's quotations for {1}.").format(supplier_quotation, item_code))
	return {"cost_rate": quote.stock_rate * boq_factor(item_code, uom), "supplier": quote.supplier, "valid_till": quote.valid_till}
