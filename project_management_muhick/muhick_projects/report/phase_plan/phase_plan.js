// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.query_reports["Phase Plan"] = {
	filters: [{ fieldname: "project", label: __("Project"), fieldtype: "Link", options: "Project", reqd: 1 }],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && data.phase === __("Current")) {
			value = `<b>${value}</b>`;
		}
		return value;
	},
};
