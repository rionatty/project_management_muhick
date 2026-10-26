# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""The opportunity status follows the sale and the bid status the tender. An opportunity whose bid was
won (its outcome report approved) and whose sale has gone no further is Won."""

import frappe

from project_management_muhick.setup.custom_fields import setup_custom_fields


def execute():
	setup_custom_fields()  # the Won status is normally added after patches run
	for (name,) in frappe.db.sql(
		"""
		select bid.name from `tabOpportunity` bid
		inner join `tabBid Outcome` outcome on outcome.name = bid.muhick_bid_outcome
		where bid.status = 'Open' and outcome.docstatus = 1 and outcome.outcome = 'Won'
		"""
	):
		frappe.db.set_value("Opportunity", name, "status", "Won", update_modified=False)
