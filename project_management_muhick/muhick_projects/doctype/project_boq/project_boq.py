# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Bill of Quantities: the client-approved priced schedule. It is the baseline for the
project budget and for every payment claim.

Each line can carry a milestone from the shared milestone list (Task Type) and shows how much of
its item has been requested, purchased and consumed for that milestone. Those quantities are kept
current whenever a material request, purchase order or stock entry of the project is submitted or
cancelled."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from project_management_muhick.muhick_projects.utils import set_amounts
from project_management_muhick.utils import calc

QUANTITY_FIELDS = ("requested_qty", "purchased_qty", "consumed_qty")


class ProjectBOQ(Document):
	def validate(self):
		self.total_amount = set_amounts(self.items)
		for row in self.items:
			if flt(row.qty) < 0 or flt(row.rate) < 0:
				frappe.throw(_("BOQ row {0}: quantity and rate cannot be negative. Record omissions on a Variation Order.").format(row.idx))
		set_quantities(self.project, self.items)

	def before_update_after_submit(self):
		# milestones can be set on an approved BOQ; the quantities follow. Its lines stay as approved,
		# including any entered before the item was mandatory.
		self.flags.ignore_mandatory = True
		set_quantities(self.project, self.items)

	def before_submit(self):
		other = frappe.db.get_value(
			"Project BOQ", {"project": self.project, "docstatus": 1, "name": ("!=", self.name)}, "name"
		)
		if other:
			frappe.throw(
				_("Project {0} already has an approved BOQ ({1}). Amend it, or raise a Variation Order for changes.").format(
					self.project, other
				)
			)

	def on_submit(self):
		frappe.db.set_value("Project", self.project, "muhick_boq", self.name)
		contract_value = flt(frappe.db.get_value("Project", self.project, "muhick_contract_value"))
		if contract_value and abs(contract_value - flt(self.total_amount)) > 0.5:
			frappe.msgprint(
				_("The BOQ total ({0}) differs from the contract value on the project ({1}).").format(
					frappe.format_value(self.total_amount, "Currency"), frappe.format_value(contract_value, "Currency")
				),
				indicator="orange",
			)

	def on_cancel(self):
		rows = [row.name for row in self.items]
		claimed = frappe.db.sql(
			"""
			select c.name from `tabProject Claim Item` ci
			inner join `tabProject Claim` c on c.name = ci.parent
			where c.docstatus = 1 and ci.source_row in %(rows)s limit 1
			""",
			{"rows": tuple(rows) or ("",)},
		)
		if claimed:
			frappe.throw(_("Claim {0} has been raised against this BOQ, so it cannot be cancelled.").format(claimed[0][0]))
		if frappe.db.get_value("Project", self.project, "muhick_boq") == self.name:
			frappe.db.set_value("Project", self.project, "muhick_boq", None)


def set_quantities(project, rows):
	"""Requested, purchased and consumed quantity of each row's item, split by milestone."""
	rows = [r for r in rows if r.item_code]
	lines = [{"name": r.idx, "item_code": r.item_code, "phase": r.milestone, "qty": r.qty} for r in rows]
	totals = document_totals(project, {r.item_code for r in rows}) if rows else {}
	changed = []
	for field in QUANTITY_FIELDS:
		shares = calc.allocate_to_lines(lines, totals.get(field, {}))
		for row in rows:
			if abs(flt(row.get(field)) - shares[row.idx]) > 1e-9:
				setattr(row, field, shares[row.idx])  # a form row or a plain dict row from get_all
				changed.append(row)
	return changed


def document_totals(project, items) -> dict:
	"""{field: {(item, milestone): quantity in stock unit}} from the project's submitted documents.
	A document's milestone is the Type of the project milestone task it was raised against."""
	params = {"project": project, "items": tuple(items)}
	queries = {
		"requested_qty": """
			select i.item_code, t.type as phase, sum(i.stock_qty) as qty
			from `tabMaterial Request Item` i inner join `tabMaterial Request` p on p.name = i.parent
			left join `tabTask` t on t.name = p.muhick_phase
			where p.docstatus = 1 and p.status not in ('Stopped', 'Cancelled')
				and i.project = %(project)s and i.item_code in %(items)s
			group by i.item_code, t.type""",
		# an order takes the milestone of the request it was raised from
		"purchased_qty": """
			select i.item_code, t.type as phase, sum(i.stock_qty) as qty
			from `tabPurchase Order Item` i inner join `tabPurchase Order` p on p.name = i.parent
			left join `tabMaterial Request` mr on mr.name = i.material_request
			left join `tabTask` t on t.name = mr.muhick_phase
			where p.docstatus = 1 and i.project = %(project)s and i.item_code in %(items)s
			group by i.item_code, t.type""",
		"consumed_qty": """
			select d.item_code, t.type as phase, sum(d.transfer_qty) as qty
			from `tabStock Entry Detail` d inner join `tabStock Entry` se on se.name = d.parent
			left join `tabTask` t on t.name = se.muhick_phase
			where se.docstatus = 1 and se.purpose = 'Material Issue'
				and ifnull(nullif(d.project, ''), se.project) = %(project)s and d.item_code in %(items)s
			group by d.item_code, t.type""",
	}
	return {
		field: {(r.item_code, r.phase or None): flt(r.qty) for r in frappe.db.sql(sql, params, as_dict=True)}
		for field, sql in queries.items()
	}


def update_quantities(project):
	"""Refresh the quantities on the lines of the project's approved BOQ."""
	boq = frappe.db.get_value("Project", project, "muhick_boq")
	if not boq:
		return
	rows = frappe.get_all(
		"Project BOQ Item",
		filters={"parent": boq},
		fields=["name", "idx", "item_code", "milestone", "qty", *QUANTITY_FIELDS],
		order_by="idx asc",
	)
	for row in {r.name: r for r in set_quantities(project, rows)}.values():
		frappe.db.set_value("Project BOQ Item", row.name, {f: flt(row.get(f)) for f in QUANTITY_FIELDS}, update_modified=False)


def refresh_from_document(doc, method=None):
	"""doc_event of Material Request, Purchase Order and Stock Entry (submit / cancel)."""
	projects = {doc.get("project"), doc.get("muhick_project"), *(row.get("project") for row in doc.get("items") or [])}
	for project in filter(None, projects):
		update_quantities(project)


@frappe.whitelist()
def refresh_quantities(boq: str):
	doc = frappe.get_doc("Project BOQ", boq)
	doc.check_permission("read")
	update_quantities(doc.project)
