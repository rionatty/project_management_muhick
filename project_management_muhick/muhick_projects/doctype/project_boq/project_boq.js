// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Project BOQ", {
	setup(frm) {
		// stock and non-stock items alike
		frm.set_query("item_code", "items", () => ({ filters: { disabled: 0 } }));
	},

	refresh(frm) {
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(
				__("Project Budget"),
				() => frappe.new_doc("Project Budget", { project: frm.doc.project, boq: frm.doc.name }),
				__("Create")
			);
		}
	},
});

frappe.ui.form.on("Project BOQ Item", {
	qty: (frm, cdt, cdn) => muhick.set_row_amount(cdt, cdn),
	rate: (frm, cdt, cdn) => muhick.set_row_amount(cdt, cdn),
});
