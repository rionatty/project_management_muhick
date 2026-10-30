// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Opportunity", {
	setup(frm) {
		frm.set_query("milestone", "muhick_milestones", () => ({ filters: { disabled: 0 } }));
		setup_sheets(frm);
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

frappe.ui.form.on("Opportunity", {
	render_estimate,
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

// ---------------------------------------------------------------- the cost estimate, sheet by sheet
// The estimate is laid out as the business's budget workbook: a tab per sheet, each table with the columns of
// its sheet (widths as set on Project Budget Line), every line's item or service picked from the item master,
// its sub totals by system under it, the tax computation, and the Budget Summary and Profitability tabs. The
// actions are under Cost Estimate at the top.
const GOODS_COLUMNS = ["item_code", "description", "stage", "brand", "uom", "qty", "rate", "quoted_amount", "supplier"];
const OVERHEAD_COLUMNS = ["item_code", "description", "uom", "qty", "rate", "contract_percent", "quoted_amount", "supplier", "stage"];
const SHEET_COLUMNS = {
	muhick_equipment: GOODS_COLUMNS,
	muhick_materials: GOODS_COLUMNS,
	muhick_freight: ["item_code", "description", "stage", "supplier", "qty", "rate", "quoted_amount", "amount"],
	muhick_labour: ["item_code", "description", "stage", "people", "qty", "uom", "rate", "quoted_amount", "amount"],
	muhick_tools: ["item_code", "description", "stage", "uom", "qty", "rate", "quoted_amount", "amount", "supplier"],
	muhick_preliminaries: OVERHEAD_COLUMNS,
	muhick_administrative: OVERHEAD_COLUMNS,
};
// each tab's totals, and the tables they add up
const SHEET_TOTALS = {
	muhick_equipment_totals: ["muhick_equipment"],
	muhick_materials_totals: ["muhick_materials"],
	muhick_labour_totals: ["muhick_labour"],
	muhick_tools_totals: ["muhick_tools"],
	muhick_overheads_totals: ["muhick_preliminaries", "muhick_administrative"],
};
// goods made in the East African Community pay VAT only (the names of the country list)
const EAC = ["Burundi", "Congo, The Democratic Republic of the", "Kenya", "Rwanda", "Somalia", "South Sudan", "Tanzania", "Uganda"];
const TAX_AMOUNTS = ["value", "insurance", "customs_value", "duty", "vat", "levy", "total_tax"];

function setup_sheets(frm) {
	if (frm.get_field("muhick_import_taxes")) {
		frm.set_query("item_code", "muhick_import_taxes", () => ({ filters: { disabled: 0 } }));
	}
	Object.entries(SHEET_COLUMNS).forEach(([table, columns]) => {
		const field = frm.get_field(table);
		if (!field) {
			return; // until the site is migrated
		}
		field.grid.editable_fields = columns.map((fieldname) => ({ fieldname }));
		frm.set_query("cost_code", table, () => ({ filters: { disabled: 0 } }));
		frm.set_query("item_code", table, () => ({ filters: { disabled: 0 } }));
	});
}

function setup_estimate(frm) {
	if (!frm.fields_dict.muhick_equipment) {
		return; // until the site is migrated
	}
	frm.trigger("render_estimate");
	if (!frm.perm[0].write) {
		return;
	}
	const group = __("Cost Estimate");
	frm.add_custom_button(__("Upload from Excel"), () => muhick.cost_lines.upload(frm), group);
	frm.add_custom_button(__("Download Excel"), () => muhick.cost_lines.download(frm), group);
	if (frm.is_new()) {
		return;
	}
	frm.add_custom_button(__("Get Lines from the BOQ"), () => get_boq_lines(frm), group);
	frm.add_custom_button(__("Get Supplier Prices"), () => get_supplier_prices(frm), group);
	frm.add_custom_button(__("Get Imported Goods"), () => get_imported_goods(frm), group);
}

function render_estimate(frm) {
	if (!frm.fields_dict.muhick_equipment) {
		return;
	}
	muhick.cost_lines.settings(frm).then((settings) => {
		Object.entries(SHEET_TOTALS).forEach(([field, tables]) => frm.fields_dict[field].$wrapper.html(sheet_totals(frm, tables)));
		frm.fields_dict.muhick_taxes_totals.$wrapper.html(tax_computation(frm));
		frm.fields_dict.muhick_budget_summary.$wrapper.html(budget_summary(frm, settings));
		frm.fields_dict.muhick_profitability.$wrapper.html(profitability(frm));
	});
}

const esc = (text) => frappe.utils.escape_html(text || "");
const company_currency = (frm) => erpnext.get_currency(frm.doc.company);
const currency_of = (frm, row) => row.currency || company_currency(frm);
const money = (value, currency) => (flt(value) ? format_currency(value, currency) : "");
const total_of = (rows, key) => rows.reduce((sum, row) => sum + flt(row[key]), 0);
const cell = (html, bold) => `<td class="text-right"${bold ? ' style="font-weight: bold"' : ""}>${html}</td>`;
const grid_table = (head, body) =>
	`<div style="overflow-x: auto"><table class="table table-bordered table-condensed" style="margin-bottom: 12px">` +
	`<thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
const heads = (labels) => labels.map(([label, right]) => `<th${right ? ' class="text-right"' : ""}>${label}</th>`).join("");
// the stages of some lines, in the order they first come, those without one last
const stages_of = (rows) => {
	const stages = [...new Set(rows.map((r) => r.stage || ""))];
	return [...stages.filter(Boolean), ...stages.filter((s) => !s)];
};
// the currencies lines are quoted in, the company's last
const currencies_of = (frm, rows) => {
	const company = company_currency(frm);
	return [...new Set([...rows.map((r) => currency_of(frm, r)), company])].sort((a, b) => (a === company) - (b === company));
};
const in_currency = (frm, rows, currency, key) => total_of(rows.filter((r) => currency_of(frm, r) === currency), key);
// the estimate's lines of some tables
const lines_of = (frm, tables) => tables.flatMap((table) => frm.doc[table] || []);

// under a sheet's table, its sub totals as the sheet has them, system by system (or table by table): as quoted in
// each currency, VAT included where the quotes have it, and without VAT in the company's currency
function sheet_totals(frm, tables) {
	const rows = lines_of(frm, tables);
	if (!rows.length) {
		return "";
	}
	const company = company_currency(frm);
	const currencies = currencies_of(frm, rows);
	const line = (label, own, bold) =>
		`<tr${bold ? ' class="bold"' : ""}><td>${label}</td>` +
		currencies.map((c) => cell(money(in_currency(frm, own, c, "quoted_amount"), c))).join("") +
		cell(money(total_of(own, "amount"), company), true) +
		`</tr>`;
	const groups =
		tables.length > 1
			? tables.map((table) => [esc(__(frm.fields_dict[table].df.label)), frm.doc[table] || []])
			: stages_of(rows).map((stage) => [esc(stage) || __("No stage"), rows.filter((r) => (r.stage || "") === stage)]);
	const body = groups.filter(([, own]) => own.length).map(([label, own]) => line(label, own)).join("") + line(__("Total"), rows, true);
	const head = heads([
		[tables.length > 1 ? __("Part") : __("System / Stage")],
		...currencies.map((c) => [__("Amount as Quoted ({0})", [esc(c)]), true]),
		[__("Without VAT ({0})", [esc(company)]), true],
	]);
	return `<h6 class="text-muted" style="margin-top: 12px">${__("Sub Totals")}</h6>` + grid_table(head, body);
}

// the Taxes sheet: each imported good with its insurance, customs value (C.I), import duty (ID), VAT, levy (IL)
// and total tax in its currency, the totals with the freight (CFR), and what the imports cost the budget
function tax_computation(frm) {
	const goods = frm.doc.muhick_import_taxes || [];
	const freight = frm.doc.muhick_freight || [];
	if (!goods.length && !freight.length) {
		return "";
	}
	const company = company_currency(frm);
	let html = "";
	[...new Set(goods.map((r) => currency_of(frm, r)))].forEach((currency) => {
		const own = goods.filter((r) => currency_of(frm, r) === currency);
		const body =
			own
				.map(
					(r, i) =>
						`<tr><td>${i + 1}</td><td>${esc(r.description)}</td>${cell(flt(r.qty))}<td>${esc(r.uom)}</td>${cell(money(r.rate, currency))}` +
						TAX_AMOUNTS.map((key) => cell(money(r[key], currency))).join("") +
						`</tr>`
				)
				.join("") +
			`<tr class="bold"><td></td><td>${__("Total")}</td><td></td><td></td><td></td>` +
			TAX_AMOUNTS.map((key) => cell(money(total_of(own, key), currency))).join("") +
			`</tr>`;
		const head = heads([
			[__("No.")], [__("Item / Description")], [__("Qty"), true], [__("UOM")], [__("Rate"), true], [__("Total"), true],
			[__("Insurance"), true], [__("C.I"), true], [__("ID"), true], [__("VAT"), true], [__("IL"), true], [__("Total Tax"), true],
		]);
		html += `<h6 class="text-muted" style="margin-top: 12px">${__("Tax Computation ({0})", [esc(currency)])}</h6>` + grid_table(head, body);
	});
	const rows = [];
	[...new Set(goods.map((r) => currency_of(frm, r)))].forEach((currency) => {
		const value = in_currency(frm, goods, currency, "value");
		const carried = in_currency(frm, freight, currency, "quoted_amount");
		rows.push([__("Total Amount ({0})", [esc(currency)]), money(value, currency)]);
		rows.push([__("Total Taxes ({0})", [esc(currency)]), money(in_currency(frm, goods, currency, "total_tax"), currency)]);
		if (carried) {
			rows.push([__("Freight ({0})", [esc(currency)]), money(carried, currency)]);
			rows.push([__("Total Amount with Freight, CFR ({0})", [esc(currency)]), money(value + carried, currency)]);
		}
	});
	const taxes_cost = total_of(goods, "cost");
	const freight_cost = total_of(freight, "amount");
	const vat = goods.reduce((sum, r) => sum + flt(r.vat) * (currency_of(frm, r) === company ? 1 : flt(r.exchange_rate) || 1), 0);
	rows.push([__("Insurance, Import Duty and Levy ({0})", [esc(company)]), money(taxes_cost, company)]);
	rows.push([__("Freight and Clearing, without VAT ({0})", [esc(company)]), money(freight_cost, company)]);
	rows.push([`<b>${__("Cost of the Imports to the Budget ({0})", [esc(company)])}</b>`, `<b>${money(taxes_cost + freight_cost, company)}</b>`]);
	if (vat) {
		rows.push([__("Import VAT, claimed back so not a cost ({0})", [esc(company)]), money(vat, company)]);
	}
	return (
		html +
		`<table class="table table-condensed" style="width: auto; margin-top: 8px"><tbody>` +
		rows.map(([label, value]) => `<tr><td>${label}</td>${cell(value)}</tr>`).join("") +
		`</tbody></table>`
	);
}

// what a part of the estimate comes to: as quoted in each currency, and without VAT in the company's currency
const part = (frm, rows) => ({ rows, quoted: (c) => in_currency(frm, rows, c, "quoted_amount"), amount: total_of(rows, "amount") });

// the Budget Summary sheet: equipment and materials system by system with their suppliers, the origin, shipment
// and taxes of the imported ones, then taxes and freight, installation costs and overheads, and the grand total,
// contract value, project cost and profit
function budget_summary(frm, settings) {
	const all = muhick.cost_lines.rows(frm);
	const goods = frm.doc.muhick_import_taxes || [];
	if (!all.length && !goods.length) {
		return "";
	}
	const company = company_currency(frm);
	const currencies = currencies_of(frm, all);
	const distinct = (values) => [...new Set(values.filter(Boolean))].map(esc).join(", ");
	const taxes_to_ura = (rows) => rows.reduce((sum, r) => sum + flt(r.total_tax) * (currency_of(frm, r) === company ? 1 : flt(r.exchange_rate) || 1), 0);
	let number = 0;
	const row = (label, rows, extra = {}, bold = false) => {
		const sums = part(frm, rows);
		const style = bold ? ' style="font-weight: bold"' : "";
		return (
			`<tr${style}><td>${extra.no || ""}</td><td>${label}</td><td>${extra.supplier || ""}</td><td>${extra.country || ""}</td><td>${extra.shipment || ""}</td>` +
			currencies.map((c) => cell(money(sums.quoted(c), c))).join("") +
			cell(money(extra.taxes, company)) +
			cell(money(sums.amount + flt(extra.cost), company)) +
			`</tr>`
		);
	};
	const heading = (letter, label) => `<tr class="bold"><td>${letter}</td><td colspan="${6 + currencies.length}">${label}</td></tr>`;
	let body = "";
	[
		["A", __("Equipment"), "muhick_equipment"],
		["B", __("Installation Materials"), "muhick_materials"],
	].forEach(([letter, label, table]) => {
		const rows = frm.doc[table] || [];
		if (!rows.length) {
			return;
		}
		body += heading(letter, label);
		number = 0;
		stages_of(rows).forEach((stage) => {
			const own = rows.filter((r) => (r.stage || "") === stage);
			// the origin, shipment and taxes of the system's imported goods go with its equipment
			const imported = table === "muhick_equipment" ? goods.filter((r) => (r.stage || "") === stage) : [];
			body += row(esc(stage) || __("No stage"), own, {
				no: ++number,
				supplier: distinct(own.map((r) => r.supplier)),
				country: distinct(imported.map((r) => r.country_of_origin)),
				shipment: distinct(imported.map((r) => r.mode_of_shipment)),
				taxes: taxes_to_ura(imported),
			});
		});
		body += row(__("Total Cost of {0}", [label]), rows, { taxes: table === "muhick_equipment" ? taxes_to_ura(goods) : 0 }, true);
	});
	const freight = frm.doc.muhick_freight || [];
	if (goods.length || freight.length) {
		body += heading("C", __("Taxes and Freight"));
		body += row(__("Insurance, Import Duty and Levy"), [], { no: 1, cost: total_of(goods, "cost") });
		body += row(__("Freight and Clearing"), freight, { no: 2, supplier: distinct(freight.map((r) => r.supplier)) });
	}
	[
		["D", __("Installation Costs"), [[__("Labour"), "muhick_labour"], [__("Tools and Equipment"), "muhick_tools"]]],
		["E", __("Preliminaries and Administrative Costs"), [[__("Preliminaries"), "muhick_preliminaries"], [__("Administrative Costs"), "muhick_administrative"]]],
	].forEach(([letter, label, parts]) => {
		if (!parts.some(([, table]) => (frm.doc[table] || []).length)) {
			return;
		}
		body += heading(letter, label);
		parts.forEach(([name, table], i) => (body += row(name, frm.doc[table] || [], { no: i + 1 })));
	});
	const cost = total_of(all, "amount") + total_of(goods, "cost");
	const quoted = all.reduce((sum, r) => sum + flt(r.quoted_amount) * (currency_of(frm, r) === company ? 1 : flt(r.exchange_rate) || 1), 0);
	const grand = quoted + goods.reduce((sum, r) => sum + (flt(r.insurance) + flt(r.total_tax)) * (currency_of(frm, r) === company ? 1 : flt(r.exchange_rate) || 1), 0);
	const head = heads([
		[__("No.")], [__("Description")], [__("Supplier")], [__("Country of Origin")], [__("Mode of Shipment")],
		...currencies.map((c) => [__("Amount ({0})", [esc(c)]), true]),
		[__("Taxes to URA ({0})", [esc(company)]), true],
		[__("Without VAT ({0})", [esc(company)]), true],
	]);
	const rates = [...new Map(all.filter((r) => muhick.cost_lines.foreign(frm, r)).map((r) => [r.currency, flt(r.exchange_rate)])).entries()];
	const contract = muhick.cost_lines.contract_value(frm);
	const vat = flt(settings.vat_percent);
	const lines = [
		[__("Grand Total, VAT and import taxes included"), money(grand, company)],
		...(rates.length ? [[__("Exchange rates used"), rates.map(([c, rate]) => `${esc(c)} 1 = ${format_currency(rate, company)}`).join("; ")]] : []),
		[__("Contract Value, VAT included"), money(contract * (1 + vat / 100), company)],
		[__("Contract Value, without VAT"), money(contract, company)],
		[`<b>${__("Total Project Cost, without VAT")}</b>`, `<b>${money(cost, company)}</b>`],
		...(contract
			? [
					[`<b>${__("Profit Margin")}</b>`, `<b>${format_currency(contract - cost, company)}</b>`],
					[`<b>${__("% Profit")}</b>`, `<b>${flt(((contract - cost) / contract) * 100, 1)}%</b>`],
			  ]
			: []),
	];
	return (
		grid_table(head, body) +
		`<table class="table table-condensed" style="width: auto"><tbody>` +
		lines.map(([label, value]) => `<tr><td>${label}</td>${cell(value)}</tr>`).join("") +
		`</tbody></table>`
	);
}

// the Profitability sheet: the contract value without VAT, less the estimate part by part without VAT, the
// equipment and materials system by system, and the margin and its percentage
function profitability(frm) {
	const all = muhick.cost_lines.rows(frm);
	const goods = frm.doc.muhick_import_taxes || [];
	if (!all.length && !goods.length) {
		return "";
	}
	const company = company_currency(frm);
	const contract = muhick.cost_lines.contract_value(frm);
	let body = `<tr class="bold"><td></td><td>${__("Contract Value, without VAT")}</td>${cell(money(contract, company))}</tr>`;
	body += `<tr><td></td><td><i>${__("Less: Deductions")}</i></td><td></td></tr>`;
	let expenses = 0;
	const block = (label, items) => {
		const shown = items.filter(([, amount]) => flt(amount));
		if (!shown.length) {
			return;
		}
		body += `<tr class="bold"><td></td><td>${label}</td><td></td></tr>`;
		shown.forEach(([name, amount], i) => (body += `<tr><td>${i + 1}</td><td>${name}</td>${cell(money(amount, company))}</tr>`));
		const subtotal = shown.reduce((sum, [, amount]) => sum + flt(amount), 0);
		body += `<tr><td></td><td><i>${__("Sub-Total")}</i></td>${cell(money(subtotal, company), true)}</tr>`;
		expenses += subtotal;
	};
	const by_stage = (table) => {
		const rows = frm.doc[table] || [];
		return stages_of(rows).map((stage) => [esc(stage) || __("No stage"), total_of(rows.filter((r) => (r.stage || "") === stage), "amount")]);
	};
	block(__("Installation Equipment, without VAT"), by_stage("muhick_equipment"));
	block(__("Installation Materials, without VAT"), by_stage("muhick_materials"));
	block(__("Taxes and Freight"), [
		[__("Insurance, Import Duty and Levy"), total_of(goods, "cost")],
		[__("Freight and Clearing"), total_of(frm.doc.muhick_freight || [], "amount")],
	]);
	block(__("Installation Costs, without VAT"), [
		[__("Labour"), total_of(frm.doc.muhick_labour || [], "amount")],
		[__("Tools and Equipment"), total_of(frm.doc.muhick_tools || [], "amount")],
	]);
	block(__("Preliminaries and Administrative Costs"), [
		[__("Preliminaries"), total_of(frm.doc.muhick_preliminaries || [], "amount")],
		[__("Administrative Costs"), total_of(frm.doc.muhick_administrative || [], "amount")],
	]);
	body += `<tr class="bold"><td></td><td>${__("Sub-Total Project Expenses, without VAT")}</td>${cell(money(expenses, company))}</tr>`;
	if (contract) {
		body += `<tr class="bold"><td></td><td>${__("Profit Margin")}</td>${cell(format_currency(contract - expenses, company))}</tr>`;
		body += `<tr class="bold"><td></td><td>${__("% Margin")}</td>${cell(`${flt(((contract - expenses) / contract) * 100, 1)}%`)}</tr>`;
	}
	return grid_table(heads([[__("No.")], [__("Details")], [__("Amount ({0})", [esc(company)]), true]]), body);
}

// an imported good's taxes, as the business's tax computation works them out (see calc.import_taxes)
function taxes_of(frm, row) {
	const value = flt(row.qty) * flt(row.rate);
	const insurance = (value * flt(row.insurance_percent)) / 100;
	const customs_value = value + insurance;
	const duty = (customs_value * flt(row.duty_percent)) / 100;
	const vat = ((customs_value + duty) * flt(row.vat_percent)) / 100;
	const levy = (customs_value * flt(row.levy_percent)) / 100;
	const rate = muhick.cost_lines.foreign(frm, row) ? flt(row.exchange_rate) || 1 : 1;
	return { value, insurance, customs_value, duty, vat, levy, total_tax: duty + vat + levy, cost: (insurance + duty + levy) * rate };
}

function set_taxes(frm, cdt, cdn) {
	frappe.model.set_value(cdt, cdn, taxes_of(frm, locals[cdt][cdn])).then(() => frm.trigger("render_estimate"));
}

const usual_rates = (settings) => ({
	insurance_percent: settings.import_insurance_percent,
	duty_percent: settings.import_duty_percent,
	vat_percent: settings.vat_percent,
	levy_percent: settings.import_levy_percent,
});

frappe.ui.form.on("Import Tax Line", {
	item_code: (frm, cdt, cdn) => muhick.cost_lines.take_item(frm, cdt, cdn, ["description", "uom"]),
	muhick_import_taxes_add(frm, cdt, cdn) {
		muhick.cost_lines
			.settings(frm)
			.then((settings) => frappe.model.set_value(cdt, cdn, { currency: company_currency(frm), ...usual_rates(settings) }));
	},
	...Object.fromEntries(
		["qty", "rate", "insurance_percent", "duty_percent", "vat_percent", "levy_percent"].map((field) => [field, set_taxes])
	),
	exchange_rate(frm, cdt, cdn) {
		set_taxes(frm, cdt, cdn);
		muhick.cost_lines.share_rate(frm, cdt, cdn);
	},
	currency(frm, cdt, cdn) {
		muhick.cost_lines.set_exchange_rate(frm, cdt, cdn);
		set_taxes(frm, cdt, cdn);
	},
	// goods made in the Community pay VAT only; others pay the usual duty and levy
	country_of_origin(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (EAC.includes(row.country_of_origin)) {
			frappe.model.set_value(cdt, cdn, { duty_percent: 0, levy_percent: 0 });
		} else if (row.country_of_origin && !flt(row.duty_percent) && !flt(row.levy_percent)) {
			muhick.cost_lines.settings(frm).then((settings) => {
				const rates = usual_rates(settings);
				frappe.model.set_value(cdt, cdn, { duty_percent: rates.duty_percent, levy_percent: rates.levy_percent });
			});
		}
	},
	stage: (frm) => frm.trigger("render_estimate"),
	mode_of_shipment: (frm) => frm.trigger("render_estimate"),
	muhick_import_taxes_remove: (frm) => frm.trigger("render_estimate"),
});

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
				message: __("{0} line(s) added from the BOQ to Equipment and Installation Materials. Check their rates and cost codes, then add labour, tools and administration.", [
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
					Object.assign(row, price, { rate_includes_vat: 0 });
					if (muhick.cost_lines.foreign(frm, row)) {
						row.exchange_rate = muhick.cost_lines.used_rate(frm, row) || row.exchange_rate;
					}
					row.amount = muhick.cost_lines.amount(frm, row, settings);
					row.quoted_amount = muhick.cost_lines.quoted(row);
					priced += 1;
				});
				frm.dirty();
				muhick.cost_lines.tables(frm).forEach((table) => frm.refresh_field(table));
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

// the tax computation's goods from the equipment and materials bought abroad (marked International, or priced
// in another currency) that are not in it yet, at the usual rates
function get_imported_goods(frm) {
	const key = (r) => `${r.stage || ""}|${(r.description || "").trim().toLowerCase()}`;
	const present = new Set((frm.doc.muhick_import_taxes || []).map(key));
	const lines = lines_of(frm, ["muhick_equipment", "muhick_materials"]).filter(
		(r) => (r.procurement_type === "International" || muhick.cost_lines.foreign(frm, r)) && !present.has(key(r))
	);
	if (!lines.length) {
		frappe.msgprint(
			__("Every imported line is in the tax computation already. Lines count as imported when their Procurement Type is International or they are priced in another currency.")
		);
		return;
	}
	muhick.cost_lines.settings(frm).then((settings) => {
		lines.forEach((r) => {
			const row = frm.add_child("muhick_import_taxes", {
				stage: r.stage, item_code: r.item_code, description: r.description, supplier: r.supplier, qty: r.qty, uom: r.uom, rate: r.rate,
				currency: r.currency || company_currency(frm), exchange_rate: r.exchange_rate, ...usual_rates(settings),
			});
			Object.assign(row, taxes_of(frm, row));
		});
		frm.refresh_field("muhick_import_taxes");
		frm.dirty();
		frm.trigger("render_estimate");
		frappe.show_alert({
			message: __("{0} imported good(s) added to the tax computation at the usual rates. Set the country of origin of each: goods from the East African Community pay VAT only.", [lines.length]),
			indicator: "green",
		});
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
