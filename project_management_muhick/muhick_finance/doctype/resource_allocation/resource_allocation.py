# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Money attached to one project allocated to another. Funds are held project by project, not in one pool: when a project
runs ahead of its own receipts it uses another project's money (often a client advance) and refunds it once it is paid.
The Finance Manager or the department that needs the money prepares the request and the General Manager approves it. It
stays outstanding until refunded, so the position of every project is known."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate

from project_management_muhick.muhick_finance import funds
from project_management_muhick.muhick_projects.utils import draft_status
from project_management_muhick.utils.common import FINANCE_ROLES, notify, project_manager_of, require_roles


class ResourceAllocation(Document):
	def validate(self):
		if self.from_project == self.to_project:
			frappe.throw(_("Select two different projects."))
		if flt(self.amount) <= 0:
			frappe.throw(_("Enter the amount."))
		self.outstanding_amount = flt(self.amount)
		self.status = draft_status(self)
		left = funds.available(self.from_project, self.company)
		if flt(self.amount) > left:
			frappe.msgprint(
				_("{0} has only {1} available.").format(self.from_project, frappe.format_value(left, "Currency")),
				indicator="orange",
				alert=True,
			)

	def before_submit(self):
		self.refunded_amount = 0
		self.outstanding_amount = flt(self.amount)
		self.status = "Outstanding"

	def before_update_after_submit(self):
		self.refunded_amount = sum(flt(r.amount) for r in self.refunds)
		if self.refunded_amount > flt(self.amount) + 0.005:
			frappe.throw(_("Refunds cannot be more than the amount allocated."))
		self.outstanding_amount = flt(self.amount) - self.refunded_amount
		if self.outstanding_amount <= 0.005:
			self.status = "Refunded"
		else:
			self.status = "Partly Refunded" if self.refunded_amount else "Outstanding"

	def on_cancel(self):
		if self.refunds:
			frappe.throw(_("Refunds have been recorded against this allocation; it cannot be cancelled."))
		self.db_set("status", "Cancelled")

	@frappe.whitelist()
	def record_refund(self, amount: float, refund_date: str | None = None, reference: str | None = None):
		"""Finance records the money going back to the project it came from."""
		require_roles(*FINANCE_ROLES)
		if self.docstatus != 1:
			frappe.throw(_("Only an approved allocation can be refunded."))
		amount = flt(amount)
		if amount <= 0 or amount > flt(self.outstanding_amount) + 0.005:
			frappe.throw(_("The amount still to refund is {0}.").format(frappe.format_value(self.outstanding_amount, "Currency")))
		self.append("refunds", {"refund_date": refund_date or nowdate(), "amount": amount, "reference": reference})
		self.save()
		managers = [project_manager_of(self.from_project), project_manager_of(self.to_project)]
		notify(
			[user for user in managers if user],
			_("{0} has refunded {1} to {2}; {3} is still to refund.").format(
				self.to_project,
				frappe.format_value(amount, "Currency"),
				self.from_project,
				frappe.format_value(self.outstanding_amount, "Currency"),
			),
			doc=self,
		)


@frappe.whitelist()
def get_project_funds(company: str, projects) -> dict:
	"""What each project has available, for the form to show while the allocation is prepared."""
	frappe.has_permission("Resource Allocation", "read", throw=True)
	positions = funds.positions(company)
	return {project: flt(positions[project].available) for project in frappe.parse_json(projects) if project}
