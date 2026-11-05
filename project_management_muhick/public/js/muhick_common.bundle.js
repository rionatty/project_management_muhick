// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

// Small helpers shared by the Muhick forms. Loaded on every desk page as a bundle (see hooks.py): what
// other scripts use hangs on the muhick namespace or is a form event, as the bundle's own names stay in it.
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
	return { filters: { project: project || "", is_group: 1, parent_task: ["is", "not set"], status: ["!=", "Cancelled"] } };
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

// A bid's cost estimate (on the opportunity, a table per sheet of the budget workbook) and a project budget have
// the same lines. A line's amount is in the company's currency without VAT: people x qty x rate at its
// exchange rate, a rate quoted with VAT taken without it, or a share of the contract value; its amount as
// quoted is people x qty x rate in its own currency. The server works them out the same way on saving.
muhick.cost_lines = {
	// the tables of lines of an estimate or budget, one per section as the sheets of the budget workbook (see
	// estimate.py)
	sections: {
		muhick_equipment: "Equipment",
		muhick_materials: "Installation Materials",
		muhick_freight: "Taxes and Freight",
		muhick_labour: "Labour",
		muhick_tools: "Tools and Equipment",
		muhick_preliminaries: "Preliminaries",
		muhick_administrative: "Administrative",
	},
	tables() {
		return Object.keys(muhick.cost_lines.sections);
	},
	table_of(section) {
		const sections = muhick.cost_lines.sections;
		return Object.keys(sections).find((field) => sections[field] === section) || "muhick_materials";
	},
	rows(frm) {
		return muhick.cost_lines.tables().flatMap((field) => frm.doc[field] || []);
	},
	// the value a share is taken of: the bid price, or the project's revised contract value
	contract_value(frm) {
		return frm.doctype === "Opportunity"
			? flt(frm.doc.opportunity_amount) * (flt(frm.doc.conversion_rate) || 1)
			: flt(frm.doc.contract_value);
	},
	settings(frm) {
		frm.__cost_settings =
			frm.__cost_settings || frappe.xcall("project_management_muhick.muhick_projects.estimate.get_estimate_settings");
		return frm.__cost_settings;
	},
	foreign(frm, row) {
		return Boolean(row.currency) && row.currency !== erpnext.get_currency(frm.doc.company);
	},
	amount(frm, row, settings) {
		if (flt(row.contract_percent)) {
			return (muhick.cost_lines.contract_value(frm) * flt(row.contract_percent)) / 100;
		}
		const rate = muhick.cost_lines.foreign(frm, row) ? flt(row.exchange_rate) || 1 : 1;
		const amount = muhick.cost_lines.quoted(row) * rate;
		return row.rate_includes_vat ? amount / (1 + muhick.cost_lines.vat_of(row, settings) / 100) : amount;
	},
	// a line quoted with VAT keeps the rate it was first worked out at; one quoted without it has none
	vat_of(row, settings) {
		return row.rate_includes_vat ? flt(row.vat_percent) || flt(settings.vat_percent) : 0;
	},
	// the amount as the budget sheets show it: people x qty x rate in the line's currency, VAT as quoted
	quoted(row) {
		return flt(row.qty) * flt(row.rate) * (cint(row.people) || 1);
	},
	set_amount(frm, cdt, cdn) {
		muhick.cost_lines.settings(frm).then((settings) => {
			const row = locals[cdt][cdn];
			const amount = muhick.cost_lines.amount(frm, row, settings);
			frappe.model.set_value(
				cdt,
				cdn,
				flt(row.contract_percent)
					? { amount, qty: 1, rate: amount, quoted_amount: amount, vat_percent: 0 }
					: { amount, quoted_amount: muhick.cost_lines.quoted(row), vat_percent: muhick.cost_lines.vat_of(row, settings) }
			);
		});
	},
	// one rate per currency on an estimate or budget: the one its other lines in that currency already use
	used_rate(frm, row) {
		const others = [...muhick.cost_lines.rows(frm), ...(frm.doc.muhick_import_taxes || [])];
		const other = others.find((r) => r !== row && r.currency === row.currency && flt(r.exchange_rate));
		return other ? flt(other.exchange_rate) : 0;
	},
	// a rate changed on one line is the rate for that currency: the other lines take it too
	share_rate(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!muhick.cost_lines.foreign(frm, row) || !flt(row.exchange_rate)) {
			return;
		}
		[...muhick.cost_lines.rows(frm), ...(frm.doc.muhick_import_taxes || [])]
			.filter((r) => r !== row && r.currency === row.currency && flt(r.exchange_rate) !== flt(row.exchange_rate))
			.forEach((r) => frappe.model.set_value(r.doctype, r.name, "exchange_rate", row.exchange_rate));
	},
	set_exchange_rate(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!muhick.cost_lines.foreign(frm, row)) {
			frappe.model.set_value(cdt, cdn, "exchange_rate", 1);
			return;
		}
		const used = muhick.cost_lines.used_rate(frm, row);
		if (used) {
			frappe.model.set_value(cdt, cdn, "exchange_rate", used);
			return;
		}
		frappe
			.xcall("erpnext.setup.utils.get_exchange_rate", {
				from_currency: row.currency,
				to_currency: erpnext.get_currency(frm.doc.company),
			})
			.then((rate) => rate && frappe.model.set_value(cdt, cdn, "exchange_rate", rate));
	},
	// lines from the server, each into its section's table: in a currency already used, at its rate; then
	// their amounts and the summary
	add_rows(frm, rows) {
		return muhick.cost_lines.settings(frm).then((settings) => {
			const touched = new Set();
			rows.forEach((values) => {
				const table = muhick.cost_lines.table_of(values.section);
				const row = frm.add_child(table, { ...values, currency: values.currency || erpnext.get_currency(frm.doc.company) });
				if (muhick.cost_lines.foreign(frm, row)) {
					row.exchange_rate = muhick.cost_lines.used_rate(frm, row) || row.exchange_rate;
				}
				row.amount = muhick.cost_lines.amount(frm, row, settings);
				row.quoted_amount = flt(row.contract_percent) ? row.amount : muhick.cost_lines.quoted(row);
				row.vat_percent = muhick.cost_lines.vat_of(row, settings);
				touched.add(table);
			});
			touched.forEach((table) => frm.refresh_field(table));
			muhick.cost_lines.render_summary(frm);
		});
	},
	// an item picked from the item master brings its description, unit and the other fields given, and its
	// price when the line has none (the lowest supplier quotation for the bid, else its last purchase price);
	// when another item is picked, what came from the first follows it, what was typed over stays
	take_item(frm, cdt, cdn, fields) {
		const item_code = locals[cdt][cdn].item_code;
		if (!item_code) {
			return Promise.resolve(null);
		}
		const before = locals[cdt][cdn].__item || {};
		const row = locals[cdt][cdn];
		return frappe
			.xcall("project_management_muhick.muhick_projects.estimate.get_item_details", {
				item_code,
				uom: row.uom && row.uom !== before.uom ? row.uom : null,
				opportunity: frm.doctype === "Opportunity" && !frm.is_new() ? frm.doc.name : null,
				company: frm.doc.company,
			})
			.then((item) => {
				const now = locals[cdt][cdn];
				if (!item.description || !now || now.item_code !== item_code) {
					return null;
				}
				const values = {};
				fields.forEach((field) => {
					if (item[field] && (!now[field] || now[field] === before[field])) {
						values[field] = item[field];
					}
				});
				const price = item.price || {};
				if (flt(price.rate) && (!flt(now.rate) || flt(now.rate) === flt((before.price || {}).rate))) {
					Object.assign(values, price);
				}
				now.__item = item;
				return frappe.model.set_value(cdt, cdn, values).then(() => item);
			});
	},
	// the lines to and from Excel: a file of the saved lines to prepare or change in Excel, and an upload
	// that checks every row first, so a file with mistakes changes nothing
	download(frm) {
		if (frm.is_dirty() && !frm.is_new()) {
			frappe.msgprint(__("Save first, so the Excel file has the latest lines."));
			return;
		}
		const args = new URLSearchParams({ doctype: frm.doctype, name: frm.is_new() ? "" : frm.doc.name });
		window.open(`/api/method/project_management_muhick.muhick_projects.estimate.download_cost_lines?${args}`);
	},
	upload(frm) {
		new frappe.ui.FileUploader({
			as_dataurl: true,
			allow_multiple: false,
			restrictions: { allowed_file_types: [".xlsx", ".xls", ".csv"] },
			on_success: (file) =>
				frappe
					.xcall("project_management_muhick.muhick_projects.estimate.read_cost_lines", {
						doctype: frm.doctype,
						name: frm.is_new() ? null : frm.doc.name,
						company: frm.doc.company,
						filename: file.name,
						content: file.dataurl,
					})
					.then((result) => muhick.cost_lines.take_upload(frm, result)),
		});
	},
	take_upload(frm, result) {
		const lines = (texts) => texts.map((t) => frappe.utils.escape_html(t)).join("<br>");
		if (result.errors.length) {
			frappe.msgprint({
				title: __("Nothing was uploaded"),
				indicator: "red",
				message: __("Correct these in the Excel file and upload it again:") + "<br><br>" + lines(result.errors),
			});
			return;
		}
		const taxes = result.tax_rows || [];
		const tables = [...muhick.cost_lines.tables(), "muhick_import_taxes"];
		const take = (replace) => {
			if (replace) {
				tables.forEach((table) => frm.clear_table(table));
			}
			taxes.forEach((values) =>
				frm.add_child("muhick_import_taxes", { ...values, currency: values.currency || erpnext.get_currency(frm.doc.company) })
			);
			muhick.cost_lines.add_rows(frm, result.rows).then(() => {
				tables.forEach((table) => frm.refresh_field(table));
				frm.dirty();
				frm.trigger("render_estimate");
				const counted = taxes.length
					? __("{0} line(s) and {1} imported good(s) taken from the Excel file. Save to keep them.", [result.rows.length, taxes.length])
					: __("{0} line(s) taken from the Excel file. Save to keep them.", [result.rows.length]);
				frappe.msgprint({ title: __("Uploaded"), indicator: "green", message: lines([counted, ...result.notes]) });
			});
		};
		if (!tables.some((table) => (frm.doc[table] || []).length)) {
			take(true);
			return;
		}
		frappe.prompt(
			{
				fieldname: "mode",
				fieldtype: "Select",
				label: __("The lines already here"),
				options: [
					{ value: "replace", label: __("Replace them with the Excel lines") },
					{ value: "add", label: __("Keep them and add the Excel lines") },
				],
				default: "replace",
				reqd: 1,
			},
			(values) => take(values.mode === "replace"),
			__("Upload from Excel"),
			__("Upload")
		);
	},
	render_summary(frm) {
		frm.trigger("render_estimate");
	},
};

