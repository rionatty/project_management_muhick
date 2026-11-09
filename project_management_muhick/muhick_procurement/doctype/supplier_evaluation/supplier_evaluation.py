# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Supplier Evaluation: the supplier chosen for each line of a request for quotation, from its quotations side by side as the
comparison shows them, with the reason for choosing each supplier. The lowest valid price is chosen to start with. The
Procurement Manager approves it once, or the General Manager for an administration purchase, and that approval is the
supplier selection: each chosen quotation is approved with the lines chosen on it marked selected, and the Procurement
Report of each material request behind it shows where every item stands. What a supplier quoted beyond the request, its
transport say, comes with it while it supplies any line, so that it reaches the requisition and the order."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, formatdate, getdate, nowdate

from project_management_muhick.muhick_procurement.report.supplier_quotation_comparison import supplier_quotation_comparison as comparison
from project_management_muhick.utils.common import administration_purchase

BEING_PREPARED = (None, "", "Draft", "Rejected")
SAME = 0.005
REQUESTED_FIELDS = [
	"name", "item_code", "item_name", "qty", "uom", "stock_qty", "conversion_factor", "project_name", "material_request", "material_request_item",
]


class SupplierEvaluation(Document):
	def validate(self):
		self.company = self.company or frappe.db.get_value("Request for Quotation", self.request_for_quotation, "company")
		self.check_one_open()
		self.set_lines(get_offers(self.request_for_quotation))
		self.set_suppliers()
		if self.docstatus == 1 or self.get("workflow_state") not in BEING_PREPARED:
			self.check_ready()

	def check_one_open(self):
		other = frappe.db.get_value(
			"Supplier Evaluation",
			{"request_for_quotation": self.request_for_quotation, "docstatus": ("<", 2), "name": ("!=", self.name or "")},
			"name",
		)
		if other:
			frappe.throw(_("Request for Quotation {0} is already evaluated on {1}.").format(self.request_for_quotation, other))

	def set_lines(self, data):
		"""One line for each line requested, as its quotations stand now. What was chosen stays chosen, nothing included, while
		its quotation still prices the line; a new evaluation starts with the lowest price that is still valid, and with none
		where every price has expired."""
		starting = not self.lines
		chosen = {row.request_for_quotation_item: row.supplier_quotation for row in self.lines}
		names = {quotation.name: quotation for quotation in data.quotations}
		self.set("lines", [])
		for line in data.requested:
			offers = data.offers.get(line.name, {})
			valid = {name: offer for name, offer in offers.items() if not offer.expired}
			pool = valid or offers
			lowest = min(pool, key=lambda name: pool[name].rate) if pool else None
			pick = (lowest if lowest in valid else None) if starting else chosen.get(line.name)
			offer = offers.get(pick) if pick else None
			quotation = names.get(pick) if offer else None
			self.append(
				"lines",
				{
					"request_for_quotation_item": line.name,
					"item_code": line.item_code,
					"item_name": line.item_name,
					"qty": line.qty,
					"uom": line.uom,
					"material_request": line.material_request,
					"material_request_item": line.material_request_item,
					"project": line.project_name,
					"quotes": len(offers),
					"lowest_supplier": names[lowest].supplier_name if lowest else None,
					"lowest_rate": pool[lowest].rate if lowest else 0,
					"supplier_quotation": quotation.name if quotation else None,
					"supplier": quotation.supplier if quotation else None,
					"supplier_name": quotation.supplier_name if quotation else None,
					"rate": offer.rate if offer else 0,
					"amount": offer.amount if offer else 0,
					"is_lowest": int(bool(offer) and offer.rate - pool[lowest].rate <= SAME),
					"lead_time_days": cint(offer.lead_time) if offer else 0,
					"valid_till": quotation.valid_till if quotation else None,
					"supplier_quotation_items": ",".join(offer.rows) if offer else None,
				},
			)
		self.add_beyond_the_request(data, names)
		projects = {row.project for row in self.lines if row.project}
		self.project = projects.pop() if len(projects) == 1 else None
		self.administration_purchase = administration_purchase(self.lines)

	def add_beyond_the_request(self, data, names):
		chosen = {row.supplier_quotation for row in self.lines if row.supplier_quotation}
		for extra in data.beyond:
			if extra.quotation in chosen:
				quotation = names[extra.quotation]
				self.append(
					"lines",
					{
						"item_code": extra.item_code,
						"item_name": extra.item_name,
						"qty": extra.qty,
						"uom": extra.uom,
						"quotes": 1,
						"supplier_quotation": quotation.name,
						"supplier": quotation.supplier,
						"supplier_name": quotation.supplier_name,
						"rate": extra.rate,
						"amount": extra.amount,
						"is_lowest": 0,
						"lead_time_days": cint(extra.lead_time),
						"valid_till": quotation.valid_till,
						"supplier_quotation_items": ",".join(extra.rows),
					},
				)

	def set_suppliers(self):
		"""A row for each supplier chosen, with what it was chosen for; the reasons typed stay with their quotations."""
		reasons = {row.supplier_quotation: row.reason for row in self.suppliers}
		chosen = {}
		for line in self.lines:
			if line.supplier_quotation:
				# a plain dict: on a frappe._dict, .items is the dict's own method
				row = chosen.setdefault(
					line.supplier_quotation,
					{"supplier": line.supplier, "supplier_name": line.supplier_name, "supplier_quotation": line.supplier_quotation, "items": 0, "lowest_items": 0, "amount": 0.0},
				)
				row["items"] += 1
				row["lowest_items"] += cint(line.is_lowest)
				row["amount"] += flt(line.amount)
		self.set("suppliers", [])
		for name, row in chosen.items():
			self.append("suppliers", {**row, "reason": reasons.get(name)})
		requested = [line for line in self.lines if line.request_for_quotation_item]
		self.items_selected = sum(1 for line in requested if line.supplier_quotation)
		self.items_not_selected = len(requested) - self.items_selected
		self.total_amount = sum(flt(line.amount) for line in self.lines if line.supplier_quotation)

	def check_ready(self):
		if not self.items_selected:
			frappe.throw(_("Choose a supplier for at least one line."))
		missing = [row.supplier_name or row.supplier for row in self.suppliers if not (row.reason or "").strip()]
		if missing:
			frappe.throw(_("Give the reason for choosing {0}.").format(", ".join(missing)))
		today = getdate(nowdate())
		for row in self.suppliers:
			valid_till = frappe.db.get_value("Supplier Quotation", row.supplier_quotation, "valid_till")
			if valid_till and getdate(valid_till) < today:
				frappe.throw(
					_("{0}'s quotation {1} expired on {2}. Ask them to extend it, and change its Valid Till.").format(
						row.supplier_name, row.supplier_quotation, formatdate(valid_till)
					)
				)

	def quotation_rows(self) -> list:
		return [name for line in self.lines if line.supplier_quotation for name in (line.supplier_quotation_items or "").split(",") if name]

	def material_requests(self) -> set:
		return {line.material_request for line in self.lines if line.material_request}

	def on_submit(self):
		"""The selection: each chosen quotation approved, with the lines chosen on it marked."""
		for name in {line.supplier_quotation for line in self.lines if line.supplier_quotation}:
			if frappe.db.get_value("Supplier Quotation", name, "docstatus") == 0:
				quotation = frappe.get_doc("Supplier Quotation", name)
				quotation.flags.ignore_permissions = True
				quotation.submit()
		for row in self.quotation_rows():
			frappe.db.set_value("Supplier Quotation Item", row, {"muhick_selected": 1, "muhick_supplier_evaluation": self.name})
		refresh_reports(self.material_requests())

	def on_cancel(self):
		rows = self.quotation_rows()
		taken = (
			frappe.db.sql(
				"""
				select distinct req.name from `tabProcurement Requisition Item` line
				inner join `tabProcurement Requisition` req on req.name = line.parent
				where line.supplier_quotation_item in %(rows)s and req.docstatus < 2 and ifnull(req.workflow_state, '') != 'Rejected'
				""",
				{"rows": tuple(rows)},
			)
			if rows
			else []
		)
		if taken:
			frappe.throw(_("Its selection is on Procurement Requisition {0}. Cancel that first.").format(", ".join(r[0] for r in taken)))
		for row in rows:
			frappe.db.set_value("Supplier Quotation Item", row, {"muhick_selected": 0, "muhick_supplier_evaluation": None})
		refresh_reports(self.material_requests())


