// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Procurement Requisition", {
	setup(frm) {
		frm.set_query("cost_code", "items", () => ({ filters: { disabled: 0 } }));
	},

	refresh(frm) {
		if (flt(frm.doc.total_price_variance) > 0 && frm.doc.docstatus === 0) {
			frm.set_intro(
				__("Sourced prices are {0} above the project budget.", [format_currency(frm.doc.total_price_variance)]),
				"orange"
			);
		}
		show_comparison(frm);
		const rows = frm.doc.items || [];
		const being_prepared = frm.doc.docstatus === 0 && !["Pending COO", "Pending Finance Manager", "Pending General Manager"].includes(frm.doc.workflow_state);
		if (being_prepared && frm.has_perm("write")) {
			frm.add_custom_button(__("Supplier Quotation"), () => get_items_from_quotations(frm), __("Get Items From"));
		}
		if (frm.doc.docstatus === 1 && rows.some((row) => !row.purchase_order)) {
			frm.add_custom_button(__("Purchase Order"), () => make_purchase_orders(frm), __("Create"));
		}
		const over_budget = ["Exceeds Budget", "Not Budgeted"].includes(frm.doc.budget_status) || flt(frm.doc.total_price_variance) > 0;
		if (!frm.is_new() && frm.doc.docstatus < 2 && over_budget && rows.some((row) => row.project) && frappe.model.can_create("Project Budget Revision")) {
			frm.add_custom_button(__("Cost Control Sheet"), () => make_cost_control_sheet(frm), __("Create"));
		}
	},

	before_workflow_action(frm) {
		if (frm.selected_workflow_action !== "Reject" || (frm.doc.rejection_reason || "").trim()) {
			return;
		}
		frappe.dom.unfreeze();
		return new Promise((resolve, reject) => {
			frappe.prompt(
				{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason for Rejection"), reqd: 1 },
				(values) => {
					frm.set_value("rejection_reason", values.reason);
					frm.save().then(resolve, reject);
				},
				__("Reject"),
				__("Reject")
			);
		});
	},

	// a line from a request stays on the request's project
	project(frm) {
		(frm.doc.items || []).forEach((row) => {
			if (!row.material_request_item && row.project !== frm.doc.project) {
				frappe.model.set_value(row.doctype, row.name, { project: frm.doc.project, cost_code: null });
			}
		});
	},
});

frappe.ui.form.on("Procurement Requisition Item", {
	qty: (frm, cdt, cdn) => muhick.set_row_amount(cdt, cdn),
	rate: (frm, cdt, cdn) => muhick.set_row_amount(cdt, cdn),
});

function get_items_from_quotations(frm) {
	const filters = { requisition: frm.doc.name };
	if (frm.doc.company) {
		filters.company = frm.doc.company;
	}
	new frappe.ui.form.MultiSelectDialog({
		doctype: "Supplier Quotation",
		target: frm,
		setters: { supplier: null },
		columns: ["name", "supplier_name", "transaction_date", "valid_till", "grand_total"],
		size: "extra-large",
		get_query: () => ({
			query: "project_management_muhick.muhick_procurement.doctype.procurement_requisition.procurement_requisition.open_quotations",
			filters,
		}),
		action(selections) {
			if (!selections.length) {
				frappe.msgprint(__("Select at least one supplier quotation."));
				return;
			}
			this.dialog.hide();
			frappe
				.xcall("project_management_muhick.muhick_procurement.doctype.procurement_requisition.procurement_requisition.get_quotation_lines", {
					quotations: selections,
					requisition: frm.doc.name,
				})
				.then(({ lines, values }) => add_quotation_lines(frm, lines, values));
		},
	});
}

function add_quotation_lines(frm, lines, values) {
	const present = new Set((frm.doc.items || []).map((row) => row.supplier_quotation_item));
	lines.filter((line) => !present.has(line.supplier_quotation_item)).forEach((line) => frm.add_child("items", line));
	frm.refresh_field("items");
	["company", "project", "delivery_location", "delivery_period"].forEach((field) => {
		if (values[field] && !frm.doc[field]) {
			frm.set_value(field, values[field]);
		}
	});
	if (values.procurement_type === "International") {
		frm.set_value("procurement_type", "International");
	}
}

