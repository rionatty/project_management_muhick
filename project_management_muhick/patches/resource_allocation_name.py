# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Project Fund Transfer becomes Resource Allocation, the name its process goes by. Its documents keep their names and
figures. The approval flow and approval form under the old name go; those of the new name are made after migrate."""

import frappe

OLD, NEW = "Project Fund Transfer", "Resource Allocation"


def execute():
	if not frappe.db.exists("DocType", OLD) or frappe.db.exists("DocType", NEW):
		return
	frappe.delete_doc("Workflow", f"Muhick {OLD} Approval", force=True, ignore_missing=True, ignore_permissions=True)
	frappe.delete_doc("Print Format", f"{OLD} Approval Form", force=True, ignore_missing=True, ignore_permissions=True)
	frappe.rename_doc("DocType", f"{OLD} Refund", f"{NEW} Refund", force=True)
	frappe.rename_doc("DocType", OLD, NEW, force=True)
