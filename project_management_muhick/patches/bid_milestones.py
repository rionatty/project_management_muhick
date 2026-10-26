# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""A bid's status is shown as milestones that carry weight. The status history they replace is taken
off, the Bid Milestones list is created, and every bid gets its milestones, reached as its record
shows, and its progress."""

import frappe

from project_management_muhick.overrides.crm import refresh_bid_status
from project_management_muhick.setup.custom_fields import setup_custom_fields
from project_management_muhick.setup.defaults import setup_crm_lists


def execute():
	for field in ("Opportunity-muhick_status_history", "Opportunity-muhick_status_history_section"):
		if frappe.db.exists("Custom Field", field):
			frappe.delete_doc("Custom Field", field, ignore_permissions=True, force=True)
	setup_custom_fields()  # the milestones are normally added after patches run
	setup_crm_lists()
	for name in frappe.get_all("Opportunity", pluck="name"):
		refresh_bid_status(name)
