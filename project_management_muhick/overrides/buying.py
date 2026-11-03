# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Purchase Order, Purchase Receipt and Purchase Invoice hooks.

An approved Purchase Order is a commitment: it reduces the available project budget at once,
before anything is paid.
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt

from project_management_muhick.muhick_controls import matching, sod
from project_management_muhick.muhick_finance.doctype.payment_plan.payment_plan import paid_on_account
from project_management_muhick.muhick_projects import budget_engine
from project_management_muhick.overrides import stock as stock_api
from project_management_muhick.overrides import supplier as supplier_api
from project_management_muhick.utils import calc
from project_management_muhick.utils.approval import get_route
from project_management_muhick.utils.common import (
	FM, FO, PRO, administration_order, administration_purchase, get_settings, notify_roles,
)

OVER_BUDGET = ("Exceeds Budget", "Not Budgeted")


def _projects(doc) -> set:
	return {row.project for row in doc.items if row.project} | ({doc.project} if doc.get("project") else set())


def _fill_cost_codes(doc, source_doctype=None, source_field=None):
	"""Carry the cost code from the source row; fall back to the item's budgeted cost code."""
	for row in doc.items:
		if row.get("muhick_cost_code") or not row.project:
			continue
		source = row.get(source_field) if source_field else None
		if source:
			row.muhick_cost_code = frappe.db.get_value(source_doctype, source, "muhick_cost_code")
		if not row.get("muhick_cost_code") and row.item_code:
			row.muhick_cost_code = budget_engine.get_budget_cost_code(row.project, row.item_code)


def _amounts_by_project(doc) -> dict:
	amounts = defaultdict(lambda: defaultdict(float))
	for row in doc.items:
		project = row.project or doc.get("project")
		if project:
			amounts[project][row.get("muhick_cost_code") or ""] += flt(row.base_net_amount)
	return amounts


def _approved_overrun(doc) -> dict:
	"""Value of the order's lines that come from a Material Request already approved over budget."""
	allowance = defaultdict(lambda: defaultdict(float))
	mr_rows = [row.material_request_item for row in doc.items if row.get("material_request_item")]
	if not mr_rows:
		return allowance
	rows = frappe.db.sql(
		"""
		select mri.name, mri.amount, mri.project, ifnull(mri.muhick_cost_code, '') as cost_code
		from `tabMaterial Request Item` mri
		inner join `tabMaterial Request` mr on mr.name = mri.parent
		where mri.name in %(rows)s and mr.docstatus = 1 and mr.muhick_budget_status in %(over)s
		""",
		{"rows": tuple(mr_rows), "over": OVER_BUDGET},
		as_dict=True,
	)
	for r in rows:
		if r.project:
			allowance[r.project][r.cost_code] += flt(r.amount)
	return allowance


def _check_budget(doc, enforce=False) -> bool:
	"""Whether the document is over budget on any project."""
	over_budget = False
	allowance = _approved_overrun(doc) if doc.doctype == "Purchase Order" else {}
	for project, amounts in _amounts_by_project(doc).items():
		status, remarks = budget_engine.evaluate(project, amounts, allowance=allowance.get(project))
		rows = [
			(row.item_code, budget_engine.row_stock_qty(row), row.get("material_request_item"))
			for row in doc.items
			if row.item_code and (row.project or doc.get("project")) == project
		]
		status, remarks = budget_engine.with_quantities(project, status, remarks, budget_engine.beyond_requests(rows))
		if status not in OVER_BUDGET:
			continue
		over_budget = True
		if enforce:
			budget_engine.enforce(doc, "budget_action_on_purchase_order", status, f"{project}: {remarks}")
		else:
			frappe.msgprint(
				_("{0}: {1}. {2}").format(project, _(status), remarks), title=_("Budget Check"), indicator="orange"
			)
	return over_budget


# ------------------------------------------------------------------ Purchase Order
def validate_supplier_quotation(doc, method=None):
	"""A quotation for one project carries it on its header, where the project's connections read it."""
	projects = _projects(doc)
	if not doc.get("project") and len(projects) == 1:
		doc.project = projects.pop()
	doc.muhick_administration = administration_purchase(doc.items)


