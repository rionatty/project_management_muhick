// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

// a line's amount and the summary by stage come from muhick.cost_lines (muhick_common.js), shared with
// the bid's cost estimate
frappe.ui.form.on("Project Budget", {
	setup(frm) {
		frm.set_query("cost_code", "lines", () => ({ filters: { disabled: 0 } }));
		frm.set_query("item_code", "lines", () => ({ filters: { disabled: 0 } }));
		frm.set_query("phase", "lines", () => muhick.phase_filters(frm.doc.project));
		// an activity is a task of the line's milestone
		frm.set_query("activity", "lines", (doc, cdt, cdn) => {
			const row = locals[cdt][cdn];
			return { filters: { project: frm.doc.project || "", parent_task: row.phase || "", status: ["!=", "Cancelled"] } };
		});
		frm.set_query("boq", () => ({ filters: { project: frm.doc.project || "", docstatus: 1 } }));
	},

	refresh(frm) {
		muhick.cost_lines.render_summary(frm);
		if (frm.doc.docstatus === 0 && frm.doc.project) {
			frm.add_custom_button(__("Get Lines from the Bid Estimate"), () => get_lines(frm, "estimate"));
			frm.add_custom_button(__("Get Items from Activity Plan"), () => get_lines(frm, "plan"));
		}
		if (!frm.is_new()) {
			frm.add_custom_button(
				__("Cash Plan by Month"),
				() => frappe.set_route("query-report", "Budget Cash Plan", { project: frm.doc.project }),
				__("View")
			);
		}
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

	contract_value: (frm) => muhick.cost_lines.render_summary(frm),
});

frappe.ui.form.on("Project Budget Cost Code", {
	// entering an estimate to complete switches the cost code to a manual forecast
	estimate_to_complete: (frm, cdt, cdn) => frappe.model.set_value(cdt, cdn, "etc_is_manual", 1),
});

// lines from the won bid's cost estimate, or for the items of the approved activity plan, skipping lines
// already in the budget
function get_lines(frm, source) {
	const method =
		source === "estimate"
			? "project_management_muhick.muhick_projects.estimate.get_estimate_lines"
			: "project_management_muhick.muhick_projects.doctype.project_budget.project_budget.get_plan_items";
	const key = (r) => [r.stage || "", r.item_code || "", r.item_code ? "" : r.description || ""].join("|");
	frappe.xcall(method, { project: frm.doc.project }).then((rows) => {
		(frm.doc.lines || []).filter((r) => !r.item_code && !r.description).forEach((r) => frappe.model.clear_doc(r.doctype, r.name));
		const present = new Set((frm.doc.lines || []).map(key));
		const added = rows.filter((row) => !present.has(key(row)));
		muhick.cost_lines.add_rows(frm, added).then(() =>
			frappe.show_alert({
				message: added.length
					? __("{0} line(s) added. Check the rates and cost codes.", [added.length])
					: __("Every line is already in the budget."),
				indicator: added.length ? "green" : "orange",
			})
		);
	});
}
