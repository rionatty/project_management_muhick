# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Procurement Requisition: raised once the supplier is selected, carrying the chosen supplier,
itemised prices, payment and delivery terms. Approved COO -> Finance Manager -> General Manager,
and only then is the Purchase Order raised from it.

Prices are compared with the project budget line by line and any variance is flagged. Prices or
quantities may still be corrected while it is under approval: the change needs a written summary,
is logged, and Finance is told; the approval does not start again.
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, now_datetime, nowdate

from project_management_muhick.muhick_projects import budget_engine
from project_management_muhick.muhick_projects.utils import draft_status
from project_management_muhick.overrides.buying import _approved_overrun
from project_management_muhick.utils.common import COO, FINANCE_ROLES, notify_roles

BEING_PREPARED = (None, "", "Draft", "Rejected")
RANK = {"Not Applicable": 0, "Within Budget": 1, "Exceeds Budget": 2, "Not Budgeted": 3}


class ProcurementRequisition(Document):
	def validate(self):
		self.set_supplier()
		self.set_item_values()
		self.set_budget_status()
		self.status = draft_status(self)
		self.log_change()

	def set_supplier(self):
		quotation = frappe.db.get_value(
			"Supplier Quotation", self.supplier_quotation, ["docstatus", "supplier", "supplier_name"], as_dict=True
		)
		if not quotation or quotation.docstatus != 1:
			frappe.throw(
				_("Supplier Quotation {0} has not been approved. The supplier selection must be approved first.").format(
					self.supplier_quotation
				)
			)
		self.supplier, self.supplier_name = quotation.supplier, quotation.supplier_name
		other = frappe.db.get_value(
			"Procurement Requisition",
			{"supplier_quotation": self.supplier_quotation, "docstatus": ("<", 2), "name": ("!=", self.name or "")},
			"name",
		)
		if other:
			frappe.throw(_("Requisition {0} already exists for this supplier quotation.").format(other))
		if not self.project:
			self.project = frappe.db.get_value("Material Request", self.material_request, "muhick_project")
		compared = frappe.db.sql(
			"""
			select count(distinct sqi.parent) from `tabSupplier Quotation Item` sqi
			inner join `tabSupplier Quotation` sq on sq.name = sqi.parent
			where sqi.material_request = %s and sq.docstatus < 2
			""",
			(self.material_request,),
		)
		self.quotations_compared = compared[0][0] if compared else 0

	def set_item_values(self):
		self.total_amount = self.total_budget_amount = self.total_price_variance = 0
		for row in self.items:
			row.amount = flt(row.qty) * flt(row.rate)
			if not row.project:
				row.project = self.project
			if not row.cost_code and row.material_request_item:
				row.cost_code = frappe.db.get_value("Material Request Item", row.material_request_item, "muhick_cost_code")
			if not row.cost_code and row.project:
				row.cost_code = budget_engine.get_budget_cost_code(row.project, row.item_code)
			row.budget_rate = budget_engine.get_budget_rate(row.project, row.item_code) if row.project else 0
			row.price_variance = (flt(row.rate) - flt(row.budget_rate)) * flt(row.qty) if flt(row.budget_rate) else 0
			self.total_amount += row.amount
			self.total_budget_amount += flt(row.budget_rate) * flt(row.qty)
			self.total_price_variance += row.price_variance

	def amounts_by_project(self) -> dict:
		amounts = defaultdict(lambda: defaultdict(float))
		for row in self.items:
			if row.project:
				amounts[row.project][row.cost_code or ""] += flt(row.amount)
		return amounts

	def set_budget_status(self):
		"""Worst result across the projects on the requisition (normally one)."""
		self.budget_status, remarks = "Not Applicable", []
		# an over-budget Material Request that was approved covers the same value here
		allowance = _approved_overrun(self)
		for project, amounts in self.amounts_by_project().items():
			status, note = budget_engine.evaluate(project, amounts, allowance=allowance.get(project))
			if RANK[status] > RANK[self.budget_status]:
				self.budget_status = status
			if note:
				remarks.append(f"{project}: {note}")
		self.budget_remarks = "; ".join(remarks)

	def log_change(self):
		"""A change made while the requisition is under approval is logged, not restarted."""
		before = self.get_doc_before_save()
		leaving_draft = bool(before) and before.get("workflow_state") in BEING_PREPARED and self.workflow_state not in BEING_PREPARED
		# prices above budget are brought to the head of department as soon as it goes for approval
		self.flags.variance_alert = leaving_draft and flt(self.total_price_variance) > 0.5
		if not before or before.get("workflow_state") in BEING_PREPARED:
			return
		was = [(r.item_code, flt(r.qty), flt(r.rate)) for r in before.items]
		now = [(r.item_code, flt(r.qty), flt(r.rate)) for r in self.items]
		if was == now:
			return
		summary = (self.amendment_summary or "").strip()
		if not summary:
			frappe.throw(_("Prices or quantities were changed. Summarise what changed and why before saving."))
		self.append(
			"amendments",
			{
				"changed_on": now_datetime(),
				"changed_by": frappe.session.user,
				"summary": summary,
				"total_before": before.total_amount,
				"total_after": self.total_amount,
			},
		)
		self.amendment_summary = None
		self.flags.change_summary = summary

	def on_update(self):
		if self.flags.change_summary:
			notify_roles(
				FINANCE_ROLES,
				_("{0} was changed while under approval: {1}").format(self.name, self.flags.change_summary),
				doc=self,
			)
		if self.flags.variance_alert:
			notify_roles(
				COO,
				_("{0}: sourced prices are {1} above the project budget.").format(
					self.name, frappe.format_value(self.total_price_variance, "Currency")
				),
				doc=self,
			)

	def before_submit(self):
		for project, amounts in self.amounts_by_project().items():
			status, note = budget_engine.evaluate(project, amounts, allowance=_approved_overrun(self).get(project))
			budget_engine.enforce(self, "budget_action_on_purchase_order", status, f"{project}: {note}")
		self.status = "Approved"

	def on_cancel(self):
		if self.purchase_order and frappe.db.get_value("Purchase Order", self.purchase_order, "docstatus") != 2:
			frappe.throw(_("Purchase Order {0} was raised from this requisition. Cancel it first.").format(self.purchase_order))
		self.db_set("status", "Cancelled")


