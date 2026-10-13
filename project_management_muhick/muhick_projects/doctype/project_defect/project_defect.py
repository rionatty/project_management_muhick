# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""A defect reported during the Defects Liability Period."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import nowdate

DONE = ("Rectified", "Closed")


class ProjectDefect(Document):
	def validate(self):
		if self.status in DONE and not self.rectified_on:
			self.rectified_on = nowdate()
		if self.status not in DONE:
			self.rectified_on = None
		if self.is_new() and frappe.db.get_value("Project", self.project, "muhick_stage") != "Practical Completion":
			frappe.msgprint(_("This project is not in its Defects Liability Period."), indicator="orange", alert=True)


@frappe.whitelist()
def make_material_request(source_name: str):
	"""If the repair needs new materials, the procurement process is followed."""
	defect = frappe.get_doc("Project Defect", source_name)
	defect.check_permission("read")
	request = frappe.new_doc("Material Request")
	request.update(
		{
			"material_request_type": "Purchase",
			"company": frappe.db.get_value("Project", defect.project, "company"),
			"muhick_project": defect.project,
			"muhick_request_origin": "Defects Liability",
			"muhick_justification": _("Rectification of defect {0}: {1}").format(defect.name, defect.title),
		}
	)
	return request
