// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.query_reports["Role Permission Matrix"] = {
	filters: [
		{ fieldname: "document", label: __("Document"), fieldtype: "Link", options: "DocType" },
		{ fieldname: "role", label: __("Role"), fieldtype: "Link", options: "Role" },
	],
};
