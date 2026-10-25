# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""A sales requisition can be a bid security request, approved by the Finance Manager. Existing
requisitions are for bid costs, and the Sales Requisition workflow is rebuilt with the new route
(the workflows are otherwise left as the site has them)."""

import frappe

from project_management_muhick.setup.workflows import setup_workflows


def execute():
	frappe.db.sql("update `tabSales Requisition` set purpose = 'Bid Costs' where ifnull(purpose, '') = ''")
	setup_workflows(force=True, doctypes=["Sales Requisition"])