@frappe.whitelist()
def make_from_supplier_quotation(source_name: str):
	"""Start a requisition from the approved (selected) supplier quotation."""
	quotation = frappe.get_doc("Supplier Quotation", source_name)
	quotation.check_permission("read")
	if quotation.docstatus != 1:
		frappe.throw(_("The supplier selection must be approved before the requisition is raised."))
	material_requests = [i.material_request for i in quotation.items if i.material_request]
	if not material_requests:
		frappe.throw(_("This supplier quotation is not linked to a Material Request."))
	doc = frappe.new_doc("Procurement Requisition")
	doc.update(
		{
			"material_request": material_requests[0],
			"supplier_quotation": quotation.name,
			"supplier": quotation.supplier,
			"supplier_name": quotation.supplier_name,
			"company": quotation.company,
			"project": quotation.project or frappe.db.get_value("Material Request", material_requests[0], "muhick_project"),
		}
	)
	for item in quotation.items:
		doc.append(
			"items",
			{
				"item_code": item.item_code,
				"item_name": item.item_name,
				"uom": item.uom,
				"qty": item.qty,
				"rate": item.rate,
				"project": item.project,
				"warehouse": item.warehouse,
				"schedule_date": item.expected_delivery_date,
				"material_request_item": item.material_request_item,
				"supplier_quotation_item": item.name,
			},
		)
	return doc


@frappe.whitelist()
def make_purchase_order(source_name: str):
	"""Raise the Purchase Order from the approved requisition, as a saved draft."""
	requisition = frappe.get_doc("Procurement Requisition", source_name)
	requisition.check_permission("read")
	if requisition.docstatus != 1:
		frappe.throw(_("The requisition must be approved before the order is raised."))
	if requisition.purchase_order:
		frappe.throw(_("This requisition is already ordered on {0}.").format(requisition.purchase_order))
	draft = frappe.db.get_value("Purchase Order", {"muhick_procurement_requisition": requisition.name, "docstatus": 0}, "name")
	if draft:
		return draft
	today = getdate(nowdate())
	order = frappe.new_doc("Purchase Order")
	order.update(
		{
			"supplier": requisition.supplier,
			"company": requisition.company,
			"project": requisition.project,
			"muhick_procurement_requisition": requisition.name,
			"muhick_payment_type": requisition.payment_terms_type,
			"muhick_advance_percent": requisition.advance_percent,
			"muhick_delivery_location": requisition.delivery_location,
		}
	)
	for row in requisition.items:
		required = max(getdate(row.schedule_date), today) if row.schedule_date else today
		order.append(
			"items",
			{
				"item_code": row.item_code,
				"qty": row.qty,
				"rate": row.rate,
				"uom": row.uom,
				"schedule_date": required,
				"warehouse": row.warehouse,
				"project": row.project,
				"muhick_cost_code": row.cost_code,
				"material_request": requisition.material_request if row.material_request_item else None,
				"material_request_item": row.material_request_item,
				"supplier_quotation": requisition.supplier_quotation,
				"supplier_quotation_item": row.supplier_quotation_item,
			},
		)
	order.schedule_date = max(i.schedule_date for i in order.items)
	# saved on the server so ERPNext fills taxes and accounts and the approved rates are kept
	order.insert()
	return order.name
