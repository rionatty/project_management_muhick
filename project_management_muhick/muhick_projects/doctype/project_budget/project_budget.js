// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Project Budget", {
	setup(frm) {
		frm.set_query("cost_code", "lines", () => ({ filters: { disabled: 0 } }));
		frm.set_query("milestone", "lines", () => ({ filters: { project: frm.doc.project || "" } }));
		frm.set_query("boq", () => ({ filters: { project: frm.doc.project || "", docstatus: 1 } }));
	},

	refresh(frm) {
		if (frm.doc.docstatus !== 1) {
			return;
		}
		frm.add_custom_button(__("Update Position"), () => {
			frappe
				.call({
					method: "project_management_muhick.muhick_projects.budget_engine.recalculate",
					args: { project: frm.doc.project },
					freeze: true,
				})
				.then(() => frm.reload_doc());
		});
		frm.add_custom_button(
			__("Budget Revision"),
			() => frappe.new_doc("Project Budget Revision", { project: frm.doc.project }),
			__("Create")
		);
		frm.add_custom_button(
			__("Project Cost Report"),
			() => frappe.set_route("query-report", "Project Cost Report", { project: frm.doc.project }),
			__("View")
		);
	},
});

frappe.ui.form.on("Project Budget Line", {
	qty: (frm, cdt, cdn) => muhick.set_row_amount(cdt, cdn),
	rate: (frm, cdt, cdn) => muhick.set_row_amount(cdt, cdn),
});

frappe.ui.form.on("Project Budget Cost Code", {
	// entering an estimate to complete switches the cost code to a manual forecast
	estimate_to_complete: (frm, cdt, cdn) => frappe.model.set_value(cdt, cdn, "etc_is_manual", 1),
});
