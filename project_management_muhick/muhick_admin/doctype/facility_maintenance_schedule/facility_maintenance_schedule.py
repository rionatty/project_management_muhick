# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Routine servicing of office facilities and equipment (access control, generator, fire
extinguishers), with the next due date worked out from the last service."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, add_months, getdate, nowdate


class FacilityMaintenanceSchedule(Document):
	def validate(self):
		if int(self.frequency_months or 0) <= 0:
			frappe.throw(_("Enter how often, in months, this is serviced."))
		self.next_due = add_months(self.last_done or nowdate(), int(self.frequency_months))
		today = getdate(nowdate())
		if getdate(self.next_due) < today:
			self.status = "Overdue"
		elif getdate(self.next_due) <= getdate(add_days(today, 14)):
			self.status = "Due"
		else:
			self.status = "Scheduled"

	@frappe.whitelist()
	def mark_done(self, done_on: str | None = None):
		"""Record that the service was carried out; the next due date moves on."""
		self.last_done = done_on or nowdate()
		self.last_alert_on = None
		self.save()
