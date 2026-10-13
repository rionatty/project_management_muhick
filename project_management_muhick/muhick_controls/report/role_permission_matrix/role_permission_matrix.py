# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Role and Permission Matrix: who can create, edit, approve (submit),
cancel and view each key transaction and master, read live from the system's permissions.
Also lists the users holding each role, to check that supplier creation, receipt, invoice
posting and payment do not sit with one person."""

import frappe
from frappe import _

# key masters and transactions, followed by this app's own documents
STANDARD_DOCTYPES = [
	"Supplier", "Customer", "Item", "Bank Account", "Project", "Material Request", "Request for Quotation",
	"Supplier Quotation", "Purchase Order", "Purchase Receipt", "Purchase Invoice", "Payment Entry",
	"Journal Entry", "Stock Entry", "Delivery Note", "Sales Order", "Sales Invoice",
]
ACTIONS = [("create", "Create"), ("read", "View"), ("write", "Edit"), ("submit", "Approve / Submit"), ("cancel", "Cancel"), ("delete", "Delete")]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "doctype_name", "label": _("Document"), "fieldtype": "Link", "options": "DocType", "width": 230},
		{"fieldname": "role", "label": _("Role"), "fieldtype": "Link", "options": "Role", "width": 200},
		*[{"fieldname": f, "label": _(label), "fieldtype": "Data", "width": 120} for f, label in ACTIONS],
		{"fieldname": "users", "label": _("Users with the Role"), "fieldtype": "Data", "width": 360},
	]
	doctypes = [filters.document] if filters.document else STANDARD_DOCTYPES + _app_doctypes()
	users_by_role = {}
	rows = []
	for doctype in doctypes:
		if not frappe.db.exists("DocType", doctype):
			continue
		for perm in frappe.get_meta(doctype).permissions:
			if perm.permlevel or (filters.role and perm.role != filters.role):
				continue
			if perm.role not in users_by_role:
				users_by_role[perm.role] = ", ".join(_users(perm.role))
			row = {"doctype_name": doctype, "role": perm.role, "users": users_by_role[perm.role]}
			for field, _label in ACTIONS:
				row[field] = _("Yes") if perm.get(field) else ""
			rows.append(row)
	return columns, rows


def _app_doctypes():
	return frappe.get_all(
		"DocType",
		filters={"module": ("like", "Muhick %"), "istable": 0},
		pluck="name",
		order_by="name asc",
	)


def _users(role):
	if role in ("All", "Guest", "Desk User"):
		return []
	users = frappe.get_all(
		"Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent", distinct=True, order_by="parent asc"
	)
	enabled = set(frappe.get_all("User", filters={"enabled": 1, "name": ("in", users)}, pluck="name")) if users else set()
	return [u for u in users if u in enabled and u != "Administrator"]
