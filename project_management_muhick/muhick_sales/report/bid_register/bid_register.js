// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.query_reports["Bid Register"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: ["", "Identified", "Qualified", "Not Pursued", "In Preparation", "Submitted", "Under Evaluation", "Won", "Lost", "Cancelled"],
		},
		{ fieldname: "assigned_to", label: __("Sales Engineer"), fieldtype: "Link", options: "User" },
		{
			fieldname: "from_date",
			label: __("Identified From"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -12),
		},
		{ fieldname: "to_date", label: __("Identified To"), fieldtype: "Date", default: frappe.datetime.get_today() },
	],
};
