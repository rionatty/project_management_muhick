# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Fuel for a vehicle or a piece of equipment. The odometer reading at each fuelling gives the
distance covered and the consumption since the last one, so unusual consumption shows up without
relying on what the driver reports."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from project_management_muhick.muhick_projects.utils import draft_status
from project_management_muhick.utils.approval import get_route


class FuelRequisition(Document):
	def validate(self):
		if not self.vehicle and not (self.equipment_name or "").strip():
			frappe.throw(_("Select the vehicle, or name the equipment the fuel is for."))
		if not self.requested_by:
			self.requested_by = frappe.session.user
		if flt(self.litres) <= 0:
			frappe.throw(_("Enter the litres required."))
		self.amount = flt(self.litres) * flt(self.rate)
		self.set_consumption()
		self.approval_route = get_route(self.doctype, self.amount)
		self.status = draft_status(self)

	def set_consumption(self):
		self.previous_odometer = self.distance = 0
		self.km_per_litre = 0
		if not self.vehicle or not self.odometer:
			return
		last = frappe.get_all(
			"Fuel Requisition",
			filters={"vehicle": self.vehicle, "docstatus": 1, "name": ("!=", self.name or "")},
			fields=["odometer", "litres"],
			order_by="requisition_date desc, odometer desc",
			limit=1,
		)
		if not last or not last[0].odometer:
			return
		self.previous_odometer = last[0].odometer
		if self.odometer < self.previous_odometer:
			frappe.throw(_("The odometer reading is lower than at the last fuelling ({0} km).").format(self.previous_odometer))
		self.distance = self.odometer - self.previous_odometer
		# the fuel issued last time is what covered this distance
		self.km_per_litre = self.distance / flt(last[0].litres) if flt(last[0].litres) else 0

	def before_submit(self):
		self.status = "Approved"

	def on_submit(self):
		if self.vehicle and self.odometer:
			if self.odometer > (frappe.db.get_value("Vehicle", self.vehicle, "last_odometer") or 0):
				frappe.db.set_value("Vehicle", self.vehicle, "last_odometer", self.odometer)

	def on_cancel(self):
		self.db_set("status", "Cancelled")
