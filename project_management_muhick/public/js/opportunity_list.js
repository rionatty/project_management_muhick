// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

// the list tags each opportunity with where the sale stands; its bid status is a column beside it
(() => {
	const settings = (frappe.listview_settings["Opportunity"] = frappe.listview_settings["Opportunity"] || {});
	settings.add_fields = [...(settings.add_fields || []), "sales_stage"];
	settings.get_indicator = (doc) =>
		(muhick.opportunity_status_indicator && muhick.opportunity_status_indicator(doc)) || [__(doc.status), "gray", "status,=," + doc.status];
})();