def validate_purchase_order(doc, method=None):
	_fill_cost_codes(doc, "Material Request Item", "material_request_item")
	doc.muhick_administration = administration_purchase(doc.items)
	if doc.get("muhick_procurement_requisition"):
		doc.muhick_procurement_type = frappe.db.get_value(
			"Procurement Requisition", doc.muhick_procurement_requisition, "procurement_type"
		)
	# checks only stop the order once it is sent for approval, so a draft can always be saved
	enforce = doc.docstatus == 1 or doc.get("workflow_state") not in (None, "", "Draft", "Rejected")
	if doc.docstatus == 0:
		_set_route(doc, _check_budget(doc))
	_check_requisition(doc, enforce)
	supplier_api.check_purchase_order(doc, enforce)
	if doc.docstatus == 0 and doc.get("muhick_procurement_requisition"):
		doc.muhick_paid_on_requisition = paid_on_account(doc.muhick_procurement_requisition, doc.supplier)


def _set_route(doc, over_budget):
	"""Who approves follows the value and the requisition's risk. With no requisition, an order from approved
	requests is of medium risk and one with nothing approved behind it high. What is over budget takes the
	full route."""
	requisition = doc.get("muhick_procurement_requisition")
	doc.muhick_risk_class = (requisition and frappe.db.get_value("Procurement Requisition", requisition, "risk_class")) or (
		"Medium" if all(row.get("material_request_item") for row in doc.items) else "High"
	)
	doc.muhick_approval_route = calc.FULL_ROUTE if over_budget else get_route(doc.doctype, doc.base_net_total, doc.muhick_risk_class)


def _check_requisition(doc, enforce):
	"""An order is raised from an approved Procurement Requisition: for a supplier on it, and for no more than was
	approved for that supplier and not yet ordered. Orders loaded at go-live have been through approval already."""
	action = get_settings().require_procurement_requisition or "Block"
	if action == "Off" or frappe.flags.in_import:
		return
	requisition = doc.get("muhick_procurement_requisition")
	if requisition:
		if frappe.db.get_value("Procurement Requisition", requisition, "docstatus") != 1:
			frappe.throw(_("Procurement Requisition {0} is not approved.").format(requisition))
		lines = frappe.get_all(
			"Procurement Requisition Item",
			filters={"parent": requisition, "parenttype": "Procurement Requisition", "supplier": doc.supplier},
			fields=["currency", "amount", "base_amount", "purchase_order"],
		)
		if not lines:
			frappe.throw(_("Procurement Requisition {0} has nothing approved for supplier {1}.").format(requisition, doc.supplier))
		# in the quotation's own currency, so a change in the exchange rate does not trip it
		same_currency = [line for line in lines if line.currency == doc.currency]
		considered = same_currency or lines
		still_open = [line for line in considered if not line.purchase_order or line.purchase_order == doc.name]
		if not still_open:
			frappe.throw(
				_("Procurement Requisition {0} is already ordered from {1} on {2}.").format(
					requisition, doc.supplier, ", ".join(sorted({line.purchase_order for line in considered}))
				)
			)
		ordered = doc.net_total if same_currency else doc.base_net_total
		limit = sum(flt(line.amount if same_currency else line.base_amount) for line in still_open)
		if flt(ordered) > limit + 0.5:
			frappe.throw(
				_("The order ({0}) is more than the approved requisition ({1}). Amend the requisition first.").format(
					frappe.format_value(ordered, "Currency"), frappe.format_value(limit, "Currency")
				)
			)
		return
	message = _("This order has no approved Procurement Requisition.")
	if action == "Block" and enforce:
		frappe.throw(message, title=_("Procurement Requisition Required"))
	if doc.docstatus == 0:
		frappe.msgprint(message, indicator="orange", alert=True)


def before_submit_purchase_order(doc, method=None):
	_check_budget(doc, enforce=True)


def _mark_requisition(doc, cancelled=False):
	"""The requisition's lines on this order are ordered, or no longer once it is cancelled; its status follows."""
	requisition = doc.get("muhick_procurement_requisition")
	if not requisition:
		return
	table = {"parent": requisition, "parenttype": "Procurement Requisition"}
	on_order = {row.get("supplier_quotation_item") for row in doc.items}
	for line in frappe.get_all(
		"Procurement Requisition Item",
		filters={**table, "supplier": doc.supplier},
		fields=["name", "supplier_quotation_item", "purchase_order"],
	):
		if cancelled and line.purchase_order == doc.name:
			frappe.db.set_value("Procurement Requisition Item", line.name, "purchase_order", None)
		elif not cancelled and not line.purchase_order and line.supplier_quotation_item in on_order:
			frappe.db.set_value("Procurement Requisition Item", line.name, "purchase_order", doc.name)
	orders = frappe.get_all("Procurement Requisition Item", filters=table, pluck="purchase_order")
	status = "Ordered" if all(orders) else "Partly Ordered" if any(orders) else "Approved"
	frappe.db.set_value("Procurement Requisition", requisition, "status", status)


