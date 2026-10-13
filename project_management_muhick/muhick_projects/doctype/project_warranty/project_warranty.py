# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import add_months, getdate, nowdate


class ProjectWarranty(Document):
	def validate(self):
		self.warranty_end = add_months(self.warranty_start, int(self.warranty_months or 0))
		if self.status != "Claimed":
			self.status = "Expired" if getdate(self.warranty_end) < getdate(nowdate()) else "Active"
