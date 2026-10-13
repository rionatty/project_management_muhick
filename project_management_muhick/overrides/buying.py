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
from project_management_muhick.muhick_projects import budget_engine
from project_management_muhick.overrides import supplier as supplier_api
from project_management_muhick.utils.common import PRO, get_settings, notify_roles

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


def _check_budget(doc, enforce=False):
	allowance = _approved_overrun(doc) if doc.doctype == "Purchase Order" else {}
	for project, amounts in _amounts_by_project(doc).items():
		status, remarks = budget_engine.evaluate(project, amounts, allowance=allowance.get(project))
		if status not in OVER_BUDGET:
			continue
		if enforce:
			budget_engine.enforce(doc, "budget_action_on_purchase_order", status, f"{project}: {remarks}")
		else:
			frappe.msgprint(
				_("{0}: {1}. {2}").format(project, _(status), remarks), title=_("Budget Check"), indicator="orange"
			)


# ------------------------------------------------------------------ Purchase Order
def validate_purchase_order(doc, method=None):
	_fill_cost_codes(doc, "Material Request Item", "material_request_item")
	# checks only stop the order once it is sent for approval, so a draft can always be saved
	enforce = doc.docstatus == 1 or doc.get("workflow_state") not in (None, "", "Draft", "Rejected")
	if doc.docstatus == 0:
		_check_budget(doc)
	_check_requisition(doc, enforce)
	supplier_api.check_purchase_order(doc, enforce)


def _check_requisition(doc, enforce):
	"""An order is raised from an approved Procurement Requisition for the same supplier."""
	action = get_settings().require_procurement_requisition or "Warn"
	if action == "Off":
		return
	requisition = doc.get("muhick_procurement_requisition")
	if requisition:
		approved = frappe.db.get_value(
			"Procurement Requisition", requisition, ["docstatus", "supplier", "purchase_order", "total_amount"], as_dict=True
		)
		if not approved or approved.docstatus != 1:
			frappe.throw(_("Procurement Requisition {0} is not approved.").format(requisition))
		if approved.supplier != doc.supplier:
			frappe.throw(_("Procurement Requisition {0} was approved for supplier {1}.").format(requisition, approved.supplier))
		if approved.purchase_order and approved.purchase_order != doc.name:
			frappe.throw(_("Procurement Requisition {0} is already ordered on {1}.").format(requisition, approved.purchase_order))
		if flt(doc.base_net_total) > flt(approved.total_amount) + 0.5:
			frappe.throw(
				_("The order ({0}) is more than the approved requisition ({1}). Amend the requisition first.").format(
					frappe.format_value(doc.base_net_total, "Currency"), frappe.format_value(approved.total_amount, "Currency")
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


def on_submit_purchase_order(doc, method=None):
	requisition = doc.get("muhick_procurement_requisition")
	if requisition:
		frappe.db.set_value("Procurement Requisition", requisition, {"purchase_order": doc.name, "status": "Ordered"})
	if doc.get("muhick_payment_type") == "Advance":
		# the payment terms call for an advance: the officer raises the payment request
		notify_roles(
			PRO,
			_("{0} is approved and needs an advance payment of {1}%. Raise the Payment Request.").format(
				doc.name, f"{flt(doc.get('muhick_advance_percent')):g}"
			),
			doc=doc,
			extra_users=[doc.owner],
		)
	refresh_budgets(doc)


def on_cancel_purchase_order(doc, method=None):
	requisition = doc.get("muhick_procurement_requisition")
	if requisition and frappe.db.get_value("Procurement Requisition", requisition, "purchase_order") == doc.name:
		frappe.db.set_value("Procurement Requisition", requisition, {"purchase_order": None, "status": "Approved"})
	refresh_budgets(doc)


def refresh_budgets(doc, method=None):
	budget_engine.refresh_projects(_projects(doc))


# ------------------------------------------------------------------ Purchase Receipt
def validate_purchase_receipt(doc, method=None):
	_fill_cost_codes(doc, "Purchase Order Item", "purchase_order_item")


# ------------------------------------------------------------------ Purchase Invoice
def validate_purchase_invoice(doc, method=None):
	_fill_cost_codes(doc, "Purchase Order Item", "po_detail")
	_validate_subcontract_invoice(doc)
	matching.apply(doc)
	sod.check_purchase_invoice(doc)


def before_submit_purchase_invoice(doc, method=None):
	# an invoice with no purchase order commits the budget itself
	direct = defaultdict(lambda: defaultdict(float))
	if not doc.get("muhick_subcontract_agreement") and not doc.is_return:
		for row in doc.items:
			project = row.project or doc.get("project")
			if project and not row.purchase_order:
				direct[project][row.get("muhick_cost_code") or ""] += flt(row.base_net_amount)
	for project, amounts in direct.items():
		status, remarks = budget_engine.evaluate(project, amounts)
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
