// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Project Activity Plan", {
	setup(frm) {
		frm.set_query("item_code", "items", () => ({ filters: { disabled: 0 } }));
	},

	refresh(frm) {
		set_phase_options(frm);
		if (frm.doc.docstatus === 1 && frm.doc.is_current) {
			frm.add_custom_button(__("Revise Plan"), () => {
				frappe.model.open_mapped_doc({
					method: "project_management_muhick.muhick_projects.doctype.project_activity_plan.project_activity_plan.make_revision",
					frm: frm,
				});
			});
		}
		if (frm.doc.docstatus === 0 && frm.doc.project && !frm.doc.revision_of) {
			frm.add_custom_button(__("Get Phases"), () => get_phases(frm));
		}
	},

	project(frm) {
		set_phase_options(frm);
	},
});

frappe.ui.form.on("Project Activity Plan Phase", {
	phase_name: set_phase_options,
	phases_remove: set_phase_options,
});

// the phase columns of the activity and item tables offer only this plan's phases
function set_phase_options(frm) {
	const names = ["", ...(frm.doc.phases || []).map((r) => r.phase_name).filter(Boolean)];
	["activities", "items"].forEach((table) => {
		frm.fields_dict[table].grid.update_docfield_property("phase_name", "options", names);
	});
}

// load the phases and their activities from a Project Template, or from the project's own phase tasks
function get_phases(frm) {
	frappe.prompt(
		[
			{
				fieldname: "project_template",
				fieldtype: "Link",
				options: "Project Template",
				label: __("Project Template"),
				description: __("Leave empty to use the phase tasks the project already has."),
			},
		],
		(values) => {
			frappe
				.xcall("project_management_muhick.muhick_projects.doctype.project_activity_plan.project_activity_plan.load_phases", {
					project: frm.doc.project,
					project_template: values.project_template || null,
				})
				.then((r) => {
					if (!r.phases.length) {
						frappe.msgprint(__("No phases found. Add the phases in the table, or set up a Project Template."));
						return;
					}
					frm.clear_table("phases");
					frm.clear_table("activities");
					r.phases.forEach((row) => frm.add_child("phases", row));
					r.activities.forEach((row) => frm.add_child("activities", row));
					frm.refresh_fields();
					set_phase_options(frm);
					frm.dirty();
				});
		},
		__("Get Phases"),
		__("Load")
	);
}