def on_submit_purchase_order(doc, method=None):
	_mark_requisition(doc)
	if doc.get("muhick_payment_type") == "Advance" and not flt(doc.get("muhick_paid_on_requisition")):
		# the payment terms call for an advance: the officer raises the payment request
		notify_roles(
			PRO,
			_("{0} is approved and needs an advance payment of {1}%. Raise the Payment Request.").format(
				doc.name, f"{flt(doc.get('muhick_advance_percent')):g}"
			),
			doc=doc,
			extra_users=[doc.owner],
		)
	if doc.get("muhick_payment_type") == "Letter of Credit":
		# Finance applies to the bank, and the supplier confirms it before anything is shipped
		notify_roles(
			[FM, FO],
			_("{0} is approved and is to be paid by letter of credit to {1}. Apply to the bank, then record it from Create on the order.").format(
				doc.name, doc.supplier_name or doc.supplier
			),
			doc=doc,
		)
	_send_to_supplier(doc)
	refresh_budgets(doc)


def _send_to_supplier(doc):
	"""The approved order goes to the supplier by email with the order attached. With no address, or no outgoing email, it
	is left to the officer to print: an email that fails must not stop the approval. Orders loaded at go-live were sent long
	ago."""
	if frappe.flags.in_import or (get_settings().get("approved_order_to_supplier") or "Email") != "Email":
		return
	from frappe.core.doctype.communication.email import _make

	supplier = doc.supplier_name or doc.supplier
	email = doc.get("contact_email") or frappe.db.get_value("Supplier", doc.supplier, "email_id")
	if not email:
		notify_roles(
			PRO, _("{0} is approved but {1} has no email address. Print the order and send it.").format(doc.name, supplier),
			doc=doc, extra_users=[doc.owner],
		)
		return
	frappe.db.savepoint("email_order")
	try:
		_make(
			doctype=doc.doctype,
			name=doc.name,
			subject=_("Purchase Order {0}").format(doc.name),
			content=_("Dear {0},<br><br>Please find attached our purchase order {1}. Please confirm that you have received it.").format(
				supplier, doc.name
			),
			recipients=email,
			send_email=True,
			print_format=frappe.get_meta(doc.doctype).default_print_format or "Standard",
		)
	except Exception:
		frappe.db.rollback(save_point="email_order")
		frappe.log_error(title=f"Muhick: could not email order {doc.name}")
		notify_roles(
			PRO, _("{0} is approved but could not be emailed to {1}. Print the order and send it.").format(doc.name, supplier),
			doc=doc, extra_users=[doc.owner],
		)


def on_cancel_purchase_order(doc, method=None):
	_mark_requisition(doc, cancelled=True)
	refresh_budgets(doc)


def refresh_budgets(doc, method=None):
	budget_engine.refresh_projects(_projects(doc))


# ------------------------------------------------------------------ Purchase Receipt
def validate_purchase_receipt(doc, method=None):
	_fill_cost_codes(doc, "Purchase Order Item", "purchase_order_item")
	doc.muhick_administration = administration_order(doc.items)
	stock_api.refuse_client_store(doc)
	sod.check_purchase_receipt(doc)


# ------------------------------------------------------------------ Purchase Invoice
def before_validate_purchase_invoice(doc, method=None):
	"""What was paid ahead of a new invoice, on its order or on the requisition behind it, comes off what it owes:
	ERPNext takes the advances up when this is ticked, and it can still be unticked."""
	orders = {row.get("purchase_order") for row in doc.items if row.get("purchase_order")}
	if not doc.is_new() or doc.get("is_return") or not orders:
		return
	paid = frappe.get_all("Purchase Order", filters={"name": ("in", list(orders))}, fields=["advance_paid", "muhick_paid_on_requisition"])
	if any(flt(order.advance_paid) or flt(order.muhick_paid_on_requisition) for order in paid):
		doc.allocate_advances_automatically = 1


def validate_purchase_invoice(doc, method=None):
	_fill_cost_codes(doc, "Purchase Order Item", "po_detail")
	_validate_subcontract_invoice(doc)
	matching.apply(doc)
	sod.check_purchase_invoice(doc)


