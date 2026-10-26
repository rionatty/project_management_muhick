# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Every bid keeps a history of its statuses from now on. An existing bid's history begins with the day
it was opened (Qualified) and, if it has moved on since, its present status from the day it took it;
the steps in between were not recorded."""

import frappe
from frappe import _
from frappe.utils import date_diff, getdate

from project_management_muhick.setup.custom_fields import setup_custom_fields


def execute():
	setup_custom_fields()  # the history is normally added after patches run
	for bid in frappe.get_all("Opportunity", fields=["name", "sales_stage", "muhick_stage_since", "creation", "owner"]):
		if frappe.db.exists("Bid Status Change", {"parent": bid.name, "parenttype": "Opportunity"}):
			continue
		opened = getdate(bid.creation)
		since = max(getdate(bid.muhick_stage_since), opened) if bid.muhick_stage_since else opened
		rows = [{"status": "Qualified", "from_date": opened, "changed_by": bid.owner, "note": _("Bid opened")}]
		if bid.sales_stage and bid.sales_stage != "Qualified":
			rows[0].update(to_date=since, days=date_diff(since, opened))
			rows.append(
				{"status": bid.sales_stage, "from_date": since, "note": _("Status when the history began; earlier steps were not recorded")}
			)
		for idx, row in enumerate(rows, 1):
			frappe.get_doc(
				{
					"doctype": "Bid Status Change",
					"parent": bid.name,
					"parenttype": "Opportunity",
					"parentfield": "muhick_status_history",
					"idx": idx,
					**row,
				}
			).db_insert()
