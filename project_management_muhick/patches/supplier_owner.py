# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""No role profile could create a supplier: the Procurement Manager's could only edit one."""

import frappe

OWNER = "Muhick Procurement Manager"
ROLE = "Purchase Master Manager"


def execute():
	if not frappe.db.exists("Role Profile", OWNER):
		return
	profile = frappe.get_doc("Role Profile", OWNER)
	if not any(row.role == ROLE for row in profile.roles):
		profile.append("roles", {"role": ROLE})
		profile.save(ignore_permissions=True)
