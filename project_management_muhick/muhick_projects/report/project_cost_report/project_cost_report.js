// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.query_reports["Project Cost Report"] = {
	filters: [
		{
			fieldname: "project",
			label: __("Project"),
			fieldtype: "Link",
			options: "Project",
			description: __("Leave blank for one line per project"),
		},
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && ["available", "forecast_variance", "forecast_margin"].includes(column.fieldname)) {
			if (flt(data[column.fieldname]) < 0) {
				value = `<span style="color: var(--red-600)">${value}</span>`;
			}
		}
		return value;
	},
};
