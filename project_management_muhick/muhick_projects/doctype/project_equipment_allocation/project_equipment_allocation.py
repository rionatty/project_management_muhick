# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Equipment and tools held by a project: who is responsible, in what condition, and for how
long. A move from one project to another is a recorded handover the receiving side accepts, so
the register always shows where each piece is. High-value equipment is charged to the project
at a daily hire rate for the days it is held."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import date_diff, flt, getdate, now_datetime, nowdate

from project_management_muhick.muhick_projects.utils import validate_dates

HELD = ("Allocated", "Under Repair")


class ProjectEquipmentAllocation(Document):
	def validate(self):
		validate_dates(self.allocated_on, self.returned_on, _("Allocated On"), _("Returned On"))
		if self.status in HELD:
			self.returned_on = None
			self.check_not_held_elsewhere()
		elif not self.returned_on:
			self.returned_on = nowdate()
		end = getdate(self.returned_on or nowdate())
		self.chargeable_days = max(date_diff(end, getdate(self.allocated_on)) + 1, 0)
		self.hire_charge = self.chargeable_days * flt(self.daily_hire_rate) * flt(self.quantity or 1)

	def check_not_held_elsewhere(self):
		for field in ("asset", "serial_no"):
			if not self.get(field):
				continue
			other = frappe.db.get_value(
				"Project Equipment Allocation",
				{field: self.get(field), "status": ("in", HELD), "name": ("!=", self.name or "")},
				["name", "project"],
				as_dict=True,
			)
			if other:
				frappe.throw(
					_("This equipment is still allocated to project {0} ({1}). Transfer it from there.").format(other.project, other.name)
				)

	@frappe.whitelist()
	def transfer(self, to_project: str, responsible_person: str):
		"""Hand the equipment over to another project."""
		if self.status not in HELD:
			frappe.throw(_("Only equipment currently held can be transferred."))
		if to_project == self.project:
			frappe.throw(_("Select a different project."))
		self.status = "Transferred"
		self.returned_on = nowdate()
		self.save()
		new = frappe.copy_doc(self)
		new.update(
			{
				"project": to_project,
				"status": "Allocated",
				"allocated_on": nowdate(),
				"returned_on": None,
				"expected_return": None,
				"condition_in": None,
				"breakdown_notes": None,
				"responsible_person": responsible_person,
				"from_allocation": self.name,
				"from_project": self.project,
				"handover_accepted_by": None,
				"handover_accepted_on": None,
			}
		)
		new.insert()
		return new.name

	@frappe.whitelist()
	def accept_handover(self):
		"""The receiving side confirms it has the equipment and its condition."""
		if not self.from_allocation or self.handover_accepted_by:
			frappe.throw(_("There is no handover waiting to be accepted."))
		self.db_set({"handover_accepted_by": frappe.session.user, "handover_accepted_on": now_datetime()})
