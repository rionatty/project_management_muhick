# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Consignment tracking for an imported purchase order: manufacture, letter of credit,
pre-shipment inspection, shipping, customs clearance, container return and delivery, with the
tax worksheet and other charges. Dates are compared with the plan so a delay shows at once."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, add_to_date, date_diff, flt, getdate, nowdate

from project_management_muhick.muhick_projects.utils import validate_dates


class ImportShipment(Document):
	def validate(self):
		if self.purchase_order and not self.supplier:
			self.supplier, project = frappe.db.get_value("Purchase Order", self.purchase_order, ["supplier", "project"])
			self.project = self.project or project
		validate_dates(self.planned_departure, self.planned_arrival, _("Planned Departure"), _("Planned Arrival"))
		validate_dates(self.actual_departure, self.actual_arrival, _("Actual Departure"), _("Actual Arrival"))
		self.expected_ready_date = (
			add_days(self.manufacturing_start, int(self.lead_time_days or 0)) if self.manufacturing_start else None
		)
		self.transit_days_planned = self._days(self.planned_departure, self.planned_arrival)
		self.transit_days_actual = self._days(self.actual_departure, self.actual_arrival)
		# customs give 72 hours from the assessment to pay
		self.tax_payment_deadline = add_to_date(self.tax_assessment_on, hours=72) if self.tax_assessment_on else None
		self.total_charges = sum(flt(c.amount) for c in self.charges)
		if self.shipment_status in ("Delivered", "Closed") and not self.delivered_on:
			self.delivered_on = nowdate()
		self.is_delayed = int(self.behind_schedule())
		if self.is_delayed and self.shipment_status not in ("Delivered", "Closed") and not (self.delay_reason or "").strip():
			frappe.msgprint(_("This consignment is behind schedule. Record the reason for the delay."), indicator="orange", alert=True)

	@staticmethod
	def _days(start, end):
		return date_diff(end, start) if start and end else 0

	def behind_schedule(self) -> bool:
		today = getdate(nowdate())
		if self.expected_ready_date and not self.actual_ready_date and getdate(self.expected_ready_date) < today:
			return True
		if self.planned_arrival and not self.actual_arrival and getdate(self.planned_arrival) < today:
			return True
		arrival = self.actual_arrival or self.planned_arrival
		return bool(self.required_on_site_by and arrival and getdate(arrival) > getdate(self.required_on_site_by))
