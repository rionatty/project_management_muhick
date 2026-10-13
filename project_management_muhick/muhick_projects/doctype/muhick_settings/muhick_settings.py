# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class MuhickSettings(Document):
	def validate(self):
		parent = self.site_store_parent_warehouse
		if parent and not frappe.db.get_value("Warehouse", parent, "is_group"):
			frappe.throw(_("Parent Warehouse for Site Stores must be a group warehouse."))
		for fieldname in ("default_retention_percent", "retention_release_at_practical_completion"):
			if not 0 <= flt(self.get(fieldname)) <= 100:
				frappe.throw(_("{0} must be between 0 and 100.").format(self.meta.get_label(fieldname)))
		for row in self.approval_thresholds:
			if flt(row.upto_amount) <= 0:
				frappe.throw(_("Approval Thresholds row {0}: Up To Amount must be more than zero.").format(row.idx))
		for row in self.turnaround_rules:
			if flt(row.max_hours) <= 0:
				frappe.throw(_("Turnaround Rules row {0}: Allowed Hours must be more than zero.").format(row.idx))

	def on_update(self):
		from project_management_muhick.setup.roles import apply_price_visibility

		apply_price_visibility(bool(self.show_purchase_orders_to_project_managers))