frappe.ui.form.on("Project Budget Line", {
	...Object.fromEntries(
		["qty", "rate", "people", "rate_includes_vat", "vat_percent", "contract_percent"].map((field) => [
			field,
			(frm, cdt, cdn) => muhick.cost_lines.set_amount(frm, cdt, cdn),
		])
	),
	exchange_rate(frm, cdt, cdn) {
		muhick.cost_lines.set_amount(frm, cdt, cdn);
		muhick.cost_lines.share_rate(frm, cdt, cdn);
	},
	currency(frm, cdt, cdn) {
		muhick.cost_lines.set_exchange_rate(frm, cdt, cdn);
		muhick.cost_lines.set_amount(frm, cdt, cdn);
	},
	// an item that pays no VAT is not quoted with it
	item_code(frm, cdt, cdn) {
		muhick.cost_lines.take_item(frm, cdt, cdn, ["description", "uom", "brand", "cost_code"]).then((item) => {
			if (item && !flt(item.tax_rates.vat_percent) && locals[cdt][cdn].rate_includes_vat) {
				frappe.model.set_value(cdt, cdn, "rate_includes_vat", 0);
			}
		});
	},
	// a new line is in the company's currency until another is chosen, so its amounts show in it
	...Object.fromEntries(
		Object.keys(muhick.cost_lines.sections).map((table) => [
			`${table}_add`,
			(frm, cdt, cdn) => locals[cdt][cdn].currency || frappe.model.set_value(cdt, cdn, "currency", erpnext.get_currency(frm.doc.company)),
		])
	),
	...Object.fromEntries(
		["amount", "section", "stage", "supplier", ...Object.keys(muhick.cost_lines.sections).map((t) => `${t}_remove`)].map(
			(field) => [field, (frm) => muhick.cost_lines.render_summary(frm)]
		)
	),
});

