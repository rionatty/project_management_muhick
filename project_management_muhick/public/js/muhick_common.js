// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

// Small helpers shared by the Muhick forms. Loaded on every desk page (see hooks.py).
frappe.provide("muhick");

// keep amount = qty x rate on a child row
muhick.set_row_amount = function (cdt, cdn, qty_field, rate_field, amount_field) {
	const row = locals[cdt][cdn];
	const amount = flt(row[qty_field || "qty"]) * flt(row[rate_field || "rate"]);
	frappe.model.set_value(cdt, cdn, amount_field || "amount", amount);
};

// a milestone (phase) is a group task of the project
muhick.phase_filters = function (project) {
	return { filters: { project: project || "", is_group: 1, status: ["!=", "Cancelled"] } };
};

// limit milestone and cost code pickers to what belongs to the form's project
muhick.set_project_queries = function (frm, tables) {
	if (frm.fields_dict.phase) {
		frm.set_query("phase", () => muhick.phase_filters(frm.doc.project));
	}
	if (frm.fields_dict.cost_code) {
		frm.set_query("cost_code", () => ({ filters: { disabled: 0 } }));
	}
	(tables || []).forEach((table) => {
		frm.set_query("cost_code", table, () => ({ filters: { disabled: 0 } }));
	});
};

// run a whitelisted method of the open document, then reload it
muhick.run = function (frm, method, args) {
	return frm.call(method, args || {}).then(() => frm.reload_doc());
};

// ask for some values, then run a document method with them
muhick.prompt_and_run = function (frm, title, fields, method) {
	frappe.prompt(fields, (values) => muhick.run(frm, method, values), title);
};
