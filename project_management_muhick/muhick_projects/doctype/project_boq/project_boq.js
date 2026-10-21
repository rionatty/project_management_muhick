// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Project BOQ", {
	setup(frm) {
		// stock and non-stock items alike
		frm.set_query("item_code", "items", () => ({ filters: { disabled: 0 } }));
	},

	refresh(frm) {
		show_stage_summary(frm);
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Refresh Quantities"), () =>
				frappe
					.xcall("project_management_muhick.muhick_projects.doctype.project_boq.project_boq.refresh_quantities", {
						boq: frm.doc.name,
					})
					.then(() => frm.reload_doc())
			);
			frm.add_custom_button(
				__("Project Budget"),
				() => frappe.new_doc("Project Budget", { project: frm.doc.project, boq: frm.doc.name }),
				__("Create")
			);
		}
	},
});

frappe.ui.form.on("Project BOQ Item", {
	qty: (frm, cdt, cdn) => muhick.set_row_amount(cdt, cdn),
	rate: (frm, cdt, cdn) => muhick.set_row_amount(cdt, cdn),
	amount: show_stage_summary,
	milestone: show_stage_summary,
	items_remove: show_stage_summary,
});

// one row per milestone (stage): BOQ value, and what has been certified, requested, purchased and
// consumed so far, valued at the BOQ rate, with each as a share of the stage's BOQ value
function show_stage_summary(frm) {
	const measures = [
		["amount", null],
		["certified", "certified_qty"],
		["requested", "requested_qty"],
		["purchased", "purchased_qty"],
		["consumed", "consumed_qty"],
	];
	const stages = {};
	const total = { lines: 0 };
	(frm.doc.items || []).forEach((r) => {
		const stage = (stages[r.milestone || ""] = stages[r.milestone || ""] || { lines: 0 });
		[stage, total].forEach((t) => {
			t.lines += 1;
			measures.forEach(([key, qty_field]) => {
				const value = qty_field ? flt(r[qty_field]) * flt(r.rate) : flt(r.amount);
				t[key] = (t[key] || 0) + value;
			});
		});
	});
	const field = frm.get_field("stage_summary");
	const keys = Object.keys(stages);
	if (!keys.length) {
		field.$wrapper.html("");
		return;
	}
	const money = (v) => format_currency(v || 0, frm.doc.currency);
	const share = (part, whole) => (whole ? ` <span class="text-muted">(${Math.round((flt(part) / whole) * 100)}%)</span>` : "");
	const cells = (t) =>
		`<td class="text-right">${t.lines}</td><td class="text-right">${money(t.amount)}</td>` +
		measures
			.slice(1)
			.map(([key]) => `<td class="text-right">${money(t[key])}${share(t[key], t.amount)}</td>`)
			.join("");
	const rows = keys
		.sort((a, b) => (a ? 0 : 1) - (b ? 0 : 1))
		.map((key) => `<tr><td>${frappe.utils.escape_html(key || __("No milestone"))}</td>${cells(stages[key])}</tr>`)
		.join("");
	const head = [__("Milestone / Phase"), __("Lines"), __("BOQ Amount"), __("Certified"), __("Requested"), __("Purchased"), __("Consumed")];
	field.$wrapper.html(
		`<table class="table table-bordered table-condensed"><thead><tr>${head
			.map((h, i) => `<th${i ? ' class="text-right"' : ""}>${h}</th>`)
			.join("")}</tr></thead><tbody>${rows}</tbody>` +
			`<tfoot><tr><th>${__("Total")}</th>${cells(total).replace(/<td/g, "<th").replace(/<\/td>/g, "</th>")}</tr></tfoot></table>`
	);
}
