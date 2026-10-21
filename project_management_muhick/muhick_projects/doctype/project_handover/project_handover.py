# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Sales to Project handover.

A won bid becomes an active project only after the Project Manager accepts a complete
handover pack. Every mandatory item must be provided, or waived with a reason.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from project_management_muhick.muhick_projects.utils import validate_dates
from project_management_muhick.utils.common import get_settings

# handover field -> Project field
PROJECT_FIELDS = {
	"project_category": "muhick_project_category",
	"contract_no": "muhick_contract_no",
	"contract_value": "muhick_contract_value",
	"contract_start": "muhick_contract_start",
	"contract_end": "muhick_contract_end",
	"billing_method": "muhick_billing_method",
	"advance_percent": "muhick_advance_percent",
	"retention_percent": "muhick_retention_percent",
	"dlp_months": "muhick_dlp_months",
	"project_manager": "muhick_project_manager",
	"sales_engineer": "muhick_sales_engineer",
}


class ProjectHandover(Document):
	def validate(self):
		if not self.checklist:
			self.load_checklist()
		validate_dates(self.contract_start, self.contract_end, _("Contract Start"), _("Contract End"))
		for row in self.checklist:
			if row.waived and not (row.waive_reason or "").strip():
				frappe.throw(_("Handover Checklist row {0}: give the reason {1} is waived.").format(row.idx, row.checklist_item))
		if self.project:
			customer = frappe.db.get_value("Project", self.project, "customer")
			if customer and customer != self.customer:
				frappe.throw(_("Project {0} belongs to client {1}.").format(self.project, customer))
			other = frappe.db.get_value(
				"Project Handover", {"project": self.project, "docstatus": 1, "name": ("!=", self.name or "")}, "name"
			)
			if other:
				frappe.throw(_("Project {0} already has an accepted handover: {1}.").format(self.project, other))

	def load_checklist(self):
		for item in get_settings().get("handover_checklist") or []:
			self.append("checklist", {"checklist_item": item.checklist_item, "is_mandatory": item.is_mandatory})

	def before_submit(self):
		missing = [r.checklist_item for r in self.checklist if r.is_mandatory and not r.provided and not r.waived]
		if missing:
			frappe.throw(
				_("The handover pack is incomplete. Provide or waive:") + "<br>" + "<br>".join(f"- {m}" for m in missing),
				title=_("Handover Pack Incomplete"),
			)
		self.accepted_by = frappe.session.user
		self.accepted_on = now_datetime()

	def on_submit(self):
		project = frappe.get_doc("Project", self.project) if self.project else self.make_project()
		self.update_project(project)

	def make_project(self):
		project = frappe.new_doc("Project")
		project.project_name = self.project_name
		project.company = self.company
		project.customer = self.customer
		project.sales_order = self.sales_order
		project.expected_start_date = self.contract_start
		project.expected_end_date = self.contract_end
		project.insert(ignore_permissions=True)
		self.db_set("project", project.name)
		return project

	def update_project(self, project):
		project.muhick_handover = self.name
		for source, target in PROJECT_FIELDS.items():
			if self.get(source) not in (None, ""):
				project.set(target, self.get(source))
		if not project.get("muhick_approved_brands"):
			for row in self.approved_brands:
				project.append(
					"muhick_approved_brands",
					{f: row.get(f) for f in ("item_group", "item_code", "brand", "specification", "approval_reference")},
				)
		project.flags.ignore_permissions = True
		project.save()

	def on_cancel(self):
		if self.project and frappe.db.get_value("Project", self.project, "muhick_handover") == self.name:
			if frappe.db.get_value("Project", self.project, "muhick_stage") != "Planning":
				frappe.throw(_("Project {0} is already in execution; its handover cannot be cancelled.").format(self.project))
			frappe.db.set_value("Project", self.project, "muhick_handover", None)


@frappe.whitelist()
def get_checklist_template():
	return [
		{"checklist_item": i.checklist_item, "is_mandatory": i.is_mandatory}
		for i in get_settings().get("handover_checklist") or []
	]


@frappe.whitelist()
def make_from_sales_order(source_name: str):
	"""Start a handover from a confirmed Sales Order. The project name is left for the user to type."""
	so = frappe.get_doc("Sales Order", source_name)
	so.check_permission("read")
	doc = frappe.new_doc("Project Handover")
	doc.update(
		{
			"customer": so.customer,
			"company": so.company,
			"sales_order": so.name,
			"project": so.project,
			"contract_value": so.base_net_total,
			"sales_engineer": frappe.session.user,
		}
	)
	doc.load_checklist()
	return doc
