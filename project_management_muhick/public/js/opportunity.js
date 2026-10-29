// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Opportunity", {
	setup(frm) {
		frm.set_query("milestone", "muhick_milestones", () => ({ filters: { disabled: 0 } }));
		frm.set_query("cost_code", "muhick_estimate", () => ({ filters: { disabled: 0 } }));
		frm.set_query("item_code", "muhick_estimate", () => ({ filters: { disabled: 0 } }));
		// "Sales" stays only as ERPNext's fallback; the types of work are the business's own
		frm.set_query("opportunity_type", () => ({ filters: { name: ["!=", "Sales"] } }));
		// from a qualified lead or an existing customer, not from a prospect
		frm.set_query("opportunity_from", () => ({ filters: { name: ["in", ["Lead", "Customer"]] } }));
	},

	onload(frm) {
		if (!frm.is_new()) {
			return;
		}
		follow_milestone_list(frm);
		// instead of ERPNext's "Sales", the type of work comes from the lead or is chosen
		if (frm.doc.opportunity_type === undefined) {
			frm.doc.opportunity_type = "";
		}
		if (frm.doc.opportunity_from === "Lead" && frm.doc.party_name && !frm.doc.opportunity_type) {
			frappe.db.get_value("Lead", frm.doc.party_name, "request_type").then((r) => {
				if (r.message && r.message.request_type) {
					frm.set_value("opportunity_type", r.message.request_type);
				}
			});
		}
	},

	refresh(frm) {
		toggle_bid_price(frm);
		setup_estimate(frm);
		// the milestones start from the list and are the opportunity's own: Reset to the List goes back to it
		const milestones = frm.fields_dict.muhick_milestones.grid;
		milestones.clear_custom_buttons();
		if (!frm.is_new() && frm.perm[0].write) {
			milestones.add_custom_button(__("Reset to the List"), () =>
				frappe.confirm(
					__("Replace this opportunity's milestones with those of the Opportunity Milestones list? Statuses set by hand go back to following the record."),
					() =>
						frappe
							.xcall("project_management_muhick.overrides.crm.reset_milestones", { opportunity: frm.doc.name })
							.then(() => frm.reload_doc())
				)
			);
		}
		if (frm.is_new()) {
			return;
		}
		// the tag at the top shows where the sale stands; where the tender stands opens the Bid tab
		const indicator = muhick.opportunity_status_indicator && muhick.opportunity_status_indicator(frm.doc);
		if (indicator) {
			frm.page.set_indicator(indicator[0], indicator[1]);
		}
		replace_close_and_reopen(frm);
		if ((frm.doc.items || []).length) {
			frm.add_custom_button(
				__("Supplier Comparison"),
				() => frappe.set_route("query-report", "Bid Margin Comparison", { opportunity: frm.doc.name }),
				__("View")
			);
		}
		if (["Lost", "Closed"].includes(frm.doc.status)) {
			return;
		}
		const create = (label, method) => {
			frm.add_custom_button(label, () => frappe.model.open_mapped_doc({ method: method, frm: frm }), __("Create"));
		};
		create(__("Sales Requisition"), "project_management_muhick.overrides.crm.make_sales_requisition");
		if (frm.doc.muhick_bid_security_required && !frm.doc.muhick_bid_security) {
			// approved by the Finance Manager, after which Finance issues the funds for it
			create(__("Bid Security Request"), "project_management_muhick.overrides.crm.make_bid_security_request");
		}
		show_outcome(frm);
		show_preparation(frm);
	},
});

frappe.ui.form.on("Opportunity Item", {
	items_add: toggle_bid_price,
	items_remove: toggle_bid_price,
});

frappe.ui.form.on("Opportunity Milestone Line", {
	// a status chosen here is set by hand: it stays as set, reached on the day given
	status(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.reached_when !== "Ticked by Hand" && !row.set_by_hand) {
			frappe.model.set_value(cdt, cdn, "set_by_hand", 1);
		}
		frappe.model.set_value(cdt, cdn, "reached_on", row.status === "Reached" ? row.reached_on || frappe.datetime.get_today() : null);
	},
});

