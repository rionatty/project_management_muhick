// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Bid Outcome", {
	setup(frm) {
		// the bid's own quotations that price the line's item
		frm.set_query("supplier_quotation", "lines", (doc, cdt, cdn) => ({
			filters: [
				["Supplier Quotation", "opportunity", "=", doc.opportunity],
				["Supplier Quotation", "docstatus", "<", 2],
				["Supplier Quotation Item", "item_code", "=", locals[cdt][cdn].item_code],
			],
		}));
	},

	refresh(frm) {
		// the lines are the bid's BOQ
		frm.set_df_property("lines", "cannot_add_rows", true);
		frm.set_df_property("lines", "cannot_delete_rows", true);
		if (frm.doc.opportunity) {
			frm.add_custom_button(__("Supplier Comparison"), () =>
				frappe.set_route("query-report", "Bid Margin Comparison", { opportunity: frm.doc.opportunity })
			);
		}
		if (frm.doc.docstatus === 0 && !frm.is_new() && frm.doc.outcome === "Won") {
			frm.add_custom_button(__("Refresh Prices"), () => muhick.run(frm, "refresh_prices"));
		}
		const today = frappe.datetime.get_today();
		const lines = frm.doc.lines || [];
		const expired = lines.filter((l) => l.supplier_quotation && l.valid_till && l.valid_till < today);
		const no_cost = lines.filter((l) => !flt(l.cost_rate));
		const notes = [];
		if (expired.length) {
			notes.push(__("{0} line(s) are priced at a quotation that has expired. Confirm those prices with the supplier.", [expired.length]));
		}
		if (no_cost.length && !frm.is_new()) {
			notes.push(__("{0} line(s) have no cost, so the margin counts them in full.", [no_cost.length]));
		}
		if (notes.length) {
			frm.dashboard.set_headline(notes.join("<br>"), "orange");
		}
	},
});

frappe.ui.form.on("Bid Outcome Line", {
	// the line's cost at the chosen quotation, shown before the report is saved
	supplier_quotation(frm, cdt, cdn) {
		const line = locals[cdt][cdn];
		if (!line.supplier_quotation) {
			// saved, it goes back to what the estimate has it costing
			frappe.model.set_value(cdt, cdn, { supplier: "", valid_till: "", cost_rate: 0, cost_source: "" });
			return;
		}
		frappe
			.xcall("project_management_muhick.muhick_sales.doctype.bid_outcome.bid_outcome.get_quote_price", {
				opportunity: frm.doc.opportunity,
				supplier_quotation: line.supplier_quotation,
				item_code: line.item_code,
				uom: line.uom,
			})
			.then((price) => frappe.model.set_value(cdt, cdn, price));
	},

	cost_rate(frm, cdt, cdn) {
		const line = locals[cdt][cdn];
		const cost = flt(line.qty) * flt(line.cost_rate);
		frappe.model.set_value(cdt, cdn, {
			cost_amount: cost,
			margin: flt(line.bid_amount) - cost,
			margin_percent: flt(line.bid_amount) ? ((flt(line.bid_amount) - cost) / flt(line.bid_amount)) * 100 : 0,
		});
	},
});
