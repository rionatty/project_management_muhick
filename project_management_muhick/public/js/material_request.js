// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Material Request", {
	setup(frm) {
		// a phase is a group task of the project
		frm.set_query("muhick_phase", () => ({
			filters: { project: frm.doc.muhick_project || "", is_group: 1, status: ["!=", "Cancelled"] },
		}));
		frm.set_query("muhick_cost_code", "items", () => ({ filters: { disabled: 0 } }));
	},

	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Frequent Items"), () => pick_frequent_items(frm));
		}
		if (frm.doc.docstatus === 0 && frm.doc.muhick_project && frm.doc.muhick_phase) {
			frm.add_custom_button(__("Get Items from Phase"), () => get_phase_items(frm));
		}
		const status = frm.doc.muhick_budget_status;
		if (status === "Exceeds Budget" || status === "Not Budgeted") {
			// this request follows the longer approval route: COO, Finance Manager, General Manager
			frm.set_intro(`${__(status)}: ${frappe.utils.escape_html(frm.doc.muhick_budget_remarks || "")}`, "orange");
		}
		if (frm.doc.muhick_stock_status === "Insufficient Stock" && !frm.is_new()) {
			frm.set_intro(
				`${__("Not enough stock")}: ${frappe.utils.escape_html(frm.doc.muhick_stock_note || "")}`,
				"orange"
			);
			// not enough in the stores: start the procurement process for the shortfall
			frm.add_custom_button(__("Purchase Request for Shortfall"), () => {
				frappe.model.open_mapped_doc({
					method: "project_management_muhick.overrides.material_request.make_purchase_request",
					frm: frm,
				});
			});
		}
	},

	muhick_project(frm) {
		(frm.doc.items || []).forEach((row) => {
			frappe.model.set_value(row.doctype, row.name, "project", frm.doc.muhick_project);
		});
		frm.set_value("muhick_phase", null);
	},
});

// what the approved activity plan needs for this phase, less what other requests already ask for
function get_phase_items(frm) {
	frappe
		.xcall("project_management_muhick.overrides.material_request.get_phase_items", {
			project: frm.doc.muhick_project,
			phase: frm.doc.muhick_phase,
			material_request: frm.is_new() ? null : frm.doc.name,
		})
		.then((rows) => {
			// a new request starts with an empty row
			(frm.doc.items || []).filter((r) => !r.item_code).forEach((r) => frappe.model.clear_doc(r.doctype, r.name));
			const present = new Set((frm.doc.items || []).map((r) => r.item_code));
			const added = rows.filter((row) => !present.has(row.item_code));
			added.forEach((row) => frm.add_child("items", { ...row, warehouse: row.warehouse || frm.doc.set_warehouse }));
			frm.refresh_field("items");
			frappe.show_alert({
				message: added.length
					? __("{0} item(s) added from the phase plan.", [added.length])
					: __("Nothing left to request for this phase."),
				indicator: added.length ? "green" : "orange",
			});
		});
}

// quick selection of the items bought most often, instead of typing each one
function pick_frequent_items(frm) {
	frappe.call("project_management_muhick.overrides.material_request.get_frequent_items").then((r) => {
		const rows = r.message || [];
		if (!rows.length) {
			frappe.msgprint(__("No purchase history yet to build the list from."));
			return;
		}
		const dialog = new frappe.ui.Dialog({
			title: __("Frequently Bought Items"),
			size: "large",
			fields: [
				{
					fieldname: "items",
					fieldtype: "Table",
					label: __("Enter a quantity against the items required"),
					cannot_add_rows: true,
					cannot_delete_rows: true,
					in_place_edit: true,
					data: rows,
					get_data: () => rows,
					fields: [
						{ fieldname: "item_code", fieldtype: "Link", options: "Item", label: __("Item"), in_list_view: 1, read_only: 1, columns: 3 },
						{ fieldname: "item_name", fieldtype: "Data", label: __("Item Name"), in_list_view: 1, read_only: 1, columns: 4 },
						{ fieldname: "uom", fieldtype: "Data", label: __("UOM"), in_list_view: 1, read_only: 1, columns: 1 },
						{ fieldname: "qty", fieldtype: "Float", label: __("Qty"), in_list_view: 1, columns: 2 },
					],
				},
			],
			primary_action_label: __("Add to Request"),
			async primary_action() {
				const wanted = rows.filter((row) => flt(row.qty) > 0);
				dialog.hide();
				for (const item of wanted) {
					const row = frm.add_child("items");
					await frappe.model.set_value(row.doctype, row.name, "item_code", item.item_code);
					await frappe.model.set_value(row.doctype, row.name, "qty", flt(item.qty));
				}
				frm.refresh_field("items");
			},
		});
		dialog.show();
	});
}
