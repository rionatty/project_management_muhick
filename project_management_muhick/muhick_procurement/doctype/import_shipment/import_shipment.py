# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Consignment tracking for an imported purchase order: manufacture, letter of credit,
pre-shipment inspection, shipping, customs clearance, container return and delivery, with the
tax worksheet and other charges. Dates are compared with the plan so a delay shows at once.

The letter of credit is recorded once, with the bank's other instruments, and read from there."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, add_to_date, date_diff, flt, getdate, nowdate

from project_management_muhick.muhick_projects.utils import validate_dates
from project_management_muhick.utils.common import FM, FO, notify_roles

# taxes the company claims back rather than costs: they stay off the cost of the goods
NOT_A_COST = ("VAT", "Withholding Tax")
# who is paid for a charge whose payee is not given: the consignment's own forwarder or agent
PAID_TO = {"Freight": "freight_forwarder", "Clearing Agent Fees": "clearing_agent"}


class ImportShipment(Document):
	def validate(self):
		if self.purchase_order and not self.supplier:
			self.supplier, project = frappe.db.get_value("Purchase Order", self.purchase_order, ["supplier", "project"])
			self.project = self.project or project
		validate_dates(self.planned_departure, self.planned_arrival, _("Planned Departure"), _("Planned Arrival"))
		validate_dates(self.actual_departure, self.actual_arrival, _("Actual Departure"), _("Actual Arrival"))
		self.expected_ready_date = (
			add_days(self.manufacturing_start, int(self.lead_time_days or 0)) if self.manufacturing_start else None
		)
		self.transit_days_planned = self._days(self.planned_departure, self.planned_arrival)
		self.transit_days_actual = self._days(self.actual_departure, self.actual_arrival)
		# customs give 72 hours from the assessment to pay
		self.tax_payment_deadline = add_to_date(self.tax_assessment_on, hours=72) if self.tax_assessment_on else None
		self.total_charges = sum(flt(c.amount) for c in self.charges)
		if self.shipment_status in ("Delivered", "Closed") and not self.delivered_on:
			self.delivered_on = nowdate()
		self.is_delayed = int(self.behind_schedule())
		if self.is_delayed and self.shipment_status not in ("Delivered", "Closed") and not (self.delay_reason or "").strip():
			frappe.msgprint(_("This consignment is behind schedule. Record the reason for the delay."), indicator="orange", alert=True)
		self.set_letter_of_credit()

	def set_letter_of_credit(self):
		if not self.purchase_order:
			return
		values = letter_of_credit_of(self.purchase_order)
		# what was typed here before the letter of credit had a record of its own stays until it has one
		if values["letter_of_credit"] or self.letter_of_credit:
			self.update(values)
		if values["letter_of_credit"] or frappe.db.get_value("Purchase Order", self.purchase_order, "muhick_payment_type") == "Letter of Credit":
			self.lc_required = 1

	def on_update(self):
		if self.commercial_invoice and self.has_value_changed("commercial_invoice"):
			notify_roles(
				[FM, FO],
				_("The commercial invoice for {0} is on {1}. Create the reserve invoice.").format(self.purchase_order, self.name),
				doc=self,
			)

	@staticmethod
	def _days(start, end):
		return date_diff(end, start) if start and end else 0

	def behind_schedule(self) -> bool:
		today = getdate(nowdate())
		if self.expected_ready_date and not self.actual_ready_date and getdate(self.expected_ready_date) < today:
			return True
		if self.planned_arrival and not self.actual_arrival and getdate(self.planned_arrival) < today:
			return True
		arrival = self.actual_arrival or self.planned_arrival
		return bool(self.required_on_site_by and arrival and getdate(arrival) > getdate(self.required_on_site_by))


def letter_of_credit_of(purchase_order) -> dict:
	"""The order's letter of credit as the bank's record has it, for the fields of its consignments."""
	credit = frappe.db.get_value(
		"Bank Instrument",
		{"purchase_order": purchase_order, "instrument_type": "Letter of Credit", "status": ("!=", "Cancelled")},
		["name", "reference_no", "bank_facility", "amount", "issue_date", "expiry_date"],
		as_dict=True,
	) or frappe._dict()
	return {
		"letter_of_credit": credit.name,
		"lc_number": credit.reference_no,
		"lc_bank": frappe.db.get_value("Bank Facility", credit.bank_facility, "bank") if credit.bank_facility else None,
		"lc_amount": credit.amount,
		"lc_issue_date": credit.issue_date,
		"lc_expiry_date": credit.expiry_date,
	}


