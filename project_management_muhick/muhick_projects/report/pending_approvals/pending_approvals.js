// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.query_reports["Pending Approvals"] = {
	filters: [
		{
			fieldname: "status",
			label: __("Show"),
			fieldtype: "Select",
			options: ["Pending", "Completed"],
			default: "Pending",
			reqd: 1,
		},
		{ fieldname: "document_type", label: __("Document Type"), fieldtype: "Link", options: "DocType" },
		{ fieldname: "project", label: __("Project"), fieldtype: "Link", options: "Project" },
		{ fieldname: "only_overdue", label: __("Only Overdue"), fieldtype: "Check" },
		{
			fieldname: "from_date",
			label: __("From (Completed)"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			depends_on: "eval:doc.status=='Completed'",
		},
		{
			fieldname: "to_date",
			label: __("To (Completed)"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			depends_on: "eval:doc.status=='Completed'",
		},
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && data.overdue && ["hours", "overdue"].includes(column.fieldname)) {
			value = `<span style="color: var(--red-600)">${value}</span>`;
		}
		return value;
	},
};