def before_submit_purchase_invoice(doc, method=None):
	# an invoice with no purchase order commits the budget itself
	direct = defaultdict(lambda: defaultdict(float))
	quantities = defaultdict(lambda: defaultdict(float))
	if not doc.get("muhick_subcontract_agreement") and not doc.is_return:
		for row in doc.items:
			project = row.project or doc.get("project")
			if project and not row.purchase_order:
				direct[project][row.get("muhick_cost_code") or ""] += flt(row.base_net_amount)
				if row.item_code:
					quantities[project][row.item_code] += budget_engine.row_stock_qty(row)
	for project, amounts in direct.items():
		status, remarks = budget_engine.evaluate(project, amounts)
		status, remarks = budget_engine.with_quantities(project, status, remarks, quantities[project])
		budget_engine.enforce(doc, "budget_action_on_purchase_order", status, f"{project}: {remarks}")


def _validate_subcontract_invoice(doc):
	"""Finance may only invoice a subcontractor against a submitted Service Receipt Note."""
	agreement = doc.get("muhick_subcontract_agreement")
	if not agreement:
		return
	srn = doc.get("muhick_service_receipt_note")
	if not srn:
		frappe.throw(_("Select the Service Receipt Note this subcontract invoice is raised against."))
	note = frappe.db.get_value(
		"Service Receipt Note", srn, ["docstatus", "subcontract_agreement", "purchase_invoice", "gross_amount"], as_dict=True
	)
	if not note or note.docstatus != 1 or note.subcontract_agreement != agreement:
		frappe.throw(_("Service Receipt Note {0} is not a submitted note of agreement {1}.").format(srn, agreement))
	if note.purchase_invoice and note.purchase_invoice != doc.name:
		frappe.throw(_("Service Receipt Note {0} is already invoiced on {1}.").format(srn, note.purchase_invoice))
	if flt(doc.base_net_total) > flt(note.gross_amount) + 0.5:
		frappe.throw(
			_("The invoice ({0}) is more than the amount certified on {1} ({2}).").format(
				frappe.format_value(doc.base_net_total, "Currency"), srn, frappe.format_value(note.gross_amount, "Currency")
			)
		)


def on_submit_purchase_invoice(doc, method=None):
	if doc.get("muhick_service_receipt_note"):
		frappe.db.set_value(
			"Service Receipt Note", doc.muhick_service_receipt_note, {"purchase_invoice": doc.name, "status": "Invoiced"}
		)
	if administration_order(doc.items):
		notify_roles([FM, FO], _("{0} for an administration purchase is posted and waiting to be paid.").format(doc.name), doc=doc)
	refresh_budgets(doc)


def on_cancel_purchase_invoice(doc, method=None):
	if doc.get("muhick_service_receipt_note"):
		frappe.db.set_value(
			"Service Receipt Note", doc.muhick_service_receipt_note, {"purchase_invoice": None, "status": "Submitted"}
		)
	refresh_budgets(doc)


@frappe.whitelist()
def make_site_transfer(source_name: str):
	"""A delivery note for goods going on to site, raised from the approved Purchase Order.
	It opens as a draft stock transfer so quantities can be adjusted to what is actually sent."""
	order = frappe.get_doc("Purchase Order", source_name)
	order.check_permission("read")
	if order.docstatus != 1:
		frappe.throw(_("The Purchase Order must be approved first."))
	transfer = frappe.new_doc("Stock Entry")
	transfer.update(
		{
			"stock_entry_type": "Material Transfer",
			"purpose": "Material Transfer",
			"company": order.company,
			"project": order.project,
			# bought on this project's own order, so the transfer is not charged to the budget again
			"muhick_purchase_order": order.name,
		}
	)
	for row in order.items:
		project = row.project or order.project
		site = frappe.db.get_value("Project", project, "muhick_site_warehouse") if project else None
		if not site or site == row.warehouse:
			continue  # no site store, or the goods are received there directly
		transfer.append(
			"items",
			{
				"item_code": row.item_code,
				"qty": flt(row.received_qty) or flt(row.qty),
				"uom": row.uom,
				"s_warehouse": row.warehouse,
				"t_warehouse": site,
				"project": project,
				"muhick_cost_code": row.get("muhick_cost_code"),
			},
		)
	if not transfer.items:
		frappe.throw(_("Nothing to send: these items are received directly at the site store, or their project has no site store."))
	return transfer
