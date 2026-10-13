// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Project Budget Revision", {
	setup(frm) {
		frm.set_query("cost_code", "lines", () => ({ filters: { disabled: 0 } }));
		frm.set_query("variation_order", () => ({ filters: { project: frm.doc.project || "", docstatus: 1 } }));
		frm.set_query("material_request", () => ({ filters: { muhick_project: frm.doc.project || "" } }));
	},
});
