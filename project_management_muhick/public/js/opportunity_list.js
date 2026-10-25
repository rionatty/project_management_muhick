// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

// the list shows each bid's status (its sales stage), coloured, in place of the standard status
(() => {
	const colours = {
		Qualified: "blue",
		"In Preparation": "orange",
		Submitted: "purple",
		"Under Evaluation": "yellow",
		"Outcome Pending Approval": "pink",
		Won: "green",
		Lost: "red",
		"Not Pursued": "gray",
		Cancelled: "darkgrey",
	};
	const settings = (frappe.listview_settings["Opportunity"] = frappe.listview_settings["Opportunity"] || {});
	settings.add_fields = [...(settings.add_fields || []), "sales_stage"];
	settings.get_indicator = (doc) =>
		doc.sales_stage
			? [__(doc.sales_stage), colours[doc.sales_stage] || "gray", "sales_stage,=," + doc.sales_stage]
			: [__(doc.status), "gray", "status,=," + doc.status];
})();
