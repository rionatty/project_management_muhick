// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Project Budget", {
	setup(frm) {
		frm.set_query("cost_code", "lines", () => ({ filters: { disabled: 0 } }));
		frm.set_query("item_code", "lines", () => ({ filters: { disabled: 0 } }));
		frm.set_query("phase", "lines", () => muhick.phase_filters(frm.doc.project));
		// an activity is a child task of the line's phase
		frm.set_query("activity", "lines", (doc, cdt, cdn) => {
			const row = locals[cdt][cdn];
			return { filters: { project: frm.doc.project || "", parent_task: row.phase || "", status: ["!=", "Cancelled"] } };
		});
		frm.set_query("boq", () => ({ filters: { project: frm.doc.project || "", docstatus: 1 } }));
	},

	refresh(frm) {
		show_phase_summary(frm);
		if (frm.doc.docstatus === 0 && frm.doc.project) {
			frm.add_custom_button(__("Get Items from Activity Plan"), () => get_plan_items(frm));
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
});

frappe.ui.form.on("Project Budget Line", {
	qty: (frm, cdt, cdn) => muhick.set_row_amount(cdt, cdn),
	rate: (frm, cdt, cdn) => muhick.set_row_amount(cdt, cdn),
	amount: show_phase_summary,
	phase: show_phase_summary,
	lines_remove: show_phase_summary,
});

frappe.ui.form.on("Project Budget Cost Code", {
	// entering an estimate to complete switches the cost code to a manual forecast
	estimate_to_complete: (frm, cdt, cdn) => frappe.model.set_value(cdt, cdn, "etc_is_manual", 1),
});

// lines for the items of the approved activity plan, skipping items already budgeted in that phase
function get_plan_items(frm) {
	frappe
		.xcall("project_management_muhick.muhick_projects.doctype.project_budget.project_budget.get_plan_items", {
			project: frm.doc.project,
		})
		.then((rows) => {
			(frm.doc.lines || []).filter((r) => !r.item_code).forEach((r) => frappe.model.clear_doc(r.doctype, r.name));
			const present = new Set((frm.doc.lines || []).map((r) => `${r.phase || ""}|${r.item_code}`));
			const added = rows.filter((row) => !present.has(`${row.phase || ""}|${row.item_code}`));
			added.forEach((row) => frm.add_child("lines", { ...row, amount: flt(row.qty) * flt(row.rate) }));
			frm.refresh_field("lines");
			show_phase_summary(frm);
			frappe.show_alert({
				message: added.length
					? __("{0} line(s) added. Check the rates and cost codes.", [added.length])
					: __("Every item of the plan is already in the budget."),
				indicator: added.length ? "green" : "orange",
			});
		});
}

// the budget totalled by phase, below the lines
function show_phase_summary(frm) {
	const totals = {};
	(frm.doc.lines || []).forEach((r) => {
		totals[r.phase || ""] = (totals[r.phase || ""] || 0) + flt(r.amount);
	});
	const phases = Object.keys(totals).filter(Boolean);
	const render = (names) => {
		const rows = Object.keys(totals)
			.sort((a, b) => (a ? 0 : 1) - (b ? 0 : 1))
			.map((key) => {
				const label = key ? names[key] || key : __("No phase");
				const amount = format_currency(totals[key], frm.doc.currency);
				return `<tr><td>${frappe.utils.escape_html(label)}</td><td class="text-right">${amount}</td></tr>`;
			})
			.join("");
		frm.get_field("phase_summary").$wrapper.html(
			rows ? `<table class="table table-bordered table-condensed"><tbody>${rows}</tbody></table>` : ""
		);
	};
	if (!phases.length) {
		render({});
		return;
	}
	frappe.db.get_list("Task", { filters: { name: ["in", phases] }, fields: ["name", "subject"] }).then((tasks) => {
		const names = {};
		tasks.forEach((t) => (names[t.name] = t.subject));
		render(names);
	});
}
