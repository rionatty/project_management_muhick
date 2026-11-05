# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Site reports made before progress was reported on each task named only milestones, and moved nothing. Their rows keep
what they say, with the milestone's name to show."""

import frappe


def execute():
	frappe.db.sql(
		"""
		update `tabSite Report Phase` r inner join `tabTask` t on t.name = r.phase
		set r.subject = t.subject, r.is_group = 1
		where ifnull(r.subject, '') = ''
		"""
	)
