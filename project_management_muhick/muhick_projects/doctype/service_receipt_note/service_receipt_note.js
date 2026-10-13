// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Service Receipt Note", {
	setup(frm) {
		frm.set_query("subcontract_agreement", () => ({ filters: { docstatus: 1, status: "Active" } }));
	},

	refresh(frm) {
		const finance = frappe.user.has_role(["Finance Manager", "Finance Officer", "System Manager"]);
		if (frm.doc.docstatus === 1 && !frm.doc.purchase_invoice && finance) {
			frm.add_custom_button(__("Purchase Invoice"), () => {
				frappe
					.call({ method: "project_management_muhick.muhick_projects.doctype.service_receipt_note.service_receipt_note.make_purchase_invoice", args: { source_name: frm.doc.name }, freeze: true })
					.then((r) => r.message && frappe.set_route("Form", "Purchase Invoice", r.message));
			}, __("Create"));
		}
	},

	// load the agreement's payment milestones so the work certified can be entered against them
	subcontract_agreement(frm) {
		frm.clear_table("items");
		frm.refresh_field("items");
		if (frm.doc.subcontract_agreement) {
			frm.call("load_items").then(() => frm.refresh_field("items"));
		}
	},
});
