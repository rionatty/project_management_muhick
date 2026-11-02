# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Columns saved with a table's gear go before the ones a form sets, and for every table of its kind on the form. A set
saved when a budget had one table of lines, with no Stage in it, went on hiding the stage and the rest of the columns of
each of the budget's tabs. It goes, so each tab shows its sheet's columns; the gear can still save another."""

import frappe
from frappe.model.utils.user_settings import sync_user_settings


def execute():
	sync_user_settings()  # what is only in the cache so far
	for row in frappe.db.sql(
		"select `user`, `data` from `__UserSettings` where `doctype` = 'Project Budget'", as_dict=True
	):
		data = frappe.parse_json(row.data or "{}")
		if not (data.get("GridView") or {}).pop("Project Budget Line", None):
			continue
		frappe.db.sql(
			"update `__UserSettings` set `data` = %s where `user` = %s and `doctype` = 'Project Budget'",
			(frappe.as_json(data), row.user),
		)
		frappe.cache.hdel("_user_settings", f"Project Budget::{row.user}")
