// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

// a budget is laid out as the bid's cost estimate: its tabs, tables and summaries, and its lines' amounts, are
// muhick.sheets and muhick.cost_lines (muhick_common.bundle.js), shared with it
frappe.ui.form.on("Project Budget", {
	setup(frm) {
		muhick.sheets.setup(frm);
		muhick.cost_lines.tables().forEach((table) => {
			frm.set_query("phase", table, () => muhick.phase_filters(frm.doc.project));
			// an activity is a task under the line's milestone, however deep
			frm.set_query("activity", table, (doc, cdt, cdn) => {
				const row = locals[cdt][cdn];
				const under = row.phase ? { name: ["descendants of", row.phase], is_group: 0 } : { parent_task: "" };
				return { filters: { project: frm.doc.project || "", status: ["!=", "Cancelled"], ...under } };
			});
		});
		frm.set_query("boq", () => ({ filters: { project: frm.doc.project || "", docstatus: 1 } }));
	},

	refresh(frm) {
		frm.__cost_settings = null;
		frm.trigger("render_estimate");
		const group = __("Budget Lines");
		const draft = frm.doc.docstatus === 0 && frm.perm[0].write;
		if (draft) {
			frm.add_custom_button(__("Upload from Excel"), () => muhick.cost_lines.upload(frm), group);
		}
		frm.add_custom_button(__("Download Excel"), () => muhick.cost_lines.download(frm), group);
		if (draft && frm.doc.project) {
			frm.add_custom_button(__("Get Lines from the Bid Estimate"), () => get_lines(frm, "estimate"), group);
			frm.add_custom_button(__("Get Items from Activity Plan"), () => get_lines(frm, "plan"), group);
		}
		if (draft) {
			frm.add_custom_button(__("Get Imported Goods"), () => muhick.sheets.get_imported_goods(frm), group);
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

	render_estimate: muhick.sheets.render,
	contract_value: (frm) => frm.trigger("render_estimate"),
	project: start_from_bid,
});

frappe.ui.form.on("Project Budget Cost Code", {
	// entering an estimate to complete switches the cost code to a manual forecast
	estimate_to_complete: (frm, cdt, cdn) => frappe.model.set_value(cdt, cdn, "etc_is_manual", 1),
});

const BID_LINES = "project_management_muhick.muhick_projects.estimate.get_estimate_lines";

// a new budget starts from all its project's bid has, with no button to press. Lines typed or uploaded first stay;
// another project picked starts over.
function start_from_bid(frm) {
	const project = frm.doc.project;
	if (!frm.is_new() || !project || frm.__started_from === project) {
		return;
	}
	const tables = [...muhick.cost_lines.tables(), "muhick_import_taxes"];
	if (tables.some((table) => (frm.doc[table] || []).length)) {
		if (!frm.__started_from) {
			return;
		}
		tables.forEach((table) => {
			frm.clear_table(table);
			frm.refresh_field(table);
		});
		frm.doc.boq = frm.doc.remarks = null;
		frm.refresh_fields(["boq", "remarks"]);
		frm.trigger("render_estimate");
	}
	frm.__started_from = null;
	frappe.xcall(BID_LINES, { project, quiet: 1 }).then((result) => {
		if (result.bid && frm.doc.project === project) {
			frm.__started_from = project;
			add_lines(frm, result);
		}
	});
}

// lines from the won bid, or for the items of the approved activity plan
function get_lines(frm, source) {
	const method = source === "estimate" ? BID_LINES : "project_management_muhick.muhick_projects.doctype.project_budget.project_budget.get_plan_items";
	frappe.xcall(method, { project: frm.doc.project }).then((result) => add_lines(frm, result));
}

// lines and goods not yet in the budget, each to its tab; from a bid, also the contract value, the project's BOQ and
// where they came from
function add_lines(frm, result) {
	const key = (r) => [r.stage || "", r.item_code || "", r.item_code ? "" : r.description || ""].join("|");
	const rows = result.lines || result;
	const lines = muhick.cost_lines.rows(frm);
	lines.filter((r) => !r.item_code && !r.description).forEach((r) => frappe.model.clear_doc(r.doctype, r.name));
	const present = new Set(muhick.cost_lines.rows(frm).map(key));
	const added = rows.filter((row) => !present.has(key(row)));
	const goods_present = new Set((frm.doc.muhick_import_taxes || []).map(key));
	const goods = (result.goods || []).filter((good) => !goods_present.has(key(good)));
	return frappe
		.run_serially(
			result.bid
				? [
						() => frm.set_value("contract_value", result.contract_value),
						() => result.boq && frm.set_value("boq", result.boq, true),
						() => frm.set_value("remarks", __("From the cost estimate of bid {0}.", [result.bid]), true),
				  ]
				: []
		)
		.then(() => {
			goods.forEach((good) => frm.add_child("muhick_import_taxes", good));
			frm.refresh_field("muhick_import_taxes");
			return muhick.cost_lines.add_rows(frm, added);
		})
		.then(() => {
			const counted = result.bid
				? __("{0} line(s) and {1} imported good(s) came from bid {2}. Check the rates and cost codes.", [added.length, goods.length, result.bid])
				: __("{0} line(s) added. Check the rates and cost codes.", [added.length]);
			frappe.show_alert({
				message: added.length || goods.length ? counted : __("Every line is already in the budget."),
				indicator: added.length || goods.length ? "green" : "orange",
			});
		});
}
