# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class CostCode(Document):
	def validate(self):
		self.cost_code = (self.cost_code or "").strip().upper()
