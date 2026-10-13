// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Project Milestone", {
	refresh(frm) {
		if (!frm.is_new() && frm.doc.status === "Completed" && frm.doc.is_billing_milestone) {
			frm.add_custom_button(__("Create Claim"), () => {
				frappe.new_doc("Project Claim", { project: frm.doc.project, milestone: frm.doc.name });
			}).addClass("btn-primary");
		}
	},
});