// ---------------------------------------------------------------- the sheets of an estimate or budget
// An opportunity's estimate and a project's budget are laid out alike, as the business's budget workbook, with the
// same tables under the same names: a tab per sheet, each table with the columns of its sheet (widths as set on
// Project Budget Line), every line's item or service picked from the item master, its sub totals by system under
// it, the tax computation, and the Budget Summary and Profitability tabs.
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
		// a budget is controlled by cost code, so its lines show theirs
		field.grid.editable_fields = [...columns, ...(frm.doctype === "Project Budget" ? ["cost_code"] : [])].map((fieldname) => ({ fieldname }));
		frm.set_query("cost_code", table, () => ({ filters: { disabled: 0 } }));
		frm.set_query("item_code", table, () => ({ filters: { disabled: 0 } }));
	});
}

function render_estimate(frm) {
	if (!frm.fields_dict.muhick_equipment) {
		return;
	}
	muhick.cost_lines.settings(frm).then((settings) => {
		Object.entries(SHEET_TOTALS).forEach(([field, tables]) => frm.fields_dict[field].$wrapper.html(sheet_totals(frm, tables)));
		frm.fields_dict.muhick_taxes_totals.$wrapper.html(tax_totals(frm));
		frm.fields_dict.muhick_budget_summary.$wrapper.html(budget_summary(frm, settings));
		frm.fields_dict.muhick_profitability.$wrapper.html(profitability(frm));
		if (frm.fields_dict.phase_summary) {
			frm.fields_dict.phase_summary.$wrapper.html(stage_matrix(frm));
		}
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

// under the tax computation and the freight, what they come to: the totals of the Taxes sheet in each currency with
// the freight (CFR), then what the imports cost the budget
function tax_totals(frm) {
	const goods = frm.doc.muhick_import_taxes || [];
	const freight = frm.doc.muhick_freight || [];
	if (!goods.length && !freight.length) {
		return "";
	}
	const company = company_currency(frm);
	const body = [...new Set([...goods, ...freight].map((r) => currency_of(frm, r)))]
		.map((currency) => {
			const carried = in_currency(frm, freight, currency, "quoted_amount");
			return (
				`<tr><td>${esc(currency)}</td>` +
				TAX_AMOUNTS.map((key) => cell(money(in_currency(frm, goods, currency, key), currency))).join("") +
				cell(money(carried, currency)) +
				cell(money(in_currency(frm, goods, currency, "value") + carried, currency), true) +
				`</tr>`
			);
		})
		.join("");
	const head = heads([
		[__("Totals")], [__("Total"), true], [__("Insurance"), true], [__("C.I"), true], [__("ID"), true], [__("VAT"), true], [__("IL"), true],
		[__("Total Tax"), true], [__("Freight"), true], [__("With Freight (CFR)"), true],
	]);
	const taxes_cost = total_of(goods, "cost");
	const freight_cost = total_of(freight, "amount");
	const vat = goods.reduce((sum, r) => sum + flt(r.vat) * (currency_of(frm, r) === company ? 1 : flt(r.exchange_rate) || 1), 0);
	const rows = [
		[__("Insurance, Import Duty and Levy ({0})", [esc(company)]), money(taxes_cost, company)],
		[__("Freight and Clearing, without VAT ({0})", [esc(company)]), money(freight_cost, company)],
		[`<b>${__("Cost of the Imports to the Budget ({0})", [esc(company)])}</b>`, `<b>${money(taxes_cost + freight_cost, company)}</b>`],
	];
	if (vat) {
		rows.push([__("Import VAT, claimed back so not a cost ({0})", [esc(company)]), money(vat, company)]);
	}
	return (
		grid_table(head, body) +
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
// the rates as they are now for some items: {usual, items: {item: its rates}, countries: {item: its origin}}
const tax_rates = (frm, items) =>
	frappe.xcall("project_management_muhick.muhick_projects.estimate.get_tax_rates", {
		items: [...new Set(items.filter(Boolean))],
		company: frm.doc.company,
	});
// an imported good's rates: its item's, else the usual ones; goods made in the Community pay VAT only
const rates_of = (rates, item_code, country) => {
	const own = rates.items[item_code] || rates.usual;
	return EAC.includes(country) ? { ...own, duty_percent: 0, levy_percent: 0 } : own;
};

frappe.ui.form.on("Import Tax Line", {
	// an item picked brings its own rates and origin from the item master; a rate can still be changed on the row
	item_code(frm, cdt, cdn) {
		muhick.cost_lines.take_item(frm, cdt, cdn, ["description", "uom"]).then((item) => {
			if (item) {
				const country = locals[cdt][cdn].country_of_origin || item.country_of_origin;
				const rates = rates_of({ items: {}, usual: item.tax_rates }, null, country);
				frappe.model.set_value(cdt, cdn, { ...rates, country_of_origin: country || null });
			}
		});
	},
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
	// goods made in the Community pay VAT only; others pay their item's duty and levy, else the usual ones
	country_of_origin(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (EAC.includes(row.country_of_origin)) {
			frappe.model.set_value(cdt, cdn, { duty_percent: 0, levy_percent: 0 });
		} else if (row.country_of_origin && !flt(row.duty_percent) && !flt(row.levy_percent)) {
			tax_rates(frm, [row.item_code]).then((rates) => {
				const own = rates_of(rates, row.item_code, row.country_of_origin);
				frappe.model.set_value(cdt, cdn, { duty_percent: own.duty_percent, levy_percent: own.levy_percent });
			});
		}
	},
	stage: (frm) => frm.trigger("render_estimate"),
	mode_of_shipment: (frm) => frm.trigger("render_estimate"),
	muhick_import_taxes_remove: (frm) => frm.trigger("render_estimate"),
});

// a budget's cost section by section (A Equipment, B Installation Materials...) against the stages, as its print has it
function stage_matrix(frm) {
	const cost_lines = muhick.cost_lines;
	const goods = frm.doc.muhick_import_taxes || [];
	const stages = stages_of([...cost_lines.rows(frm), ...goods]);
	if (!stages.length) {
		return "";
	}
	const company = company_currency(frm);
	const amounts = Object.entries(cost_lines.sections).map(([table, section]) => {
		const rows = frm.doc[table] || [];
		const taxes = section === "Taxes and Freight" ? goods : [];
		return [
			section,
			stages.map((stage) => {
				const own = (r) => (r.stage || "") === stage;
				return total_of(rows.filter(own), "amount") + total_of(taxes.filter(own), "cost");
			}),
		];
	});
	const shown = amounts.filter(([, values]) => values.some(flt));
	const body =
		shown
			.map(([section, values], i) => {
				const total = values.reduce((sum, value) => sum + flt(value), 0);
				return `<tr><td>${String.fromCharCode(65 + i)}. ${__(section)}</td>${values.map((v) => cell(money(v, company))).join("")}${cell(money(total, company), true)}</tr>`;
			})
			.join("") +
		`<tr class="bold"><td>${__("Total Cost, without VAT")}</td>` +
		stages.map((_stage, i) => cell(money(shown.reduce((sum, [, values]) => sum + flt(values[i]), 0), company))).join("") +
		cell(money(shown.reduce((sum, [, values]) => sum + values.reduce((all, value) => all + flt(value), 0), 0), company)) +
		`</tr>`;
	return grid_table(heads([[__("Section")], ...stages.map((stage) => [esc(stage) || __("No stage"), true]), [__("Total"), true]]), body);
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
	tax_rates(frm, lines.map((r) => r.item_code)).then((rates) => {
		lines.forEach((r) => {
			const country = rates.countries[r.item_code];
			const row = frm.add_child("muhick_import_taxes", {
				stage: r.stage, item_code: r.item_code, description: r.description, supplier: r.supplier, qty: r.qty, uom: r.uom, rate: r.rate,
				currency: r.currency || company_currency(frm), exchange_rate: r.exchange_rate, country_of_origin: country,
				...rates_of(rates, r.item_code, country),
			});
			Object.assign(row, taxes_of(frm, row));
		});
		frm.refresh_field("muhick_import_taxes");
		frm.dirty();
		frm.trigger("render_estimate");
		frappe.show_alert({
			message: __("{0} imported good(s) added to the tax computation. Check the country of origin of each: goods from the East African Community pay VAT only.", [lines.length]),
			indicator: "green",
		});
	});
}

muhick.sheets = { setup: setup_sheets, render: render_estimate, taxes_of, tax_rates, rates_of, get_imported_goods, lines_of, esc, money, cell, company_currency };

// run a whitelisted method of the open document, then reload it
muhick.run = function (frm, method, args) {
	return frm.call(method, args || {}).then(() => frm.reload_doc());
};

// ask for some values, then run a document method with them
muhick.prompt_and_run = function (frm, title, fields, method) {
	frappe.prompt(fields, (values) => muhick.run(frm, method, values), title);
};

// BEGIN cash requisitions: the same for a project's and a bid's
muhick.setup_cash_requisition = function (frm) {
	const company = () => ({ company: frm.doc.company || "" });
	frm.set_query("employee", () => ({
		query: "project_management_muhick.muhick_finance.cash_requisition.employee_query",
		filters: company(),
	}));
	["items", "expenses"].forEach((table) => {
		frm.set_query("expense_account", table, () => ({
			query: "project_management_muhick.muhick_finance.cash_requisition.expense_account_query",
			filters: company(),
		}));
	});
};

muhick.cash_requisition_actions = function (frm) {
	const status = frm.doc.status;
	const finance = frappe.user.has_role(["Finance Manager", "Finance Officer", "System Manager"]);
	if (status === "Approved") {
		muhick.show_payment_schedule(frm);
		return;
	}
	if (["Rejected", "Cancelled"].includes(status)) {
		return;
	}
	frm.add_custom_button(
		__("Accountability Form"),
		() => frappe.utils.print(frm.doctype, frm.doc.name, `${frm.doctype} Accountability Form`, frm.doc.letter_head || ""),
		__("View")
	);
	if (status === "Paid") {
		frm.set_intro(__("Enter what each line cost, with receipts, in the Accountability section, save, then submit the accountability."), "blue");
		frm.add_custom_button(__("Submit Accountability"), () => {
			// save the expense lines first so the server sees them
			const submit = () => muhick.run(frm, "submit_accountability");
			frm.is_dirty() ? frm.save("Update").then(submit) : submit();
		}).addClass("btn-primary");
	}
	if (status === "Accountability Submitted" && finance) {
		frm.add_custom_button(__("Verify Accountability"), () => {
			frappe.confirm(__("Have the expenses been checked against the supporting documents? They will be posted to the expense accounts."), () =>
				muhick.run(frm, "verify_accountability")
			);
		}).addClass("btn-primary");
	}
	if (status !== "Accounted") {
		return;
	}
	const reference = { fieldname: "reference", fieldtype: "Data", label: __("Reference") };
	if (flt(frm.doc.balance_to_return) > 0 && finance) {
		const posting = frm.doc.issue_entry
			? [
					{
						fieldname: "bank_account",
						fieldtype: "Link",
						options: "Account",
						label: __("Received Into"),
						reqd: 1,
						default: frm.doc.paid_from,
						get_query: () => ({ filters: { company: frm.doc.company, is_group: 0, account_type: ["in", ["Bank", "Cash"]] } }),
					},
					{ fieldname: "on_date", fieldtype: "Date", label: __("Date"), reqd: 1, default: frappe.datetime.get_today() },
			  ]
			: [];
		frm.add_custom_button(__("Record Balance Returned"), () => {
			muhick.prompt_and_run(
				frm,
				__("Balance Returned by the Requester"),
				[
					{
						fieldname: "amount",
						fieldtype: "Currency",
						label: __("Amount Returned"),
						reqd: 1,
						default: flt(frm.doc.balance_to_return) - flt(frm.doc.returned_amount),
					},
					...posting,
					reference,
				],
				"record_return"
			);
		}).addClass("btn-primary");
	}
	if (flt(frm.doc.reimbursement_due) > 0) {
		if (frm.doc.issue_entry) {
			frm.set_intro(__("{0} is due back to the requester. It goes on the next weekly payment plan.", [format_currency(flt(frm.doc.reimbursement_due) - flt(frm.doc.reimbursed_amount))]), "blue");
		} else if (finance) {
			frm.add_custom_button(__("Record Reimbursement Paid"), () => {
				muhick.prompt_and_run(frm, __("Reimbursement Paid"), [reference], "record_reimbursement");
			}).addClass("btn-primary");
		}
	}
};
// END cash requisitions