def get_offers(request) -> frappe._dict:
	"""The request's lines, its quotations and, for each line, what each quotation offers: in the company's currency, for one
	of the unit requested, and whether the quotation's validity has passed; and what each quoted beyond the request."""
	quotations, _expired = comparison._quotations(request, True)
	requested = frappe.get_all("Request for Quotation Item", filters={"parent": request}, fields=REQUESTED_FIELDS, order_by="idx asc")
	cells, extras = comparison._quoted(request, requested, quotations)
	today = getdate(nowdate())
	offers = {}
	for line in requested:
		for quotation in quotations:
			cell = cells.get((quotation.name, line.name))
			rate = comparison._rate(cell, line) if cell else None
			if rate:
				offers.setdefault(line.name, {})[quotation.name] = frappe._dict(
					rate=rate,
					amount=cell.amount,
					rows=list(cell.rows),
					lead_time=cell.lead_time,
					expired=bool(quotation.valid_till and getdate(quotation.valid_till) < today),
				)
	beyond = [
		frappe._dict(
			quotation=name, item_code=extras[place].item_code, item_name=extras[place].item_name, uom=extras[place].uom, qty=cell.qty,
			amount=cell.amount, rate=cell.amount / cell.qty, rows=list(cell.rows), lead_time=cell.lead_time,
		)
		for (name, place), cell in list(cells.items())
		if place in extras and cell.qty
	]
	return frappe._dict(requested=requested, quotations=quotations, offers=offers, beyond=beyond)


