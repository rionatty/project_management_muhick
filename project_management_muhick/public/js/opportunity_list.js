// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

// the list shows each bid's status (its sales stage), coloured, in place of the standard status
(() => {
	const settings = (frappe.listview_settings["Opportunity"] = frappe.listview_settings["Opportunity"] || {});
	settings.add_fields = [...(settings.add_fields || []), "sales_stage"];
	settings.get_indicator = (doc) =>
		(muhick.bid_status_indicator && muhick.bid_status_indicator(doc)) || [__(doc.status), "gray", "status,=," + doc.status];
})();
