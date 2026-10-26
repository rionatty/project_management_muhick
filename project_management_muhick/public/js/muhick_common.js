// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

// Small helpers shared by the Muhick forms. Loaded on every desk page (see hooks.py).
frappe.provide("muhick");

// On a document, every button its form adds to the header, and every group of them (Create, View...),
// is a primary button like Save, so they all take its colour whatever the theme
(() => {
	const page = frappe.ui && frappe.ui.Page && frappe.ui.Page.prototype;
	if (!page) {
		return;
	}
	const on_document = () => {
		const route = frappe.router && frappe.router.current_route;
		return Boolean(route && route[0] === "Form");
	};
	const add_inner_button = page.add_inner_button;
	page.add_inner_button = function (label, action, group, type = "default", align_right = false) {
		return add_inner_button.call(this, label, action, group, type === "default" && on_document() ? "primary" : type, align_right);
	};
	const get_or_add_inner_group_button = page.get_or_add_inner_group_button;
	page.get_or_add_inner_group_button = function (label, align_right) {
		const $group = get_or_add_inner_group_button.call(this, label, align_right);
		if (on_document()) {
			$group.children("button").removeClass("btn-default").addClass("btn-primary");
		}
		return $group;
	};
})();

// where an approved request stands on the weekly payment plan, from which its funds are issued
muhick.show_payment_schedule = function (frm) {
	frappe
		.xcall("project_management_muhick.muhick_finance.doctype.payment_plan.payment_plan.get_payment_schedule", {
			doctype: frm.doctype,
			name: frm.doc.name,
		})
		.then((line) => {
			if (!line) {
				frm.set_intro(__("Approved. It goes on the next weekly payment plan, and its funds are issued from there."), "blue");
				return;
			}
			const plan = frappe.utils.get_form_link("Payment Plan", line.plan, true);
			if (line.line_status === "Held") {
				frm.set_intro(__("Held on payment plan {0}: {1}", [plan, frappe.utils.escape_html(line.hold_reason || "")]), "orange");
				return;
			}
			frm.set_intro(
				__("On payment plan {0} for {1} to {2}: {3}, {4}.", [
					plan,
					frappe.datetime.str_to_user(line.period_from),
					frappe.datetime.str_to_user(line.period_to),
					format_currency(line.approved_amount || line.proposed_amount),
					__(line.line_status).toLowerCase(),
				]),
				"blue"
			);
		});
};

// an opportunity's status (where the sale stands) as a coloured tag, on the opportunity list and at the
// top of the opportunity; its bid status is a column of the list and opens the Bid tab
muhick.opportunity_status_indicator = function (doc) {
	const colours = { Open: "orange", Won: "green", Quotation: "cyan", Converted: "blue", Lost: "red", Closed: "gray" };
	if (!doc.status) {
		return null;
	}
	return [__(doc.status), colours[doc.status] || "gray", "status,=," + doc.status];
};

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

// {task name: subject} for milestones shown in a summary
muhick.milestone_names = function (names) {
	if (!names.length) {
		return Promise.resolve({});
	}
	return frappe.db.get_list("Task", { filters: { name: ["in", names] }, fields: ["name", "subject"] }).then((tasks) => {
		const out = {};
		tasks.forEach((t) => (out[t.name] = t.subject));
		return out;
	});
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
