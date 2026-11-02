# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""A schedule's rows name their group task and say what they are, where until now their level implied it. Columns chosen
for the schedule's table before this go too, as they would hide the new ones."""

import json

import frappe

from project_management_muhick.utils import calc

ROW = "Project Activity Plan Activity"


def execute():
	for plan in frappe.get_all("Project Activity Plan", pluck="name"):
		rows = frappe.get_all(ROW, filters={"parent": plan}, fields=["name", "row_id", "outline_level"], order_by="idx asc")
		levels = [row.outline_level or 0 for row in rows]
		for row, parent, kind in zip(rows, calc.outline_parents(levels), calc.outline_kinds(levels)):
			frappe.db.set_value(ROW, row.name, {"parent_row": rows[parent].row_id if parent is not None else 0, "row_type": kind}, update_modified=False)
	for saved in frappe.db.sql("select `user`, `data` from `__UserSettings` where `doctype` = 'Project Activity Plan'", as_dict=True):
		data = json.loads(saved.data or "{}")
		if (data.get("GridView") or {}).pop(ROW, None) is not None:
			frappe.db.sql(
				"update `__UserSettings` set `data` = %s where `user` = %s and `doctype` = 'Project Activity Plan'",
				(json.dumps(data), saved.user),
			)
	frappe.cache.delete_value("_user_settings")
