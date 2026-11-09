// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

// The supplier for each line is picked from the quotations side by side, as the comparison shows them. What is chosen lives
// in the lines behind the view, and the suppliers chosen, with their reasons, in the table under it; saving works both out
// again from the quotations as they stand. What a supplier quoted beyond the request comes with it while it supplies any line.
const SAME = 0.005;
const NOT_COPIED = ["name", "idx", "parent", "parentfield", "parenttype", "doctype", "docstatus", "owner", "creation", "modified", "modified_by", "__islocal", "__unsaved"];
const SHADED = "background: var(--green-highlight-color, #ecfdf5);";

frappe.ui.form.on("Supplier Evaluation", {
	setup(frm) {
		// a row for each supplier chosen in the view above; only its reason is typed
		frm.set_df_property("suppliers", "cannot_add_rows", true);
		frm.set_df_property("suppliers", "cannot_delete_rows", true);
	},

	refresh(frm) {
		if (frm.doc.request_for_quotation && !frm.is_new()) {
			frm.add_custom_button(
				__("Supplier Quotation Comparison"),
				() => frappe.set_route("query-report", "Supplier Quotation Comparison", { request_for_quotation: frm.doc.request_for_quotation }),
				__("View")
			);
		}
		show_selection(frm);
	},

	// a new evaluation starts from the request's quotations, the lowest valid price chosen on each line
	request_for_quotation(frm) {
		if (!frm.is_new()) {
			return;
		}
		frm.clear_table("lines");
		frm.clear_table("suppliers");
		if (!frm.doc.request_for_quotation) {
			frm.refresh_fields();
			show_selection(frm);
			return;
		}
		frappe.xcall("project_management_muhick.muhick_procurement.doctype.supplier_evaluation.supplier_evaluation.make_supplier_evaluation", { source_name: frm.doc.request_for_quotation }).then((doc) => {
			if (!doc.__islocal) {
				frappe.set_route("Form", "Supplier Evaluation", doc.name);
				return;
			}
			(doc.lines || []).forEach((row) => frm.add_child("lines", values_of(row)));
			(doc.suppliers || []).forEach((row) => frm.add_child("suppliers", values_of(row)));
			["items_selected", "items_not_selected", "total_amount", "project", "administration_purchase"].forEach((field) => (frm.doc[field] = doc[field]));
			frm.refresh_fields();
			show_selection(frm);
		});
	},
});

// a row from the server, without what made it that row
function values_of(row) {
	return Object.fromEntries(Object.entries(row).filter(([key]) => !NOT_COPIED.includes(key)));
}

function show_selection(frm) {
	const place = frm.fields_dict.selection_view;
	if (!place) {
		return; // until the site is migrated
	}
	const el = place.$wrapper[0];
	if (!frm.doc.request_for_quotation || !(frm.doc.lines || []).length) {
		el.innerHTML = "";
		return;
	}
	if (el.__selection && el.__selection.request === frm.doc.request_for_quotation) {
		draw(frm, el);
		return;
	}
	frappe.xcall("project_management_muhick.muhick_procurement.doctype.supplier_evaluation.supplier_evaluation.get_selection", { request_for_quotation: frm.doc.request_for_quotation }).then((data) => {
		el.__selection = { ...data, request: frm.doc.request_for_quotation };
		draw(frm, el);
	});
}

function lowest_of(offers) {
	const all = Object.entries(offers || {});
	const valid = all.filter(([, offer]) => !offer.expired);
	const pool = valid.length ? valid : all;
	return pool.length ? Math.min(...pool.map(([, offer]) => flt(offer.rate))) : null;
}

const requested_lines = (frm) => (frm.doc.lines || []).filter((line) => line.request_for_quotation_item);

