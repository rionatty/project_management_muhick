// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

// A phase is a group task. A completed billing phase is claimed from here.
frappe.ui.form.on("Task", {
	refresh(frm) {
		const done = frm.doc.status === "Completed" || flt(frm.doc.progress) >= 100;
		if (frm.doc.is_group && frm.doc.muhick_is_billing_milestone && done && !frm.doc.muhick_billing_status) {
			frm.add_custom_button(__("Create Claim"), () => {
				frappe.new_doc("Project Claim", { project: frm.doc.project, phase: frm.doc.name });
			}).addClass("btn-primary");
		}
	},
});
