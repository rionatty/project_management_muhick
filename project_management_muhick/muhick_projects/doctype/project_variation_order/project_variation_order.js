// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Project Variation Order", {
	setup(frm) {
		frm.set_query("cost_code", "items", () => ({ filters: { disabled: 0 } }));
		// stock and non-stock items alike
		frm.set_query("item_code", "items", () => ({ filters: { disabled: 0 } }));
	},
});

frappe.ui.form.on("Project Variation Order Item", {
	qty: (frm, cdt, cdn) => muhick.set_row_amount(cdt, cdn),
	rate: (frm, cdt, cdn) => muhick.set_row_amount(cdt, cdn),
});
