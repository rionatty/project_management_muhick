# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""A milestone (phase) of the approved activity plan. The Project Manager updates progress here;
plan dates, weights and valuations change only through an approved Activity Plan revision."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime, nowdate

from project_management_muhick.overrides import project as project_api
from project_management_muhick.utils.common import notify, project_manager_of

PLAN_FIELDS = (
	"milestone_name", "planned_start", "planned_end", "weight", "planned_valuation",
	"planned_claim_date", "is_billing_milestone", "project",
)
BILLED = ("Claimed", "Certified")


class ProjectMilestone(Document):
	def validate(self):
		self.guard_plan_fields()
		self.percent_complete = min(max(flt(self.percent_complete), 0), 100)
		previous_status = self.status
		if self.percent_complete >= 100:
			if self.status not in BILLED:
				self.status = "Completed"
			self.completion_date = self.completion_date or nowdate()
			self.actual_end = self.actual_end or self.completion_date
			self.actual_start = self.actual_start or self.planned_start
		elif self.status in BILLED:
			frappe.throw(_("{0} has already been claimed; its progress cannot be reduced.").format(self.milestone_name))
		elif self.percent_complete > 0:
			self.status = "In Progress"
			self.actual_start = self.actual_start or nowdate()
			self.completion_date = None
		else:
			self.status = "Not Started"
			self.completion_date = None
		if self.is_new() or self.has_value_changed("percent_complete"):
			self.last_progress_update = now_datetime()
		self.flags.just_completed = self.status == "Completed" and previous_status != "Completed"

	def guard_plan_fields(self):
		if self.flags.from_activity_plan:
			return
		if self.is_new():
			frappe.throw(_("Milestones are created by an approved Project Activity Plan."))
		changed = [self.meta.get_label(f) for f in PLAN_FIELDS if self.has_value_changed(f)]
		if changed:
			frappe.throw(
				_("{0} can only be changed through an approved Activity Plan revision.").format(", ".join(changed))
			)

	def on_update(self):
		project_api.update_progress(self.project)
		if self.flags.just_completed and self.is_billing_milestone:
			# a completed billing milestone is claimed
			notify(
				[project_manager_of(self.project) or self.owner],
				_("Milestone {0} is complete. Raise the Service Delivery Note / Claim.").format(self.milestone_name),
				doc=self,
			)

	def on_trash(self):
		if flt(self.percent_complete) or self.status in BILLED:
			frappe.throw(_("{0} has progress recorded and cannot be deleted.").format(self.milestone_name))