// a new opportunity shows the milestones of the list at once, with their weights, to be adjusted before
// it is saved
function follow_milestone_list(frm) {
	if ((frm.doc.muhick_milestones || []).some((r) => r.milestone)) {
		return;
	}
	frappe.db
		.get_list("Opportunity Milestone", {
			filters: { disabled: 0 },
			fields: ["name", "weight", "reached_when"],
			order_by: "sequence asc, name asc",
			limit: 0,
		})
		.then((milestones) => {
			frm.clear_table("muhick_milestones");
			milestones.forEach((m) =>
				frm.add_child("muhick_milestones", { milestone: m.name, weight: m.weight, reached_when: m.reached_when, status: "Pending" })
			);
			frm.refresh_field("muhick_milestones");
		});
}

// at the top of a bid still being prepared: when it is due, and the documents on its checklist overdue,
// not started or in progress
function show_preparation(frm) {
	if (!["Qualified", "In Preparation"].includes(frm.doc.sales_stage)) {
		return;
	}
	const lines = [];
	let colour = "blue";
	if (frm.doc.muhick_submission_deadline) {
		const days = frappe.datetime.get_day_diff(frm.doc.muhick_submission_deadline, frappe.datetime.now_datetime());
		if (days <= 3) {
			lines.push(__("Submission is due in {0} day(s).", [Math.max(days, 0)]));
			colour = days < 0 ? "red" : "orange";
		}
	}
	const checklist = frm.doc.muhick_checklist || [];
	const today = frappe.datetime.get_today();
	const names = (rows) => rows.map((r) => frappe.utils.escape_html(r.document_type)).join(", ");
	const waiting = checklist.filter((r) => r.status !== "Ready");
	const overdue = waiting.filter((r) => r.due_date && r.due_date < today);
	const on_time = waiting.filter((r) => !overdue.includes(r));
	const not_started = on_time.filter((r) => !r.status || r.status === "Pending");
	const in_progress = on_time.filter((r) => r.status === "In Progress");
	if (overdue.length) {
		lines.push(__("Overdue: {0}.", [names(overdue)]));
		colour = "red";
	}
	if (not_started.length) {
		lines.push(__("Not started: {0}.", [names(not_started)]));
		colour = colour === "blue" ? "orange" : colour;
	}
	if (in_progress.length) {
		lines.push(__("In progress: {0}.", [names(in_progress)]));
	}
	// what else keeps the bid from going in: a part with no document, and requirements not answered
	const parts = ["Administrative", "Technical", "Financial"].filter((part) => !checklist.some((r) => r.part === part));
	if (parts.length) {
		lines.push(__("No {0} document on the checklist.", [parts.map((p) => __(p).toLowerCase()).join(", ")]));
		colour = colour === "blue" ? "orange" : colour;
	}
	const unanswered = (frm.doc.muhick_requirements || []).filter((r) => !r.compliance || r.compliance === "Clarification Needed");
	if (unanswered.length) {
		lines.push(__("Requirements and Compliance, row {0}: answer Complies or Deviation.", [unanswered.map((r) => r.idx).join(", ")]));
		colour = colour === "blue" ? "orange" : colour;
	}
	if (checklist.length && !waiting.length && !parts.length && !unanswered.length) {
		lines.push(__("Every document on the checklist is ready."));
		colour = colour === "blue" ? "green" : colour;
	}
	if (lines.length) {
		frm.set_intro(lines.join("<br>"), colour);
	}
}

// with BOQ lines, the bid price is their total
function toggle_bid_price(frm) {
	frm.toggle_enable("opportunity_amount", !(frm.doc.items || []).length);
}

// the cost estimate: its summary by stage, and the lines it can take from the BOQ, the bid's supplier
// quotations and the import costs of its imported lines
function setup_estimate(frm) {
	if (!frm.fields_dict.muhick_estimate) {
		return; // until the site is migrated
	}
	muhick.cost_lines.render_summary(frm);
	const grid = frm.fields_dict.muhick_estimate.grid;
	grid.clear_custom_buttons();
	muhick.cost_lines.excel_buttons(frm, frm.perm[0].write);
	if (frm.is_new() || !frm.perm[0].write) {
		return;
	}
	grid.add_custom_button(__("Get Lines from the BOQ"), () => get_boq_lines(frm));
	grid.add_custom_button(__("Get Supplier Prices"), () => get_supplier_prices(frm));
	grid.add_custom_button(__("Add Import Costs"), () => add_import_costs(frm));
}

