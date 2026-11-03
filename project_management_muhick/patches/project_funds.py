# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""So the money in the bank can be told project by project. A sales order takes the project that names it, and so do what
is made from it from now on. A payment already posted with no project takes that of what it pays, and its postings too. A
resource allocation now goes only to the General Manager, so one waiting on the Finance Manager moves on."""

import frappe

from project_management_muhick.muhick_finance import funds


def execute():
	for project in frappe.get_all("Project", filters={"sales_order": ("is", "set")}, fields=["name", "sales_order"]):
		if not frappe.db.get_value("Sales Order", project.sales_order, "project"):
			frappe.db.set_value("Sales Order", project.sales_order, "project", project.name, update_modified=False)

	for entry in frappe.get_all(
		"Payment Entry",
		filters={"docstatus": 1, "project": ("is", "not set"), "payment_type": ("!=", "Internal Transfer")},
		pluck="name",
	):
		references = frappe.get_all(
			"Payment Entry Reference", filters={"parent": entry}, fields=["reference_doctype", "reference_name"]
		)
		projects = {funds.document_project(r.reference_doctype, r.reference_name) for r in references}
		if len(projects) == 1 and (project := projects.pop()):
			frappe.db.set_value("Payment Entry", entry, "project", project, update_modified=False)
			frappe.db.set_value(
				"GL Entry", {"voucher_type": "Payment Entry", "voucher_no": entry, "is_cancelled": 0}, "project", project, update_modified=False
			)

	frappe.db.set_value(
		"Resource Allocation", {"workflow_state": "Pending Finance Manager"}, "workflow_state", "Pending General Manager", update_modified=False
	)
