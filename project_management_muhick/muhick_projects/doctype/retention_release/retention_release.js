// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Retention Release", {
	setup(frm) {
		frm.set_query("subcontract_agreement", () => ({ filters: { project: frm.doc.project || "", docstatus: 1 } }));
		frm.set_query("completion_certificate", () => ({ filters: { project: frm.doc.project || "", docstatus: 1 } }));
	},

	refresh(frm) {
		const finance = frappe.user.has_role(["Finance Manager", "Finance Officer", "System Manager"]);
		const invoiceable = frm.doc.docstatus === 1 && frm.doc.retention_for === "Client" && !frm.doc.sales_invoice;
		if (invoiceable && finance) {
			frm.add_custom_button(__("Sales Invoice"), () => {
				frappe
					.call({ method: "project_management_muhick.muhick_projects.doctype.retention_release.retention_release.make_sales_invoice", args: { source_name: frm.doc.name }, freeze: true })
					.then((r) => r.message && frappe.set_route("Form", "Sales Invoice", r.message));
			}, __("Create"));
		}
	},
});
