// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.query_reports["Procurement Plan"] = {
	filters: [
		{ fieldname: "project", label: __("Project"), fieldtype: "Link", options: "Project", reqd: 1 },
		{ fieldname: "only_action", label: __("Only Order Now and Late"), fieldtype: "Check" },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && column.fieldname === "plan_status") {
			const colour = { [__("Late")]: "red", [__("Order Now")]: "orange", [__("Ordered")]: "green" }[data.plan_status];
			if (colour) {
				value = `<span style="color: var(--${colour}-600)">${value}</span>`;
			}
		}
		return value;
	},
};
