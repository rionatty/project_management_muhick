// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Project Activity Plan", {
	refresh(frm) {
		if (frm.doc.docstatus === 1 && frm.doc.is_current) {
			frm.add_custom_button(__("Revise Plan"), () => {
				frappe.model.open_mapped_doc({
					method: "project_management_muhick.muhick_projects.doctype.project_activity_plan.project_activity_plan.make_revision",
					frm: frm,
				});
			});
		}
	},
});