function make_purchase_orders(frm) {
	frappe
		.call({
			method: "project_management_muhick.muhick_procurement.doctype.procurement_requisition.procurement_requisition.make_purchase_order",
			args: { source_name: frm.doc.name },
			freeze: true,
		})
		.then((r) => {
			const orders = r.message || [];
			if (orders.length === 1) {
				frappe.set_route("Form", "Purchase Order", orders[0]);
			} else if (orders.length) {
				frappe.msgprint({
					title: __("Purchase Orders"),
					indicator: "green",
					message: orders.map((order) => frappe.utils.get_form_link("Purchase Order", order, true)).join("<br>"),
				});
			}
		});
}

function make_cost_control_sheet(frm) {
	const projects = [...new Set((frm.doc.items || []).map((row) => row.project).filter(Boolean))];
	const open_sheet = (project) =>
		frappe.model.open_mapped_doc({
			method: "project_management_muhick.muhick_procurement.doctype.procurement_requisition.procurement_requisition.make_cost_control_sheet",
			frm,
			args: { project },
		});
	if (projects.length > 1) {
		frappe.prompt(
			{ fieldname: "project", fieldtype: "Select", label: __("Project"), options: projects, reqd: 1 },
			(values) => open_sheet(values.project),
			__("Cost Control Sheet"),
			__("Continue")
		);
	} else {
		open_sheet(projects[0]);
	}
}

// each line against what was requested and what was budgeted, in the stock unit and in the company's currency
function show_comparison(frm) {
	const field = frm.get_field("budget_comparison");
	if (!field) {
		return;
	}
	const rows = frm.doc.items || [];
	if (frm.is_new() || !rows.length) {
		field.$wrapper.empty();
		return;
	}
	const text = (value) => frappe.utils.escape_html(value || "");
	const quantity = (value) => (flt(value) ? format_number(value, null, Number.isInteger(flt(value)) ? 0 : 3) : "-");
	const money = (value) => (flt(value) ? format_currency(value) : "-");
	const over = (ok) => (ok ? "" : ' class="text-danger"');
	const body = rows
		.map((row) => {
			const beyond_request = flt(row.material_request_item ? row.requested_qty : row.stock_qty) >= flt(row.stock_qty);
			const beyond_budget = !flt(row.budget_qty) || flt(row.budget_qty) >= flt(row.stock_qty);
			return `<tr>
				<td>${text(row.item_name || row.item_code)}</td>
				<td>${text(row.supplier_name)}</td>
				<td class="text-right">${row.material_request_item ? quantity(row.requested_qty) : "-"}</td>
				<td class="text-right">${quantity(row.budget_qty)}</td>
				<td class="text-right"><span${over(beyond_request && beyond_budget)}>${quantity(row.stock_qty)}</span></td>
				<td class="text-right">${money(row.budget_rate)}</td>
				<td class="text-right">${money(flt(row.rate) * (flt(row.conversion_rate) || 1))}</td>
				<td class="text-right"><span${over(flt(row.price_variance) <= 0)}>${money(row.price_variance)}</span></td>
			</tr>`;
		})
		.join("");
	field.$wrapper.html(`<table class="table table-bordered table-sm" style="font-size: var(--text-sm)">
		<thead><tr>
			<th>${__("Item")}</th>
			<th>${__("Source")}</th>
			<th class="text-right">${__("Requested")}</th>
			<th class="text-right">${__("Budgeted")}</th>
			<th class="text-right">${__("This Requisition")}</th>
			<th class="text-right">${__("Budget Rate")}</th>
			<th class="text-right">${__("Rate")}</th>
			<th class="text-right">${__("Variance")}</th>
		</tr></thead>
		<tbody>${body}</tbody>
	</table>`);
}