function draw(frm, el) {
	const data = el.__selection;
	if (!data.quotations.length) {
		el.innerHTML = `<div class="text-muted">${__("No quotation has been recorded against this request yet.")}</div>`;
		return;
	}
	const esc = frappe.utils.escape_html;
	const money = (value) => format_currency(value, data.currency);
	const lines = requested_lines(frm).sort((a, b) => a.idx - b.idx);
	const can_choose = frm.doc.docstatus === 0 && frm.perm[0].write && !frappe.workflow.is_read_only(frm.doctype, frm.doc.name);
	const totals = {};
	(frm.doc.lines || []).forEach((line) => {
		if (line.supplier_quotation) {
			totals[line.supplier_quotation] = flt(totals[line.supplier_quotation]) + flt(line.amount);
		}
	});
	const supplying = new Set(lines.map((line) => line.supplier_quotation).filter(Boolean));
	const item_cell = (row) => `<td>${esc(row.item_name || row.item_code)}<div class="small text-muted">${esc(row.item_code)}</div></td><td class="text-right">${flt(row.qty)} ${esc(row.uom || "")}</td>`;
	const head = data.quotations
		.map(
			(q) =>
				`<th class="text-right" style="min-width: 130px;">${esc(q.supplier_name)}<div class="small text-muted">${esc(q.name)}${q.currency !== data.currency ? ` · ${esc(q.currency)}` : ""}</div>` +
				`<div class="small ${q.expired ? "text-danger" : "text-muted"}">${q.valid_till ? `${__("Valid Till")} ${frappe.datetime.str_to_user(q.valid_till)}` : ""}${q.expired ? ` · ${__("expired")}` : ""}</div></th>`
		)
		.join("");
	const body = lines
		.map((line, i) => {
			const offers = data.offers[line.request_for_quotation_item] || {};
			const lowest = lowest_of(offers);
			const cells = data.quotations
				.map((q) => {
					const offer = offers[q.name];
					if (!offer) {
						return `<td class="text-right text-muted">—</td>`;
					}
					const chosen = line.supplier_quotation === q.name;
					const is_lowest = !offer.expired && lowest !== null && flt(offer.rate) - lowest <= SAME;
					const radio = can_choose && !offer.expired
						? `<input type="radio" name="line-${i}" data-line="${i}" data-quotation="${esc(q.name)}" ${chosen ? "checked" : ""}> `
						: chosen ? "&#10004; " : "";
					return (
						`<td class="text-right" style="${chosen ? SHADED : ""}" data-cell="${esc(q.name)}"><label style="margin: 0; font-weight: ${is_lowest ? 600 : 400}; ${offer.expired ? "text-decoration: line-through;" : ""}">` +
						`${radio}<span class="${is_lowest ? "text-success" : ""}">${money(offer.rate)}</span></label>` +
						(offer.lead_time ? `<div class="small text-muted">${__("{0} days", [offer.lead_time])}</div>` : "") +
						`</td>`
					);
				})
				.join("");
			const none = can_choose
				? `<input type="radio" name="line-${i}" data-line="${i}" data-quotation="" ${line.supplier_quotation ? "" : "checked"}>`
				: line.supplier_quotation ? "" : "&#10004;";
			return `<tr data-line="${esc(line.request_for_quotation_item)}">${item_cell(line)}${cells}<td class="text-center">${none}</td></tr>`;
		})
		.join("");
	// each supplier's own additions, ticked while it supplies a line
	const beyond = (data.beyond || []).length
		? `<tr class="beyond"><td colspan="${data.quotations.length + 3}"><b>${__("Beyond the Request")}</b></td></tr>` +
			data.beyond
				.map((extra) => {
					const with_it = supplying.has(extra.quotation);
					const cells = data.quotations
						.map((q) =>
							q.name === extra.quotation
								? `<td class="text-right" style="${with_it ? SHADED : ""}" data-cell="${esc(q.name)}">${with_it ? "&#10004; " : ""}${money(extra.rate)}</td>`
								: "<td></td>"
						)
						.join("");
					return `<tr class="beyond">${item_cell(extra)}${cells}<td></td></tr>`;
				})
				.join("")
		: "";
	const foot = data.quotations.map((q) => `<td class="text-right">${totals[q.name] ? `<b>${money(totals[q.name])}</b>` : ""}</td>`).join("");
	el.innerHTML =
		`<div style="overflow-x: auto;"><table class="table table-bordered" style="font-size: var(--text-sm, 12px); margin-bottom: 0;">` +
		`<thead><tr><th>${__("Item")}</th><th class="text-right">${__("Qty")}</th>${head}<th class="text-center">${__("No Supplier")}</th></tr></thead>` +
		`<tbody>${body}${beyond}</tbody><tfoot><tr><td colspan="2"><b>${__("Chosen")}</b></td>${foot}<td></td></tr></tfoot></table></div>`;
	el.onchange = (event) => {
		const { line: at, quotation } = event.target.dataset;
		const line = lines[cint(at)];
		if (!line || quotation === undefined) {
			return;
		}
		choose(frm, line, quotation, data);
		draw(frm, el);
	};
}

