// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.query_reports["Bid Margin Comparison"] = {
	filters: [
		{ fieldname: "opportunity", label: __("Opportunity (Bid)"), fieldtype: "Link", options: "Opportunity", reqd: 1 },
		{ fieldname: "include_expired", label: __("Include Expired Quotations"), fieldtype: "Check" },
	],

	// the lowest price of each line stands out, and a loss shows in red
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data || !column.fieldname) {
			return value;
		}
		if (column.fieldname.startsWith("supplier_") && data[column.fieldname] && data[column.fieldname] === data.lowest_rate) {
			return `<span style="font-weight: bold; color: var(--green-600)">${value}</span>`;
		}
		if (["margin", "margin_percent"].includes(column.fieldname) && flt(data[column.fieldname]) < 0) {
			return `<span style="color: var(--red-600)">${value}</span>`;
		}
		return value;
	},
};
