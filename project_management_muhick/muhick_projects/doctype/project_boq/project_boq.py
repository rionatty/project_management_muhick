# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Bill of Quantities: the client-approved priced schedule. It is the baseline for the
project budget and for every payment claim."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from project_management_muhick.muhick_projects.utils import set_amounts


class ProjectBOQ(Document):
	def validate(self):
		self.total_amount = set_amounts(self.items)
		for row in self.items:
			if flt(row.qty) < 0 or flt(row.rate) < 0:
				frappe.throw(_("BOQ row {0}: quantity and rate cannot be negative. Record omissions on a Variation Order.").format(row.idx))

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
