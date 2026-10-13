// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.query_reports["Freight Forwarder Performance"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("Shipments From"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -24),
		},
		{ fieldname: "to_date", label: __("Shipments To"), fieldtype: "Date", default: frappe.datetime.get_today() },
	],
};
