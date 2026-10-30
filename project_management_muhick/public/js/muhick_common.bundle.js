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

// A bid's cost estimate (on the opportunity, a table per sheet of the budget workbook) and a project budget have
// the same lines. A line's amount is in the company's currency without VAT: people x qty x rate at its
// exchange rate, a rate quoted with VAT taken without it, or a share of the contract value; its amount as
// quoted is people x qty x rate in its own currency. The server works them out the same way on saving.
muhick.cost_lines = {
	// the opportunity's tables of estimate lines, one per section as the sheets of the budget workbook (see
	// estimate.py); a budget has the one table
	sections: {
		muhick_equipment: "Equipment",
		muhick_materials: "Installation Materials",
		muhick_freight: "Taxes and Freight",
		muhick_labour: "Labour",
		muhick_tools: "Tools and Equipment",
		muhick_preliminaries: "Preliminaries",
		muhick_administrative: "Administrative",
	},
	tables(frm) {
		return frm.doctype === "Opportunity" ? Object.keys(muhick.cost_lines.sections) : ["lines"];
	},
	table_of(frm, section) {
		if (frm.doctype !== "Opportunity") {
			return "lines";
		}
		const sections = muhick.cost_lines.sections;
		return Object.keys(sections).find((field) => sections[field] === section) || "muhick_materials";
	},
	rows(frm) {
		return muhick.cost_lines.tables(frm).flatMap((field) => frm.doc[field] || []);
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
		return row.rate_includes_vat ? amount / (1 + flt(settings.vat_percent) / 100) : amount;
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
				flt(row.contract_percent) ? { amount, qty: 1, rate: amount, quoted_amount: amount } : { amount, quoted_amount: muhick.cost_lines.quoted(row) }
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
				const table = muhick.cost_lines.table_of(frm, values.section);
				const row = frm.add_child(table, { ...values, currency: values.currency || erpnext.get_currency(frm.doc.company) });
				if (muhick.cost_lines.foreign(frm, row)) {
					row.exchange_rate = muhick.cost_lines.used_rate(frm, row) || row.exchange_rate;
				}
				row.amount = muhick.cost_lines.amount(frm, row, settings);
				row.quoted_amount = flt(row.contract_percent) ? row.amount : muhick.cost_lines.quoted(row);
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
			return;
		}
		const before = locals[cdt][cdn].__item || {};
		const row = locals[cdt][cdn];
		frappe
			.xcall("project_management_muhick.muhick_projects.estimate.get_item_details", {
				item_code,
				uom: row.uom && row.uom !== before.uom ? row.uom : null,
				opportunity: frm.doctype === "Opportunity" && !frm.is_new() ? frm.doc.name : null,
				company: frm.doc.company,
			})
			.then((item) => {
				const now = locals[cdt][cdn];
				if (!item.description || !now || now.item_code !== item_code) {
					return;
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
				frappe.model.set_value(cdt, cdn, values);
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
	excel_buttons(frm, can_upload) {
		const grid = frm.fields_dict.lines.grid;
		grid.add_custom_button(__("Download Excel"), () => muhick.cost_lines.download(frm));
		if (can_upload) {
			grid.add_custom_button(__("Upload from Excel"), () => muhick.cost_lines.upload(frm));
		}
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
		const taxes = frm.doctype === "Opportunity" ? result.tax_rows || [] : [];
		const tables = [...muhick.cost_lines.tables(frm), ...(frm.doctype === "Opportunity" ? ["muhick_import_taxes"] : [])];
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
	// a budget's lines totalled section by section (A Equipment, B Installation Materials...) against the
	// stages, as the budget summary sheets lay them out, then the contract value, the cost and the margin; an
	// opportunity shows its estimate sheet by sheet (opportunity.js)
	render_summary(frm) {
		if (frm.doctype === "Opportunity") {
			frm.trigger("render_estimate");
			return;
		}
		const field = frm.fields_dict.phase_summary;
		if (!field) {
			return;
		}
		const order = ["Equipment", "Installation Materials", "Taxes and Freight", "Labour", "Tools and Equipment", "Preliminaries", "Administrative"];
		const cells = {};
		const stages = [];
		muhick.cost_lines.rows(frm).forEach((r) => {
			const stage = r.stage || "";
			if (!stages.includes(stage)) {
				stages.push(stage);
			}
			cells[`${r.section || ""}|${stage}`] = flt(cells[`${r.section || ""}|${stage}`]) + flt(r.amount);
		});
		if (!stages.length) {
			field.$wrapper.html("");
			return;
		}
		stages.sort((a, b) => (a ? 0 : 1) - (b ? 0 : 1));
		const sections = [...order, ""].filter((section) => stages.some((stage) => cells[`${section}|${stage}`]));
		const currency = erpnext.get_currency(frm.doc.company);
		const money = (value) => (value ? format_currency(value, currency) : "");
		const amount = (section, stage) => flt(cells[`${section}|${stage}`]);
		const right = (html) => `<td class="text-right">${html}</td>`;
		const head = stages.map((stage) => `<th class="text-right">${frappe.utils.escape_html(stage || __("No stage"))}</th>`).join("");
		const rows = sections
			.map((section, i) => {
				const values = stages.map((stage) => amount(section, stage));
				const total = values.reduce((sum, value) => sum + value, 0);
				return `<tr><td>${String.fromCharCode(65 + i)}. ${__(section || "Other")}</td>${values.map((v) => right(money(v))).join("")}${right(`<b>${money(total)}</b>`)}</tr>`;
			})
			.join("");
		const by_stage = stages.map((stage) => sections.reduce((sum, section) => sum + amount(section, stage), 0));
		const cost = by_stage.reduce((sum, value) => sum + value, 0);
		const contract = muhick.cost_lines.contract_value(frm);
		const position = contract
			? `<table class="table table-condensed" style="width: auto"><tbody>` +
			  `<tr><td>${__("Revised Contract Value, without VAT")}</td>${right(money(contract))}</tr>` +
			  `<tr><td>${__("Total Cost, without VAT")}</td>${right(money(cost))}</tr>` +
			  `<tr class="bold"><td>${__("Margin")}</td>${right(`${format_currency(contract - cost, currency)} (${flt(((contract - cost) / contract) * 100, 1)}%)`)}</tr>` +
			  `</tbody></table>`
			: "";
		field.$wrapper.html(
			`<div style="overflow-x: auto"><table class="table table-bordered table-condensed">` +
				`<thead><tr><th>${__("Section")}</th>${head}<th class="text-right">${__("Total")}</th></tr></thead>` +
				`<tbody>${rows}<tr class="bold"><td>${__("Total Cost, without VAT")}</td>${by_stage.map((v) => right(money(v))).join("")}${right(money(cost))}</tr></tbody>` +
				`</table></div>${position}`
		);
	},
};

frappe.ui.form.on("Project Budget Line", {
	...Object.fromEntries(
		["qty", "rate", "people", "rate_includes_vat", "contract_percent"].map((field) => [
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
	item_code: (frm, cdt, cdn) => muhick.cost_lines.take_item(frm, cdt, cdn, ["description", "uom", "brand", "cost_code"]),
	// a new line is in the company's currency until another is chosen, so its amounts show in it
	...Object.fromEntries(
		["lines", ...Object.keys(muhick.cost_lines.sections)].map((table) => [
			`${table}_add`,
			(frm, cdt, cdn) => locals[cdt][cdn].currency || frappe.model.set_value(cdt, cdn, "currency", erpnext.get_currency(frm.doc.company)),
		])
	),
	...Object.fromEntries(
		["amount", "section", "stage", "supplier", "lines_remove", ...Object.keys(muhick.cost_lines.sections).map((t) => `${t}_remove`)].map(
			(field) => [field, (frm) => muhick.cost_lines.render_summary(frm)]
		)
	),
});

// run a whitelisted method of the open document, then reload it
muhick.run = function (frm, method, args) {
	return frm.call(method, args || {}).then(() => frm.reload_doc());
};

// ask for some values, then run a document method with them
muhick.prompt_and_run = function (frm, title, fields, method) {
	frappe.prompt(fields, (values) => muhick.run(frm, method, values), title);
};
