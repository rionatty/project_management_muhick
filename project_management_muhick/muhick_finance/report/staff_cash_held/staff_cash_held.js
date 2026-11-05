// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.query_reports["Staff Cash Held"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{ fieldname: "show_cleared", label: __("Show Those Holding Nothing"), fieldtype: "Check" },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "days_overdue" && data && flt(data.days_overdue) > 0) {
			value = `<span style="color: var(--red-600)">${value}</span>`;
		}
		return value;
	},
};