def refresh_letter_of_credit(purchase_order):
	"""The bank's record changed: the order's consignments read it again."""
	values = letter_of_credit_of(purchase_order)
	for name in frappe.get_all("Import Shipment", filters={"purchase_order": purchase_order}, pluck="name"):
		frappe.db.set_value("Import Shipment", name, {**values, "lc_required": 1}, update_modified=False)


@frappe.whitelist()
def make_reserve_invoice(source_name: str):
	"""The invoice of a consignment's order, already on the consignment and where it is."""
	from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice

	shipment = frappe.get_doc("Import Shipment", source_name)
	shipment.check_permission("read")
	invoice = make_purchase_invoice(shipment.purchase_order)
	invoice.update({"muhick_import_shipment": shipment.name, "muhick_location": shipment.current_location})
	return invoice


@frappe.whitelist()
def make_landed_cost_voucher(source_name: str):
	"""The landed cost of a consignment, as a draft: its charges, spread by value over the goods received on its order,
	each with who is paid for it where the site keeps that on the charge (the stock add-on does, and on submit makes each
	of them an invoice)."""
	shipment = frappe.get_doc("Import Shipment", source_name)
	shipment.check_permission("read")
	existing = frappe.db.get_value("Landed Cost Voucher", {"muhick_import_shipment": shipment.name, "docstatus": ("<", 2)}, "name")
	if existing:
		frappe.throw(_("Landed Cost Voucher {0} already covers this consignment.").format(existing))
	charges = [row for row in shipment.charges if flt(row.amount) and row.charge_type not in NOT_A_COST]
	if not charges:
		frappe.throw(_("This consignment has no charges to add to the cost of the goods."))
	receipts = (
		[shipment.purchase_receipt]
		if shipment.purchase_receipt
		else frappe.get_all(
			"Purchase Receipt Item", filters={"purchase_order": shipment.purchase_order, "docstatus": 1}, pluck="parent", distinct=True
		)
	)
	if not receipts:
		frappe.throw(_("No goods have been received on {0} yet.").format(shipment.purchase_order))

	voucher = frappe.new_doc("Landed Cost Voucher")
	voucher.update({"company": shipment.company, "muhick_import_shipment": shipment.name, "distribute_charges_based_on": "Amount"})
	for name in receipts:
		receipt = frappe.db.get_value("Purchase Receipt", name, ["supplier", "posting_date", "base_grand_total"], as_dict=True)
		voucher.append(
			"purchase_receipts",
			{
				"receipt_document_type": "Purchase Receipt",
				"receipt_document": name,
				"supplier": receipt.supplier,
				"posting_date": receipt.posting_date,
				"grand_total": receipt.base_grand_total,
			},
		)
	voucher.get_items_from_purchase_receipts()
	# left empty for Finance to choose where the chart has none of this type, or several
	accounts = frappe.get_all(
		"Account",
		filters={"company": shipment.company, "account_type": "Expenses Included In Valuation", "is_group": 0, "disabled": 0},
		pluck="name",
	)
	currency = frappe.get_cached_value("Company", shipment.company, "default_currency")
	names_payee = frappe.get_meta("Landed Cost Taxes and Charges").has_field("custom_supplier")
	for row in charges:
		line = {
			"description": f"{_(row.charge_type)}: {row.description}" if row.description else _(row.charge_type),
			"expense_account": accounts[0] if len(accounts) == 1 else None,
			"account_currency": currency,
			"exchange_rate": 1,
			"amount": row.amount,
			"base_amount": row.amount,
			"project": shipment.project,
		}
		if names_payee:
			line["custom_supplier"] = row.payee or shipment.get(PAID_TO.get(row.charge_type, ""))
		voucher.append("taxes", line)
	voucher.set_total_taxes_and_charges()
	return voucher

