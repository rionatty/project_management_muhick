// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.query_reports["Bank Facility Utilisation"] = {
	filters: [
		{
			fieldname: "view",
			label: __("Show"),
			fieldtype: "Select",
			options: ["Facilities", "Instruments"],
			default: "Facilities",
			reqd: 1,
		},
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "include_closed",
			label: __("Include Cancelled, Released and Expired"),
			fieldtype: "Check",
			depends_on: "eval:doc.view=='Instruments'",
		},
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && column.fieldname === "available" && flt(data.available) < 0) {
			value = `<span style="color: var(--red-600)">${value}</span>`;
		}
		return value;
	},
};
