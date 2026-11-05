// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Project Requisition", {
	setup(frm) {
		muhick.set_project_queries(frm, ["items", "expenses"]);
		muhick.setup_cash_requisition(frm);
	},

	refresh(frm) {
		if (frm.doc.docstatus === 1) {
			muhick.cash_requisition_actions(frm);
		}
	},
});

frappe.ui.form.on("Project Requisition Item", {
	qty: (frm, cdt, cdn) => muhick.set_row_amount(cdt, cdn),
	rate: (frm, cdt, cdn) => muhick.set_row_amount(cdt, cdn),
});