function get_boq_lines(frm) {
	const present = new Set((frm.doc.muhick_estimate || []).map((r) => `${r.stage || ""}|${r.item_code || ""}`));
	const items = (frm.doc.items || [])
		.filter((r) => r.item_code && !present.has(`${r.muhick_stage || ""}|${r.item_code}`))
		.map((r) => [r.item_code, r.uom, r.qty, r.muhick_stage]);
	if (!items.length) {
		frappe.show_alert({ message: __("Every BOQ item is already in the estimate."), indicator: "orange" });
		return;
	}
	frappe.xcall("project_management_muhick.muhick_projects.estimate.get_boq_lines", { opportunity: frm.doc.name, items }).then((rows) =>
		muhick.cost_lines.add_rows(frm, rows).then(() =>
			frappe.show_alert({
				message: __("{0} line(s) added from the BOQ. Check their rates and cost codes, then add labour, tools and administration.", [
					rows.length,
				]),
				indicator: "green",
			})
		)
	);
}

// each line with an item at the lowest valid quotation for the bid, in a currency the estimate already
// uses at its rate
function get_supplier_prices(frm) {
	const lines = (frm.doc.muhick_estimate || []).filter((r) => r.item_code);
	frappe
		.xcall("project_management_muhick.muhick_projects.estimate.get_supplier_prices", { opportunity: frm.doc.name, items: lines.map((r) => [r.item_code, r.uom]) })
		.then((prices) =>
			muhick.cost_lines.settings(frm).then((settings) => {
				let priced = 0;
				lines.forEach((row) => {
					const price = prices[`${row.item_code}|${row.uom || ""}`];
					if (!price) {
						return;
					}
					Object.assign(row, price, { rate_includes_vat: 0 });
					if (muhick.cost_lines.foreign(frm, row)) {
						row.exchange_rate = muhick.cost_lines.used_rate(frm, row) || row.exchange_rate;
					}
					row.amount = muhick.cost_lines.amount(frm, row, settings);
					priced += 1;
				});
				frm.dirty();
				frm.refresh_field("muhick_estimate");
				muhick.cost_lines.render_summary(frm);
				frappe.show_alert({
					message: priced
						? __("{0} line(s) priced from the supplier quotations for this bid.", [priced])
						: __("No supplier has quoted the estimate's items for this bid yet."),
					indicator: priced ? "green" : "orange",
				});
			})
		);
}

