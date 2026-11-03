// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.query_reports["Resource Envelope"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
		{ fieldname: "as_at", label: __("As At"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "by_account", label: __("Show Each Bank Account"), fieldtype: "Check" },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && ["own_funds", "available", "after_commitments"].includes(column.fieldname) && flt(data[column.fieldname]) < 0) {
			value = `<span style="color: var(--red-600)">${value}</span>`;
		}
		return value;
	},
};
