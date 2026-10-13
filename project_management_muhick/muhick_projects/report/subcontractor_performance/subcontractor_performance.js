// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.query_reports["Subcontractor Performance"] = {
	filters: [{ fieldname: "supplier", label: __("Subcontractor"), fieldtype: "Link", options: "Supplier" }],
};
