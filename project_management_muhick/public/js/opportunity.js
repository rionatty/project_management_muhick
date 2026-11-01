// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

// the sheets of the estimate are shared with the project budget (muhick_common.bundle.js)
const { taxes_of, tax_rates, rates_of, get_imported_goods, lines_of, esc, money, cell, company_currency } = muhick.sheets;

frappe.ui.form.on("Opportunity", {
	setup(frm) {
		frm.set_query("milestone", "muhick_milestones", () => ({ filters: { disabled: 0 } }));
		muhick.sheets.setup(frm);
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
		const checklist = frm.fields_dict.muhick_checklist.grid;
		checklist.clear_custom_buttons();
		if (frm.perm[0].write && ["Qualified", "In Preparation"].includes(frm.doc.sales_stage)) {
			checklist.add_custom_button(__("Add the Usual Documents"), () => add_usual_documents(frm));
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

frappe.ui.form.on("Opportunity", {
	render_estimate: muhick.sheets.render,
	// a quotation goes out with the BOQ's prices, so they must be there; a throw here stops ERPNext's create_quotation
	create_quotation(frm) {
		const lines = frm.doc.items || [];
		const unpriced = lines.filter((r) => !flt(r.rate)).map((r) => r.idx);
		if (!lines.length) {
			frappe.throw(__("A quotation is made from the BOQ. Add its lines on the BOQ tab first."));
		}
		if (unpriced.length) {
			frappe.throw(__("BOQ row {0} has no rate. Give it one, or use Cost Estimate > Set Bid Price.", [unpriced.join(", ")]));
		}
	},
	// a share of the contract value follows the bid price
	opportunity_amount(frm) {
		muhick.cost_lines
			.rows(frm)
			.filter((r) => flt(r.contract_percent))
			.forEach((r) => muhick.cost_lines.set_amount(frm, r.doctype, r.name));
		frm.trigger("render_estimate");
	},
	conversion_rate: (frm) => frm.trigger("opportunity_amount"),
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
	// the requirements and the site visit report the technical part also waits on (crm.technical_gaps)
	const requirements = frm.doc.muhick_requirements || [];
	const rows = (test) => requirements.filter(test).map((r) => r.idx).join(", ");
	const answered = (r) => r.compliance && r.compliance !== "Clarification Needed";
	const gaps = [
		[rows((r) => !answered(r)), __("answer Complies or Deviation")],
		[rows((r) => answered(r) && r.item_code && !r.data_sheet), __("attach the data sheet of the proposed item")],
		[rows((r) => r.compliance === "Deviation" && r.item_code && r.data_sheet && !r.deviation_sent_on), __("give the date the deviation was reported to the manufacturer")],
	]
		.filter(([idx]) => idx)
		.map(([idx, what]) => __("Requirements and Compliance, row {0}: {1}.", [idx, what]));
	if (frm.doc.muhick_site_visit_required && !frm.doc.muhick_site_visit_report) {
		gaps.push(__("Attach the site visit report."));
	}
	if (gaps.length) {
		lines.push(...gaps);
		colour = colour === "blue" ? "orange" : colour;
	}
	if (checklist.length && !waiting.length && !parts.length && !gaps.length) {
		lines.push(__("Every document on the checklist is ready."));
		colour = colour === "blue" ? "green" : colour;
	}
	if (lines.length) {
		frm.set_intro(lines.join("<br>"), colour);
	}
}

// the documents every bid needs (In Every Bid in the bid document list) that are not on the checklist, as a new
// bid starts with them
function add_usual_documents(frm) {
	frappe.db.get_list("Bid Document Type", { filters: { in_every_bid: 1 }, fields: ["name", "part"], limit: 0 }).then((types) => {
		const listed = new Set((frm.doc.muhick_checklist || []).map((r) => r.document_type));
		const missing = types.filter((t) => !listed.has(t.name));
		if (!missing.length) {
			frappe.msgprint(
				__("Every document marked In Every Bid is on the checklist already. The documents every bid needs are marked in the Bid Document Type list.")
			);
			return;
		}
		missing.forEach((t) => frm.add_child("muhick_checklist", { document_type: t.name, part: t.part, status: "Pending" }));
		frm.refresh_field("muhick_checklist");
		frm.dirty();
		frappe.show_alert({ message: __("Added {0}. Save to keep them.", [missing.map((t) => t.name).join(", ")]), indicator: "green" });
	});
}

// with BOQ lines, the bid price is their total
function toggle_bid_price(frm) {
	frm.toggle_enable("opportunity_amount", !(frm.doc.items || []).length);
}

function setup_estimate(frm) {
	if (!frm.fields_dict.muhick_equipment) {
		return; // until the site is migrated
	}
	frm.__cost_settings = null; // the rates as they are now in the settings
	frm.trigger("render_estimate");
	if (!frm.perm[0].write) {
		return;
	}
	const boq = frm.fields_dict.items.grid;
	boq.clear_custom_buttons();
	boq.add_custom_button(__("Get Lines from the Estimate"), () => get_estimate_lines(frm));
	const group = __("Cost Estimate");
	frm.add_custom_button(__("Upload from Excel"), () => muhick.cost_lines.upload(frm), group);
	frm.add_custom_button(__("Download Excel"), () => muhick.cost_lines.download(frm), group);
	if (frm.is_new()) {
		return;
	}
	frm.add_custom_button(__("Get Lines from the BOQ"), () => get_boq_lines(frm), group);
	frm.add_custom_button(__("Get Supplier Prices"), () => get_supplier_prices(frm), group);
	frm.add_custom_button(__("Get Imported Goods"), () => get_imported_goods(frm), group);
	if (frm.doc.status === "Open" && ["Qualified", "In Preparation"].includes(frm.doc.sales_stage)) {
		frm.add_custom_button(__("Apply Current Rates"), () => apply_current_rates(frm), group);
		frm.add_custom_button(__("Set Bid Price"), () => set_bid_price(frm), group);
	}
}

// the BOQ from the estimate's own tabs, chosen by the user: a line per item in each stage, the quantities of its estimate
// lines added up, so Set Bid Price can price it from their cost
function get_estimate_lines(frm) {
	const sections = muhick.cost_lines.sections;
	const tabs = Object.keys(sections).filter((table) => table !== "muhick_freight" && (frm.doc[table] || []).length);
	if (!tabs.length) {
		frappe.msgprint(__("The estimate has no lines yet."));
		return;
	}
	frappe.prompt(
		tabs.map((table) => ({
			fieldname: table,
			fieldtype: "Check",
			label: `${__(sections[table])} (${frm.doc[table].length})`,
			default: ["muhick_equipment", "muhick_materials"].includes(table) ? 1 : 0,
		})),
		(values) => add_estimate_lines(frm, tabs.filter((table) => values[table])),
		__("Get Lines from the Estimate"),
		__("Get Lines")
	);
}

// lines already in the BOQ stay as they are; a line with no item, or priced as a share of the contract value, is left out
function add_estimate_lines(frm, tables) {
	const key = (stage, item) => `${stage || ""}|${item}`;
	const present = new Set((frm.doc.items || []).map((r) => key(r.muhick_stage, r.item_code)));
	const lines = lines_of(frm, tables).filter((r) => !flt(r.contract_percent));
	const new_lines = new Map();
	lines
		.filter((r) => r.item_code && !present.has(key(r.stage, r.item_code)))
		.forEach((r) => {
			const line = `${key(r.stage, r.item_code)}|${r.uom || ""}`;
			if (!new_lines.has(line)) {
				new_lines.set(line, { item_code: r.item_code, description: r.description, uom: r.uom, muhick_stage: r.stage, qty: 0, rate: 0, amount: 0, base_rate: 0, base_amount: 0 });
			}
			new_lines.get(line).qty += flt(r.qty) * (cint(r.people) || 1);
		});
	new_lines.forEach((values) => frm.add_child("items", values));
	const no_item = lines.filter((r) => !r.item_code).length;
	const left_out = no_item ? __("{0} line(s) have no item yet and were left out: pick their items, then get the lines again.", [no_item]) : "";
	if (!new_lines.size) {
		frappe.msgprint(left_out || __("Every line is already in the BOQ."));
		return;
	}
	frm.refresh_field("items");
	toggle_bid_price(frm);
	frm.dirty();
	const added = __("{0} line(s) added to the BOQ. Save, then use Cost Estimate > Set Bid Price to price them.", [new_lines.size]);
	if (left_out) {
		frappe.msgprint(`${added}<br>${left_out}`);
	} else {
		frappe.show_alert({ message: added, indicator: "green" });
	}
}

function get_boq_lines(frm) {
	const present = new Set(muhick.cost_lines.rows(frm).map((r) => `${r.stage || ""}|${r.item_code || ""}`));
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
				message: __("{0} line(s) added from the BOQ to Equipment and Installation Materials. Check their rates, then add labour, tools and administration.", [
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
	const lines = muhick.cost_lines.rows(frm).filter((r) => r.item_code);
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
					Object.assign(row, price, { rate_includes_vat: 0, vat_percent: 0 });
					if (muhick.cost_lines.foreign(frm, row)) {
						row.exchange_rate = muhick.cost_lines.used_rate(frm, row) || row.exchange_rate;
					}
					row.amount = muhick.cost_lines.amount(frm, row, settings);
					row.quoted_amount = muhick.cost_lines.quoted(row);
					priced += 1;
				});
				frm.dirty();
				muhick.cost_lines.tables().forEach((table) => frm.refresh_field(table));
				frm.trigger("render_estimate");
				frappe.show_alert({
					message: priced
						? __("{0} line(s) priced from the supplier quotations for this bid.", [priced])
						: __("No supplier has quoted the estimate's items for this bid yet."),
					indicator: priced ? "green" : "orange",
				});
			})
		);
}

// today's rates on an open bid: each imported good at its item's rates, each line quoted with VAT at today's VAT
function apply_current_rates(frm) {
	frappe.confirm(__("Put today's tax rates on this bid's imported goods and today's VAT rate on its lines? Rates changed by hand on this bid are replaced."), () => {
		const goods = frm.doc.muhick_import_taxes || [];
		frm.__cost_settings = null;
		Promise.all([tax_rates(frm, goods.map((r) => r.item_code)), muhick.cost_lines.settings(frm)]).then(([rates, settings]) => {
			goods.forEach((row) => {
				Object.assign(row, rates_of(rates, row.item_code, row.country_of_origin));
				Object.assign(row, taxes_of(frm, row));
			});
			muhick.cost_lines.rows(frm).forEach((row) => {
				if (row.rate_includes_vat) {
					row.vat_percent = flt(settings.vat_percent);
					row.amount = muhick.cost_lines.amount(frm, row, settings);
				}
			});
			[...muhick.cost_lines.tables(), "muhick_import_taxes"].forEach((table) => frm.refresh_field(table));
			frm.dirty();
			frm.trigger("render_estimate");
			frappe.show_alert({ message: __("Today's rates applied. Save to keep them."), indicator: "green" });
		});
	});
}

// the bid price a target margin gives on the saved estimate, shown as the margin is typed, and set on the BOQ's rates
function set_bid_price(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Save first, so the price is worked out from the latest lines."));
		return;
	}
	const method = "project_management_muhick.muhick_projects.estimate.set_bid_price";
	const company = company_currency(frm);
	const show = () => {
		const margin_percent = dialog.get_value("margin_percent");
		const place = dialog.get_field("result").$wrapper;
		if (!flt(margin_percent)) {
			place.html("");
			return;
		}
		frappe.xcall(method, { opportunity: frm.doc.name, margin_percent }).then((r) => {
			const rows = [
				[__("Total Cost, without VAT"), money(r.cost, company)],
				[`<b>${__("Bid Price, without VAT")}</b>`, r.price ? `<b>${money(r.price, company)}</b>` : __("This margin leaves nothing for the costs")],
			];
			if ((frm.doc.items || []).length) {
				rows.push([__("BOQ lines it prices"), r.priced]);
			}
			if (r.unpriced.length) {
				rows.push([__("No cost in the estimate, so left as they are"), esc(r.unpriced.join(", "))]);
			}
			place.html(
				`<table class="table table-condensed"><tbody>` +
					rows.map(([label, value]) => `<tr><td>${label}</td>${cell(value)}</tr>`).join("") +
					`</tbody></table>`
			);
		});
	};
	const dialog = new frappe.ui.Dialog({
		title: __("Set Bid Price"),
		fields: [
			{ fieldname: "margin_percent", fieldtype: "Percent", label: __("Target Margin %"), reqd: 1, default: flt(frm.doc.muhick_margin_percent, 2) || undefined, onchange: show },
			{ fieldname: "result", fieldtype: "HTML" },
		],
		primary_action_label: __("Set Bid Price"),
		primary_action(values) {
			frappe.xcall(method, { opportunity: frm.doc.name, margin_percent: values.margin_percent, apply: 1 }).then((r) => {
				dialog.hide();
				frm.reload_doc();
				frappe.show_alert({ message: __("Bid price set to {0}.", [money(r.price, company)]), indicator: "green" });
			});
		},
	});
	dialog.show();
	show();
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
