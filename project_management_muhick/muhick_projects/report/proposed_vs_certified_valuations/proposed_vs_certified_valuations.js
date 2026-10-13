// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.query_reports["Proposed vs Certified Valuations"] = {
	filters: [{ fieldname: "project", label: __("Project"), fieldtype: "Link", options: "Project" }],
};
