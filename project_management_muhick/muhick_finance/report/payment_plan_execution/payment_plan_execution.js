// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.query_reports["Payment Plan Execution"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
		{ fieldname: "plan", label: __("Payment Plan"), fieldtype: "Link", options: "Payment Plan" },
		{
			fieldname: "from_date",
			label: __("Period Ending From"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
		},
		{ fieldname: "to_date", label: __("Period Ending To"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "only_unpaid", label: __("Only What Was Not Paid in Full"), fieldtype: "Check" },
	],
};
