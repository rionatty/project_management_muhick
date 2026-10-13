# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""A request to service or repair a vehicle. Recording when the next service falls due lets the
system remind the office before it becomes a breakdown."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate

from project_management_muhick.muhick_projects.utils import draft_status
from project_management_muhick.utils.approval import get_route
from project_management_muhick.utils.common import require_roles

ADM = "Administration Manager"
FLEET = "Fleet Officer"


class VehicleServiceRequest(Document):
	def validate(self):
		if not self.requested_by:
			self.requested_by = frappe.session.user
		self.approval_route = get_route(self.doctype, self.estimated_cost)
		self.status = draft_status(self)

	def before_submit(self):
		self.status = "Approved"

	def on_cancel(self):
		self.db_set("status", "Cancelled")

	@frappe.whitelist()
	def complete(
		self,
		actual_cost: float,
		completed_on: str | None = None,
		invoice_reference: str | None = None,
		next_service_date: str | None = None,
		next_service_odometer: int | None = None,
	):
		"""Record the work as done, what it cost and when the next service is due."""
		require_roles(ADM, FLEET)
		if self.docstatus != 1 or self.status != "Approved":
			frappe.throw(_("Only an approved request can be completed."))
		self.db_set(
			{
				"status": "Completed",
				"completed_on": completed_on or nowdate(),
				"actual_cost": flt(actual_cost),
				"invoice_reference": invoice_reference,
				"next_service_date": next_service_date,
				"next_service_odometer": next_service_odometer,
				"reminder_sent": 0,
			}
		)
