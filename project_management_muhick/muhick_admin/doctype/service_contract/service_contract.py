# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""A recurring contract (utilities, lunch, cleaning, insurance, licences) with its renewal date,
so it is renewed and paid before it lapses."""

from frappe.model.document import Document
from frappe.utils import getdate, nowdate

from project_management_muhick.muhick_projects.utils import validate_dates


class ServiceContract(Document):
	def validate(self):
		validate_dates(self.start_date, self.end_date, "Start Date", "Renewal / Expiry Date")
		if not self.is_new() and self.has_value_changed("end_date"):
			# renewed: remind again before the new date
			self.reminder_sent = 0
			if self.status == "Expired" and getdate(self.end_date) >= getdate(nowdate()):
				self.status = "Active"
