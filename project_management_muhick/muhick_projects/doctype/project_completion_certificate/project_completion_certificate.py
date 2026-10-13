# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Practical and Full Completion.

Practical Completion moves the project into its Defects Liability Period, which the system
then tracks with reminders. Full Completion closes the project once the period has ended and
no defect is open. Each certificate makes the matching share of retention due for release.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_months, flt, getdate

from project_management_muhick.overrides import project as project_api
from project_management_muhick.utils import calc
from project_management_muhick.utils.common import FINANCE_ROLES, notify_roles, setting

HANDOVER_DOCUMENTS = [
	"Completion report",
	"As-built drawings",
	"Equipment data sheets",
	"Operation and maintenance manuals",
	"Maintenance schedules",
	"Warranty certificates",
	"Client training on installed equipment",
]
OPEN_DEFECT = ("Open", "In Progress")


class ProjectCompletionCertificate(Document):
	def validate(self):
		project = frappe.db.get_value(
			"Project", self.project, ["muhick_stage", "muhick_dlp_months", "muhick_dlp_end_date"], as_dict=True
		)
		other = frappe.db.get_value(
			"Project Completion Certificate",
			{"project": self.project, "certificate_type": self.certificate_type, "docstatus": 1, "name": ("!=", self.name or "")},
			"name",
		)
		if other:
			frappe.throw(_("{0} is already recorded for this project on {1}.").format(_(self.certificate_type), other))
		self.open_defects = frappe.db.count("Project Defect", {"project": self.project, "status": ("in", OPEN_DEFECT)})
		if self.certificate_type == "Practical Completion":
			if project.muhick_stage != "Execution":
				frappe.throw(_("Practical Completion can only be recorded for a project in execution."))
			if not self.dlp_months:
				self.dlp_months = project.muhick_dlp_months
			self.dlp_end_date = add_months(self.certificate_date, int(self.dlp_months or 0))
			if not self.handover_documents:
				for name in HANDOVER_DOCUMENTS:
					self.append("handover_documents", {"document_name": name})
		else:
			if project.muhick_stage != "Practical Completion":
				frappe.throw(_("Record the Practical Completion Certificate first."))
			self.dlp_months = project.muhick_dlp_months
			self.dlp_end_date = project.muhick_dlp_end_date
			self.set("handover_documents", [])

	def before_submit(self):
		if not self.signed_certificate:
			frappe.throw(_("Attach the signed certificate."))
		if self.certificate_type != "Full Completion":
			return
		if self.open_defects:
			frappe.throw(_("{0} defect(s) are still open on this project. Close them first.").format(self.open_defects))
		if self.dlp_end_date and getdate(self.certificate_date) < getdate(self.dlp_end_date):
			if not (self.early_completion_reason or "").strip():
				frappe.throw(
					_("The Defects Liability Period runs to {0}. Give the reason for completing earlier.").format(
						frappe.format_value(self.dlp_end_date, "Date")
					)
				)

	def on_submit(self):
		if self.certificate_type == "Practical Completion":
			frappe.db.set_value(
				"Project",
				self.project,
				{
					"muhick_stage": "Practical Completion",
					"muhick_practical_completion_date": self.certificate_date,
					"muhick_dlp_months": self.dlp_months,
					"muhick_dlp_end_date": self.dlp_end_date,
					"muhick_last_dlp_reminder": None,
				},
			)
		else:
			project = frappe.get_doc("Project", self.project)
			project.muhick_stage = "Full Completion"
			project.muhick_final_completion_date = self.certificate_date
			project.status = "Completed"
			project.flags.ignore_permissions = True
			project.save()
		self.notify_retention_due()

	def notify_retention_due(self):
		held, released = frappe.db.get_value("Project", self.project, ["muhick_retention_held", "muhick_retention_released"])
		stage = "Practical Completion" if self.certificate_type == "Practical Completion" else "End of Defects Liability"
		due = calc.retention_release_due(held, released, stage, setting("retention_release_at_practical_completion", 50))
		if flt(due) > 0:
			notify_roles(
				FINANCE_ROLES,
				_("{0} recorded for {1}: retention of {2} is now due for release.").format(
					_(self.certificate_type), self.project_name or self.project, frappe.format_value(due, "Currency")
				),
				doc=self,
			)

	def on_cancel(self):
		if self.certificate_type == "Practical Completion":
			if frappe.db.exists("Project Completion Certificate", {"project": self.project, "certificate_type": "Full Completion", "docstatus": 1}):
				frappe.throw(_("Cancel the Full Completion Certificate first."))
			frappe.db.set_value(
				"Project",
				self.project,
				{"muhick_stage": "Execution", "muhick_practical_completion_date": None, "muhick_dlp_end_date": None},
			)
		else:
			frappe.db.set_value(
				"Project", self.project, {"muhick_stage": "Practical Completion", "muhick_final_completion_date": None, "status": "Open"}
			)