def refresh_reports(material_requests):
	from project_management_muhick.muhick_procurement.doctype.procurement_report.procurement_report import refresh_report

	for name in sorted(material_requests):
		refresh_report(name)


@frappe.whitelist()
def make_supplier_evaluation(source_name: str):
	"""From the comparison or the request for quotation: its evaluation, or a new one with the lowest valid price chosen for
	each line."""
	request = frappe.get_doc("Request for Quotation", source_name)
	request.check_permission("read")
	existing = frappe.db.get_value("Supplier Evaluation", {"request_for_quotation": source_name, "docstatus": ("<", 2)}, "name")
	if existing:
		return frappe.get_doc("Supplier Evaluation", existing)
	doc = frappe.new_doc("Supplier Evaluation")
	doc.update({"request_for_quotation": source_name, "company": request.company})
	doc.set_lines(get_offers(source_name))
	doc.set_suppliers()
	return doc


@frappe.whitelist()
def get_selection(request_for_quotation: str) -> dict:
	"""What the evaluation's form lays out: each quotation as a column, and what it offers on each line."""
	frappe.has_permission("Supplier Evaluation", "read", throw=True)
	data = get_offers(request_for_quotation)
	company = frappe.db.get_value("Request for Quotation", request_for_quotation, "company")
	return {
		"currency": frappe.get_cached_value("Company", company, "default_currency"),
		"quotations": [
			{
				"name": quotation.name,
				"supplier": quotation.supplier,
				"supplier_name": quotation.supplier_name,
				"valid_till": quotation.valid_till,
				"expired": bool(quotation.valid_till and getdate(quotation.valid_till) < getdate(nowdate())),
				"currency": quotation.currency,
			}
			for quotation in data.quotations
		],
		"offers": {
			line: {name: {"rate": offer.rate, "amount": offer.amount, "lead_time": offer.lead_time, "expired": offer.expired} for name, offer in offers.items()}
			for line, offers in data.offers.items()
		},
		"beyond": data.beyond,
	}
