# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Procurement Report: every item of a material request, the supplier chosen for it and where it stands, on one page, and an
item with no supplier yet saying how far it has got. The requisition is raised from it. One report per material request,
made when an evaluation of its items is approved or asked for from the request. It is read afresh whenever it is opened or
printed, so it always says where things stand."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, nowdate

SELECTED = "Supplier Selected"
ON_REQUISITION = "On Requisition"
ORDERED = "Ordered"
WITH_SUPPLIER = (SELECTED, ON_REQUISITION, ORDERED)


class ProcurementReport(Document):
	def validate(self):
		self.build()

	def onload(self):
		if not self.is_new():
			self.build()

	def before_print(self, settings=None):
		self.build()

	def build(self):
		request = frappe.db.get_value(
			"Material Request", self.material_request, ["company", "muhick_project", "muhick_phase", "schedule_date"], as_dict=True
		)
		if not request:
			frappe.throw(_("Material Request {0} not found.").format(self.material_request))
		self.update(
			{
				"company": request.company,
				"project": request.muhick_project,
				"milestone": request.muhick_phase,
				"required_by": request.schedule_date,
				"report_date": nowdate(),
			}
		)
		lines = frappe.get_all(
			"Material Request Item",
			filters={"parent": self.material_request},
			fields=["name", "item_code", "item_name", "qty", "uom", "stock_qty", "conversion_factor", "schedule_date"],
			order_by="idx asc",
		)
		found = _where_each_stands([line.name for line in lines])
		self.set("items", [])
		for line in lines:
			self.append("items", _item_row(line, found))
		self.set_suppliers(found)
		self.items_total = len(self.items)
		self.items_selected = sum(1 for row in self.items if row.status in WITH_SUPPLIER)
		self.items_pending = self.items_total - self.items_selected
		self.total_amount = sum(flt(row.amount) for row in self.items if row.status in WITH_SUPPLIER)

	def set_suppliers(self, found):
		"""Each supplier chosen, with what it supplies and the reason it was chosen."""
		suppliers = {}
		for row in self.items:
			if row.status in WITH_SUPPLIER and row.supplier:
				# a plain dict: on a frappe._dict, .items is the dict's own method
				entry = suppliers.setdefault(
					row.supplier, {"supplier": row.supplier, "supplier_name": row.supplier_name, "items": 0, "amount": 0.0, "reasons": {}, "evaluation": None}
				)
				entry["items"] += 1
				entry["amount"] += flt(row.amount)
				reason = found.reasons.get(row.supplier_quotation)
				if reason:
					entry["reasons"][reason.reason] = None
					entry["evaluation"] = entry["evaluation"] or reason.parent
		self.set("suppliers", [])
		for entry in suppliers.values():
			self.append(
				"suppliers",
				{
					"supplier": entry["supplier"],
					"supplier_name": entry["supplier_name"],
					"items": entry["items"],
					"amount": entry["amount"],
					"reason": "; ".join(entry["reasons"]),
					"supplier_evaluation": entry["evaluation"],
				},
			)


def _where_each_stands(request_rows) -> frappe._dict:
	"""For the request's lines: their orders, their requisitions, the quotations on them and those chosen, their evaluations
	and their requests for quotation."""
	found = frappe._dict(orders={}, requisitions={}, quoted=defaultdict(list), evaluations={}, enquiries={}, reasons={}, quotations={})
	if not request_rows:
		return found
	rows = ("in", request_rows)
	for row in frappe.get_all("Purchase Order Item", filters={"material_request_item": rows, "docstatus": 1}, fields=["material_request_item", "parent"]):
		found.orders.setdefault(row.material_request_item, row.parent)
	for row in frappe.db.sql(
		"""
		select line.material_request_item, req.name from `tabProcurement Requisition Item` line
		inner join `tabProcurement Requisition` req on req.name = line.parent
		where line.material_request_item in %(rows)s and req.docstatus < 2 and ifnull(req.workflow_state, '') != 'Rejected'
		""",
		{"rows": tuple(request_rows)},
		as_dict=True,
	):
		found.requisitions.setdefault(row.material_request_item, row.name)
	for row in frappe.get_all(
		"Supplier Quotation Item",
		filters={"material_request_item": rows, "docstatus": ("<", 2)},
		fields=["name", "parent", "material_request_item", "muhick_selected", "base_net_amount", "stock_qty", "lead_time_days"],
	):
		found.quoted[row.material_request_item].append(row)
	quotations = {row.parent for rows_ in found.quoted.values() for row in rows_}
	if quotations:
		found.quotations = {
			q.name: q
			for q in frappe.get_all("Supplier Quotation", filters={"name": ("in", list(quotations))}, fields=["name", "supplier", "supplier_name", "valid_till"])
		}
		found.reasons = {
			row.supplier_quotation: row
			for row in frappe.get_all(
				"Supplier Evaluation Supplier", filters={"supplier_quotation": ("in", list(quotations)), "docstatus": 1}, fields=["parent", "supplier_quotation", "reason"]
			)
		}
	for row in frappe.get_all(
		"Supplier Evaluation Item",
		filters={"material_request_item": rows, "docstatus": ("<", 2)},
		fields=["parent", "material_request_item", "supplier_quotation", "docstatus"],
	):
		# an evaluation still open says more than one decided before it
		if row.material_request_item not in found.evaluations or not row.docstatus:
			found.evaluations[row.material_request_item] = row
	for row in frappe.get_all("Request for Quotation Item", filters={"material_request_item": rows, "docstatus": ("<", 2)}, fields=["parent", "material_request_item"]):
		found.enquiries.setdefault(row.material_request_item, row.parent)
	return found


