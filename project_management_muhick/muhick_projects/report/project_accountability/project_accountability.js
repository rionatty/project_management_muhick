// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.query_reports["Project Accountability"] = {
	filters: [
		{ fieldname: "project", label: __("Project"), fieldtype: "Link", options: "Project", reqd: 1 },
		{ fieldname: "only_open", label: __("Only Not Yet Accounted For"), fieldtype: "Check" },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "accountability" && data && data.accountability === __("Overdue")) {
			return `<span style="color: var(--red-600)">${value}</span>`;
		}
		return value;
	},
};
