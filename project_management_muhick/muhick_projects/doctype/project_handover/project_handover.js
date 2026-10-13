// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Project Handover", {
	onload(frm) {
		// a new handover starts with the mandatory handover pack from Muhick Settings
		if (frm.is_new() && !(frm.doc.checklist || []).length) {
			frappe
				.call("project_management_muhick.muhick_projects.doctype.project_handover.project_handover.get_checklist_template")
				.then((r) => {
					(r.message || []).forEach((item) => frm.add_child("checklist", item));
					frm.refresh_field("checklist");
				});
		}
		if (frm.is_new() && !frm.doc.sales_engineer) {
			frm.set_value("sales_engineer", frappe.session.user);
		}
	},

	refresh(frm) {
		const open = (frm.doc.checklist || []).filter((r) => r.is_mandatory && !r.provided && !r.waived);
		if (frm.doc.docstatus === 0 && open.length) {
			frm.set_intro(
				__("{0} mandatory handover item(s) are still to be provided or waived.", [open.length]),
				"orange"
			);
		}
	},
});
