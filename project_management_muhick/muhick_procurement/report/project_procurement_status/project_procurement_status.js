// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.query_reports["Project Procurement Status"] = {
	filters: [
		{ fieldname: "project", label: __("Project"), fieldtype: "Link", options: "Project" },
		{
			fieldname: "from_date",
			label: __("Requested From"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -3),
		},
		{ fieldname: "to_date", label: __("Requested To"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "only_outstanding", label: __("Only Outstanding"), fieldtype: "Check", default: 1 },
	],
};