def _item_row(line, found) -> dict:
	row = {
		"material_request_item": line.name, "item_code": line.item_code, "item_name": line.item_name, "qty": line.qty, "uom": line.uom,
		"required_by": line.schedule_date, "request_for_quotation": found.enquiries.get(line.name),
	}
	quoted = found.quoted.get(line.name, [])
	chosen = [q for q in quoted if q.muhick_selected]
	if chosen:
		quotation = found.quotations.get(chosen[0].parent) or frappe._dict()
		amount = sum(flt(q.base_net_amount) for q in chosen)
		stock_qty = sum(flt(q.stock_qty) for q in chosen)
		row.update(
			{
				"supplier": quotation.supplier,
				"supplier_name": quotation.supplier_name,
				"supplier_quotation": chosen[0].parent,
				"supplier_quotation_items": ",".join(q.name for q in chosen),
				"rate": amount / stock_qty * (flt(line.conversion_factor) or 1) if stock_qty else 0,
				"amount": amount,
				"lead_time_days": max(cint(q.lead_time_days) for q in chosen),
				"valid_till": quotation.valid_till,
			}
		)
		reason = found.reasons.get(chosen[0].parent)
		row["supplier_evaluation"] = reason.parent if reason else None
	evaluation = found.evaluations.get(line.name)
	if line.name in found.orders:
		row.update(status=ORDERED, purchase_order=found.orders[line.name], procurement_requisition=found.requisitions.get(line.name))
	elif line.name in found.requisitions:
		row.update(status=ON_REQUISITION, procurement_requisition=found.requisitions[line.name])
	elif chosen:
		row["status"] = SELECTED
	elif evaluation and evaluation.docstatus == 1:
		row.update(
			status="No Supplier Selected",
			supplier_evaluation=evaluation.parent,
			remarks=_("{0} received, none chosen.").format(_quotations(len(quoted))) if quoted else _("No quotation was received."),
		)
	elif evaluation:
		row.update(status="Under Evaluation", supplier_evaluation=evaluation.parent, remarks=_("{0} received.").format(_quotations(len(quoted))))
	elif quoted:
		row.update(status="Quotations Received", remarks=_("{0} received, not yet evaluated.").format(_quotations(len(quoted))))
	elif row["request_for_quotation"]:
		row.update(status="Sent for Quotation", remarks=_("No quotation received yet."))
	else:
		row["status"] = "Not Sent for Quotation"
	return row


def _quotations(count) -> str:
	if not count:
		return _("No quotation")
	return _("1 quotation") if count == 1 else _("{0} quotations").format(count)


def refresh_report(material_request):
	"""Make or bring up to date the request's report, so its list shows how far each request has got."""
	name = frappe.db.get_value("Procurement Report", {"material_request": material_request}, "name")
	doc = frappe.get_doc("Procurement Report", name) if name else frappe.new_doc("Procurement Report")
	doc.material_request = material_request
	doc.flags.ignore_permissions = True
	doc.save()
	return doc.name


@frappe.whitelist()
def make_procurement_report(material_request: str) -> str:
	"""From the material request: its report, made now if it has none."""
	frappe.get_doc("Material Request", material_request).check_permission("read")
	frappe.has_permission("Procurement Report", "read", throw=True)
	return refresh_report(material_request)
