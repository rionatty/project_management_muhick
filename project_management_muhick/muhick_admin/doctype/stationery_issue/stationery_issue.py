# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class StationeryIssue(Document):
	def before_insert(self):
		self.issued_by = frappe.session.user
