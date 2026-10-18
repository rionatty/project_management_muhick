// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Subcontract Agreement", {
	setup(frm) {
		muhick.set_project_queries(frm);
		frm.set_query("phase", "milestones", () => muhick.phase_filters(frm.doc.project));
	},

	refresh(frm) {
		if (frm.doc.docstatus !== 1 || frm.doc.status !== "Active") {
			return;
		}
		frm.add_custom_button(
			__("Service Receipt Note"),
			() => frappe.new_doc("Service Receipt Note", { subcontract_agreement: frm.doc.name }),
			__("Create")
		);
		frm.add_custom_button(
			__("Retention Release"),
			() =>
				frappe.new_doc("Retention Release", {
					retention_for: "Subcontractor",
					project: frm.doc.project,
					subcontract_agreement: frm.doc.name,
				}),
			__("Create")
		);
		frm.add_custom_button(__("Complete Agreement"), () => {
			frappe.confirm(__("Close this subcontract? Its performance rating will be kept for future evaluations."), () => {
				// save the rating first so the server sees it
				const complete = () => muhick.run(frm, "complete");
				frm.is_dirty() ? frm.save("Update").then(complete) : complete();
			});
		});
	},
});