function choose(frm, line, quotation, data) {
	const offers = data.offers[line.request_for_quotation_item] || {};
	const offer = quotation ? offers[quotation] : null;
	const head = data.quotations.find((q) => q.name === quotation) || {};
	const lowest = lowest_of(offers);
	Object.assign(line, {
		supplier_quotation: offer ? quotation : null,
		supplier: offer ? head.supplier : null,
		supplier_name: offer ? head.supplier_name : null,
		rate: offer ? offer.rate : 0,
		amount: offer ? offer.amount : 0,
		lead_time_days: offer ? cint(offer.lead_time) : 0,
		valid_till: offer ? head.valid_till : null,
		is_lowest: offer && lowest !== null && flt(offer.rate) - lowest <= SAME ? 1 : 0,
	});
	sync_beyond(frm, data);
	sync_suppliers(frm);
	frm.dirty();
}

// what a supplier quoted beyond the request comes with it while it supplies any line
function sync_beyond(frm, data) {
	(frm.doc.lines || []).filter((line) => !line.request_for_quotation_item).forEach((line) => frappe.model.clear_doc(line.doctype, line.name));
	const supplying = new Set(requested_lines(frm).map((line) => line.supplier_quotation).filter(Boolean));
	(data.beyond || [])
		.filter((extra) => supplying.has(extra.quotation))
		.forEach((extra) => {
			const head = data.quotations.find((q) => q.name === extra.quotation) || {};
			frm.add_child("lines", {
				item_code: extra.item_code,
				item_name: extra.item_name,
				qty: extra.qty,
				uom: extra.uom,
				quotes: 1,
				supplier_quotation: extra.quotation,
				supplier: head.supplier,
				supplier_name: head.supplier_name,
				rate: extra.rate,
				amount: extra.amount,
				is_lowest: 0,
				lead_time_days: cint(extra.lead_time),
				valid_till: head.valid_till,
				supplier_quotation_items: (extra.rows || []).join(","),
			});
		});
}

// a row for each supplier chosen, its reason kept while it stays chosen
function sync_suppliers(frm) {
	const reasons = {};
	(frm.doc.suppliers || []).forEach((row) => (reasons[row.supplier_quotation] = row.reason));
	const chosen = {};
	(frm.doc.lines || []).forEach((line) => {
		if (!line.supplier_quotation) {
			return;
		}
		const row = (chosen[line.supplier_quotation] = chosen[line.supplier_quotation] || {
			supplier: line.supplier, supplier_name: line.supplier_name, supplier_quotation: line.supplier_quotation, items: 0, lowest_items: 0, amount: 0,
		});
		row.items += 1;
		row.lowest_items += cint(line.is_lowest);
		row.amount += flt(line.amount);
	});
	frm.clear_table("suppliers");
	Object.values(chosen).forEach((row) => frm.add_child("suppliers", { ...row, reason: reasons[row.supplier_quotation] || "" }));
	const requested = requested_lines(frm);
	const selected = requested.filter((line) => line.supplier_quotation);
	frm.doc.items_selected = selected.length;
	frm.doc.items_not_selected = requested.length - selected.length;
	frm.doc.total_amount = (frm.doc.lines || []).filter((line) => line.supplier_quotation).reduce((sum, line) => sum + flt(line.amount), 0);
	frm.refresh_fields();
}
