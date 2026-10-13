# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Fuel, servicing, breakdowns and repairs of a piece of equipment. The history supports the
decision to keep repairing or to replace, and puts each cost on the project that caused it."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class EquipmentLog(Document):
	def validate(self):
		if not self.recorded_by:
			self.recorded_by = frappe.session.user
		if self.allocation:
			allocation = frappe.db.get_value(
				"Project Equipment Allocation", self.allocation, ["project", "equipment_name", "asset", "serial_no"], as_dict=True
			)
			self.project = self.project or allocation.project
			self.asset = self.asset or allocation.asset
			self.serial_no = self.serial_no or allocation.serial_no
		if self.log_type == "Fuel" and flt(self.fuel_litres) <= 0:
			frappe.throw(_("Enter the litres of fuel issued."))
		if self.log_type != "Fuel":
			self.fuel_litres = self.hours_run = 0
