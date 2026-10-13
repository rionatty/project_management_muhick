# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Payment Entry, Sales Invoice and Sales Order hooks."""

import frappe
from frappe import _
from frappe.utils import flt

from project_management_muhick.muhick_controls import matching, sod
from project_management_muhick.muhick_projects import budget_engine
from project_management_muhick.muhick_finance.doctype.payment_plan import payment_plan
from project_management_muhick.muhick_finance.doctype.reimbursement_claim import reimbursement_claim
from project_management_muhick.utils.common import FINANCE_ROLES, PM, get_settings, notify_roles


# ------------------------------------------------------------------ Payment Entry
def validate_payment_entry(doc, method=None):
	for ref in doc.get("references") or []:
		if ref.reference_doctype == "Purchase Invoice" and matching.is_blocked(ref.reference_name):
			frappe.throw(
				_("Supplier invoice {0} has an unresolved three-way match exception and cannot be paid.").format(ref.reference_name),
				title=_("Payment Blocked"),
			)
	sod.check_payment_entry(doc)
	_check_payment_plan(doc)


def after_payment(doc, method=None):
	"""on_submit / on_cancel: refresh the paid figures, the payment plan and the claim status."""
	payment_plan.on_payment(doc, cancelled=doc.docstatus == 2)
	invoices = [r.reference_name for r in doc.get("references") or [] if r.reference_doctype == "Purchase Invoice"]
	orders = [r.reference_name for r in doc.get("references") or [] if r.reference_doctype == "Purchase Order"]
	projects = set()
	if invoices:
		projects.update(
			frappe.get_all("Purchase Invoice Item", filters={"parent": ("in", invoices)}, pluck="project", distinct=True)
		)
	if orders:
		projects.update(
			frappe.get_all("Purchase Order Item", filters={"parent": ("in", orders)}, pluck="project", distinct=True)
		)
	budget_engine.refresh_projects(projects)

	for ref in doc.get("references") or []:
		if ref.reference_doctype == "Sales Invoice":
			_sync_claim_payment(ref.reference_name)


def _sync_claim_payment(sales_invoice):
	claim = frappe.db.get_value("Sales Invoice", sales_invoice, "muhick_project_claim")
	if not claim:
		return
	si = frappe.db.get_value("Sales Invoice", sales_invoice, ["docstatus", "outstanding_amount"], as_dict=True)
	if si.docstatus != 1:
		return
	status = "Paid" if flt(si.outstanding_amount) <= 0.005 else "Invoiced"
	if frappe.db.get_value("Project Claim", claim, "status") in ("Invoiced", "Paid"):
		frappe.db.set_value("Project Claim", claim, "status", status)


# ------------------------------------------------------------------ Sales Invoice
def on_submit_sales_invoice(doc, method=None):
	claim = doc.get("muhick_project_claim")
	if claim:
		current = frappe.db.get_value("Project Claim", claim, ["status", "sales_invoice", "docstatus"], as_dict=True)
		if not current or current.docstatus != 1 or current.status not in ("Certified", "Invoiced"):
			frappe.throw(_("Project Claim {0} must be certified by the client before it is invoiced.").format(claim))
		if current.sales_invoice and current.sales_invoice != doc.name:
			frappe.throw(_("Project Claim {0} is already invoiced on {1}.").format(claim, current.sales_invoice))
		frappe.db.set_value("Project Claim", claim, {"status": "Invoiced", "sales_invoice": doc.name})
	if doc.get("muhick_retention_release"):
		frappe.db.set_value("Retention Release", doc.muhick_retention_release, "sales_invoice", doc.name)


def on_cancel_sales_invoice(doc, method=None):
	claim = doc.get("muhick_project_claim")
	if claim and frappe.db.get_value("Project Claim", claim, "sales_invoice") == doc.name:
		frappe.db.set_value("Project Claim", claim, {"status": "Certified", "sales_invoice": None})
	release = doc.get("muhick_retention_release")
	if release and frappe.db.get_value("Retention Release", release, "sales_invoice") == doc.name:
		frappe.db.set_value("Retention Release", release, "sales_invoice", None)


# ------------------------------------------------------------------ Sales Order
def on_submit_sales_order(doc, method=None):
	"""A project-based Sales Order notifies the Project Manager."""
	if doc.get("muhick_sale_type") in ("Project", "Additions"):
		notify_roles(
			PM,
			_("Sales Order {0} ({1}) is confirmed for {2}. The sales handover can start.").format(
				doc.name, _(doc.muhick_sale_type), doc.customer_name or doc.customer
			),
			doc=doc,
		)


def _check_payment_plan(doc):
	"""A supplier payment should come from an approved payment plan, for no more than the plan allows."""
	action = get_settings().payment_plan_control or "Warn"
	if action == "Off" or doc.payment_type != "Pay" or doc.party_type != "Supplier":
		return
	approved = payment_plan.approved_amount_for(doc)
	if approved is None:
		message = _("This supplier payment is not on an approved Payment Plan.")
		if action == "Block" and doc.docstatus == 1:
			frappe.throw(message, title=_("Payment Plan Required"))
		if doc.docstatus == 0:
			frappe.msgprint(message, indicator="orange", alert=True)
		return
	if flt(doc.paid_amount) > approved + 0.5:
		frappe.throw(
			_("The payment ({0}) is more than the amount approved on the payment plan ({1}).").format(
				frappe.format_value(doc.paid_amount, "Currency"), frappe.format_value(approved, "Currency")
			)
		)


# ------------------------------------------------------------------ Payment Request
def on_submit_payment_request(doc, method=None):
	"""A payment request from a department goes to Finance for the next payment plan."""
	if doc.payment_request_type == "Outward":
		notify_roles(
			FINANCE_ROLES,
			_("Payment request {0} for {1} {2} is waiting to be planned for payment.").format(
				doc.name, _(doc.reference_doctype), doc.reference_name
			),
			doc=doc,
		)


# ------------------------------------------------------------------ Journal Entry
def on_submit_journal_entry(doc, method=None):
	reimbursement_claim.on_refund(doc)


def on_cancel_journal_entry(doc, method=None):
	reimbursement_claim.on_refund(doc, cancelled=True)