// insurance, freight, import duty and infrastructure levy on the goods of one supplier, from the
// estimate's lines marked International
function add_import_costs(frm) {
	const imported = (frm.doc.muhick_estimate || []).filter((r) => r.procurement_type === "International");
	if (!imported.length) {
		frappe.msgprint(__("Set the Procurement Type of the imported lines to International first; their import costs are worked out from them."));
		return;
	}
	const suppliers = [...new Set(imported.map((r) => r.supplier || ""))];
	const goods = (supplier) => imported.filter((r) => (r.supplier || "") === supplier);
	const currency = (lines) => {
		const foreign = [...new Set(lines.filter((r) => muhick.cost_lines.foreign(frm, r)).map((r) => r.currency))];
		return foreign.length === 1 ? lines.find((r) => r.currency === foreign[0]) : null;
	};
	muhick.cost_lines.settings(frm).then((settings) => {
		const dialog = new frappe.ui.Dialog({
			title: __("Add Import Costs"),
			fields: [
				{
					fieldname: "supplier",
					fieldtype: "Select",
					label: __("Goods From"),
					options: suppliers.map((s) => ({ value: s, label: s || __("Lines without a supplier") })),
					default: suppliers[0],
					onchange: () => show_goods(),
				},
				{ fieldname: "goods_value", fieldtype: "Currency", label: __("Value of the Goods"), read_only: 1 },
				{ fieldname: "freight", fieldtype: "Float", label: __("Freight") },
				{ fieldtype: "Column Break" },
				{ fieldname: "insurance_percent", fieldtype: "Percent", label: __("Insurance %"), default: settings.import_insurance_percent },
				{
					fieldname: "duty_percent",
					fieldtype: "Percent",
					label: __("Import Duty %"),
					default: settings.import_duty_percent,
					description: __("Zero for goods made in the East African Community"),
				},
				{ fieldname: "levy_percent", fieldtype: "Percent", label: __("Infrastructure Levy %"), default: settings.import_levy_percent },
			],
			primary_action_label: __("Add"),
			primary_action(values) {
				const lines = goods(values.supplier || "");
				const priced_in = currency(lines);
				const stages = lines.map((r) => r.stage).filter(Boolean);
				const stage = stages.sort((a, b) => stages.filter((s) => s === b).length - stages.filter((s) => s === a).length)[0];
				frappe
					.xcall("project_management_muhick.muhick_projects.estimate.get_import_costs", {
						goods_value: lines.reduce((sum, r) => sum + flt(r.amount), 0),
						freight: flt(values.freight) * (priced_in ? flt(priced_in.exchange_rate) || 1 : 1),
						insurance_percent: values.insurance_percent,
						duty_percent: values.duty_percent,
						levy_percent: values.levy_percent,
						stage: stage || null,
						supplier: values.supplier || null,
					})
					.then((rows) => muhick.cost_lines.add_rows(frm, rows))
					.then(() => dialog.hide());
			},
		});
		const show_goods = () => {
			const lines = goods(dialog.get_value("supplier") || "");
			const priced_in = currency(lines);
			dialog.set_value("goods_value", lines.reduce((sum, r) => sum + flt(r.amount), 0));
			dialog.set_df_property(
				"freight",
				"label",
				priced_in ? __("Freight ({0})", [priced_in.currency]) : __("Freight ({0})", [erpnext.get_currency(frm.doc.company)])
			);
		};
		dialog.show();
		show_goods();
	});
}

// the outcome report on its way to approval or, once the bid is in, Won and Lost to raise one: the
// Head of Sales and then the General Manager approve it before the bid is marked won or lost
function show_outcome(frm) {
	if (frm.doc.muhick_bid_outcome || !frappe.model.can_read("Bid Outcome")) {
		return;
	}
	frappe.db.get_value("Bid Outcome", { opportunity: frm.doc.name, docstatus: 0 }, ["name", "outcome", "status"]).then((r) => {
		const report = r.message || {};
		if (report.name) {
			frm.set_intro(
				__("Outcome report {0} ({1}) is {2}.", [
					frappe.utils.get_form_link("Bid Outcome", report.name, true),
					__(report.outcome),
					__(report.status).toLowerCase(),
				]),
				"blue"
			);
		} else if (["Submitted", "Under Evaluation"].includes(frm.doc.sales_stage) && frappe.model.can_create("Bid Outcome")) {
			const raise = (outcome) =>
				frappe.model.open_mapped_doc({
					method: "project_management_muhick.overrides.crm.make_bid_outcome",
					frm: frm,
					args: { outcome: outcome },
				});
			frm.add_custom_button(__("Won"), () => raise("Won"), __("Outcome"));
			frm.add_custom_button(__("Lost"), () => raise("Lost"), __("Outcome"));
		}
	});
}

// ERPNext adds Close and Reopen after this script has run. An opportunity is closed with the reason (a
// won one too, when the sale falls through) and reopened as it was; a won or lost bid is otherwise
// reopened only by cancelling its outcome report
function replace_close_and_reopen(frm) {
	setTimeout(() => {
		frm.remove_custom_button(__("Close"));
		frm.remove_custom_button(__("Reopen"));
		if (!frm.perm[0].write || frm.doc.sales_stage === "Outcome Pending Approval") {
			return;
		}
		if (["Open", "Won", "Quotation"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Close"), () =>
				frappe.prompt(
					{ fieldname: "reason", fieldtype: "Small Text", label: __("Why is the bid being closed?"), reqd: 1 },
					(values) => frm.set_value({ status: "Closed", muhick_outcome_notes: values.reason }).then(() => frm.save()),
					__("Close the Bid")
				)
			);
		} else if (frm.doc.status === "Closed") {
			const reopened = frm.doc.sales_stage === "Won" ? "Won" : "Open";
			frm.add_custom_button(__("Reopen"), () => frm.set_value("status", reopened).then(() => frm.save()));
		}
	});
}
