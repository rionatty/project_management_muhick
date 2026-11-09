// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Supplier Quotation", {
	refresh(frm) {
		if (frm.doc.docstatus < 2 && ["Exceeds Budget", "Not Budgeted"].includes(frm.doc.muhick_budget_status)) {
			frm.set_intro(`${__(frm.doc.muhick_budget_status)}: ${frappe.utils.escape_html(frm.doc.muhick_budget_remarks || "")}`, "orange");
		}
		// against the others for the same request for quotation
		const request = (frm.doc.items || []).map((row) => row.request_for_quotation).find(Boolean);
		if (request && frm.doc.docstatus < 2 && !frm.is_new()) {
			frm.add_custom_button(__("Compare Quotations"), () => {
				frappe.set_route("query-report", "Supplier Quotation Comparison", { request_for_quotation: request });
			});
		}
	},
});
