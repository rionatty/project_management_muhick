// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.query_reports["Supplier Quotation Comparison"] = {
	filters: [
		{
			fieldname: "request_for_quotation",
			label: __("Request for Quotation"),
			fieldtype: "Link",
			options: "Request for Quotation",
			reqd: 1,
			get_query: () => ({ filters: { docstatus: ["<", 2] } }),
		},
		{ fieldname: "include_expired", label: __("Include Expired"), fieldtype: "Check" },
	],

	// the rows below the lines say a quotation's terms, in the same columns as its money
	formatter(value, row, column, data, default_formatter) {
		if (value === null || value === undefined || value === "") {
			return "";
		}
		let shown;
		if (data && data.fact && column.fieldname.startsWith("amount_")) {
			shown = data.fact === "link" ? frappe.utils.get_form_link("Supplier Quotation", value, true) : frappe.utils.escape_html(value);
		} else {
			shown = default_formatter(value, row, column, data);
		}
		// the lowest stands out, and a price above the budget reads red, even when it is the lowest
		const lowest = data && (data.lowest_cells || []).includes(column.fieldname);
		const above = data && (data.over_cells || []).includes(column.fieldname);
		if (lowest || above) {
			shown = `<span style="color: ${above ? "var(--red-600, #dc2626)" : "var(--green-600, #16a34a)"}; ${lowest ? "font-weight: 600;" : ""}">${shown}</span>`;
		}
		return data && (data.bold || (data.fact && column.fieldname === "item_name")) ? `<b>${shown}</b>` : shown;
	},
};
