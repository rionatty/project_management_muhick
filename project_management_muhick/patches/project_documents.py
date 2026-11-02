# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""A project shows the documents it came from: its won bid and quotation, from its handover and sales order. A supplier
quotation for one project carries it on its header too, where the project's connections read it."""

import frappe

from project_management_muhick.muhick_sales.bids import sales_order_quotation
from project_management_muhick.setup.custom_fields import setup_custom_fields


def execute():
	setup_custom_fields()  # the new fields are normally added after patches run
	for project in frappe.get_all("Project", filters={"muhick_handover": ("is", "set")}, fields=["name", "muhick_handover", "sales_order"]):
		bid = frappe.db.get_value("Project Handover", project.muhick_handover, "opportunity")
		frappe.db.set_value(
			"Project",
			project.name,
			{"muhick_bid": bid, "muhick_quotation": sales_order_quotation(project.sales_order)},
			update_modified=False,
		)
	for quotation in frappe.get_all("Supplier Quotation", filters={"project": ("is", "not set"), "docstatus": ("<", 2)}, pluck="name"):
		projects = set(frappe.get_all("Supplier Quotation Item", filters={"parent": quotation}, pluck="project"))
		if len(projects) == 1 and (project := projects.pop()):
			frappe.db.set_value("Supplier Quotation", quotation, "project", project, update_modified=False)
