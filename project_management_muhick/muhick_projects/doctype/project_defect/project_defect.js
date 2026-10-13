// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Project Defect", {
	refresh(frm) {
		if (!frm.is_new() && frm.doc.requires_materials && !frm.doc.material_request) {
			frm.add_custom_button(__("Material Request"), () => {
				frappe.model.open_mapped_doc({
					method: "project_management_muhick.muhick_projects.doctype.project_defect.project_defect.make_material_request",
					frm: frm,
				});
			}, __("Create"));
		}
	},
});
