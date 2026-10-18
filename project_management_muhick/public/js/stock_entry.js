// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Stock Entry", {
	setup(frm) {
		frm.set_query("muhick_phase", () => ({
			filters: { project: frm.doc.project || "", is_group: 1, status: ["!=", "Cancelled"] },
		}));
		frm.set_query("muhick_cost_code", "items", () => ({ filters: { disabled: 0 } }));
	},
});
