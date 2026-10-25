// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.listview_settings["Bid Document"] = {
	add_fields: ["status"],
	get_indicator(doc) {
		const colours = { Pending: "red", "In Progress": "orange", Ready: "green" };
		return [__(doc.status), colours[doc.status] || "gray", "status,=," + doc.status];
	},
};
