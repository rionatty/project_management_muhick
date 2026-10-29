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

// A bid's cost estimate (on the opportunity) and a project budget have the same lines. A line's amount is
// in the company's currency without VAT: people x qty x rate at its exchange rate, a rate quoted with VAT
// taken without it, or a share of the contract value. The server works it out the same way on saving.
muhick.cost_lines = {
	table(frm) {
		return frm.doctype === "Opportunity" ? "muhick_estimate" : "lines";
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
		const amount = flt(row.qty) * flt(row.rate) * (cint(row.people) || 1) * rate;
		return row.rate_includes_vat ? amount / (1 + flt(settings.vat_percent) / 100) : amount;
	},
	set_amount(frm, cdt, cdn) {
		muhick.cost_lines.settings(frm).then((settings) => {
			const row = locals[cdt][cdn];
			const amount = muhick.cost_lines.amount(frm, row, settings);
			frappe.model.set_value(cdt, cdn, flt(row.contract_percent) ? { amount, qty: 1, rate: amount } : { amount });
		});
	},
	// one rate per currency on a budget: the one its other lines in that currency already use
	used_rate(frm, row) {
		const other = (frm.doc[muhick.cost_lines.table(frm)] || []).find(
			(r) => r !== row && r.currency === row.currency && flt(r.exchange_rate)
		);
		return other ? flt(other.exchange_rate) : 0;
	},
	// a rate changed on one line is the budget's rate for that currency: its other lines take it too
	share_rate(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!muhick.cost_lines.foreign(frm, row) || !flt(row.exchange_rate)) {
			return;
		}
		(frm.doc[muhick.cost_lines.table(frm)] || [])
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
	// lines from the server: in a currency the budget already uses, at its rate; then amounts and summary
	add_rows(frm, rows) {
		return muhick.cost_lines.settings(frm).then((settings) => {
			rows.forEach((values) => {
				const row = frm.add_child(muhick.cost_lines.table(frm), values);
				if (muhick.cost_lines.foreign(frm, row)) {
					row.exchange_rate = muhick.cost_lines.used_rate(frm, row) || row.exchange_rate;
				}
				row.amount = muhick.cost_lines.amount(frm, row, settings);
			});
			frm.refresh_field(muhick.cost_lines.table(frm));
			muhick.cost_lines.render_summary(frm);
		});
	},
	// the lines to and from Excel: a file of the saved lines to prepare or change in Excel, and an upload
	// that checks every row first, so a file with mistakes changes nothing
	excel_buttons(frm, can_upload) {
		const grid = frm.fields_dict[muhick.cost_lines.table(frm)].grid;
		grid.add_custom_button(__("Download Excel"), () => {
			if (frm.is_dirty() && !frm.is_new()) {
				frappe.msgprint(__("Save first, so the Excel file has the latest lines."));
				return;
			}
			const args = new URLSearchParams({ doctype: frm.doctype, name: frm.is_new() ? "" : frm.doc.name });
			window.open(`/api/method/project_management_muhick.muhick_projects.estimate.download_cost_lines?${args}`);
		});
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
		const table = muhick.cost_lines.table(frm);
		const take = (replace) => {
			if (replace) {
				frm.clear_table(table);
			}
			muhick.cost_lines.add_rows(frm, result.rows).then(() => {
				frm.dirty();
				frappe.msgprint({
					title: __("Uploaded"),
					indicator: "green",
					message: lines([__("{0} line(s) taken from the Excel file. Save to keep them.", [result.rows.length]), ...result.notes]),
				});
			});
		};
		if (!(frm.doc[table] || []).length) {
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
	// the lines totalled by stage and budget section, then the contract value and the margin
	render_summary(frm) {
		const field = frm.fields_dict[frm.doctype === "Opportunity" ? "muhick_estimate_summary" : "phase_summary"];
		if (!field) {
			return;
		}
		const sections = ["Materials", "Works", "Administrative"];
		const totals = {};
		(frm.doc[muhick.cost_lines.table(frm)] || []).forEach((r) => {
			const stage = (totals[r.stage || ""] = totals[r.stage || ""] || { total: 0 });
			stage[r.budget_section] = flt(stage[r.budget_section]) + flt(r.amount);
			stage.total += flt(r.amount);
		});
		const stages = Object.keys(totals).sort((a, b) => (a ? 0 : 1) - (b ? 0 : 1));
		if (!stages.length) {
			field.$wrapper.html("");
			return;
		}
		const currency = erpnext.get_currency(frm.doc.company);
		const all = { total: 0 };
		stages.forEach((s) => [...sections, "total"].forEach((k) => (all[k] = flt(all[k]) + flt(totals[s][k]))));
		const cells = (t) => [...sections, "total"].map((k) => `<td class="text-right">${format_currency(flt(t[k]), currency)}</td>`).join("");
		const rows = stages
			.map((s) => `<tr><td>${frappe.utils.escape_html(s || __("No stage"))}</td>${cells(totals[s])}</tr>`)
			.join("");
		const heads = [...sections, "Total"].map((s) => `<th class="text-right">${__(s)}</th>`).join("");
		const contract = muhick.cost_lines.contract_value(frm);
		const price = frm.doctype === "Opportunity" ? __("Bid Price") : __("Revised Contract Value");
		const margin = contract
			? `<p>${__("{0} without VAT: {1}. Margin: {2} ({3}%).", [
					price,
					`<b>${format_currency(contract, currency)}</b>`,
					`<b>${format_currency(contract - all.total, currency)}</b>`,
					flt(((contract - all.total) / contract) * 100, 1),
			  ])}</p>`
			: "";
		field.$wrapper.html(
			`<table class="table table-bordered table-condensed"><thead><tr><th>${__("Stage")}</th>${heads}</tr></thead>` +
				`<tbody>${rows}<tr class="bold"><td>${__("Total")}</td>${cells(all)}</tr></tbody></table>${margin}`
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
	...Object.fromEntries(
		["amount", "stage", "budget_section", "lines_remove", "muhick_estimate_remove"].map((field) => [
			field,
			(frm) => muhick.cost_lines.render_summary(frm),
		])
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
