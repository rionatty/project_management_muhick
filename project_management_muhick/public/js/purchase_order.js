// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

// Finance applies to the bank for it, then records it here for the consignment to read
function offer_letter_of_credit(frm) {
	const filters = { purchase_order: frm.doc.name, instrument_type: "Letter of Credit", status: ["!=", "Cancelled"] };
	frappe.db.get_value("Bank Instrument", filters, "name").then(({ message }) => {
		if (message && message.name) {
			return;
		}
		frm.set_intro(__("The payment terms need a letter of credit. Apply to the bank, then record it from Create."), "blue");
		frm.add_custom_button(
			__("Letter of Credit"),
			() => {
				const supplier = frm.doc.supplier_name || frm.doc.supplier;
				frappe.new_doc("Bank Instrument", {
					instrument_type: "Letter of Credit",
					title: `${__("Letter of Credit")} - ${supplier} - ${frm.doc.name}`,
					purchase_order: frm.doc.name,
					beneficiary: supplier,
					amount: frm.doc.base_grand_total,
					project: frm.doc.project,
					company: frm.doc.company,
				});
			},
			__("Create")
		);
	});
}

frappe.ui.form.on("Purchase Order", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) {
			return;
		}
		// a delivery note for goods going on to site, raised from the approved order
		frm.add_custom_button(
			__("Delivery to Site"),
			() => {
				frappe.model.open_mapped_doc({
					method: "project_management_muhick.overrides.buying.make_site_transfer",
					frm: frm,
				});
			},
			__("Create")
		);
		if (frm.doc.muhick_payment_type === "Advance" && flt(frm.doc.advance_paid) + flt(frm.doc.muhick_paid_on_requisition) === 0) {
			frm.set_intro(
				__("The payment terms need an advance of {0}%. Raise the Payment Request from Create.", [
					flt(frm.doc.muhick_advance_percent),
				]),
				"blue"
			);
		}
		if (frm.doc.muhick_payment_type === "Letter of Credit" && frappe.model.can_create("Bank Instrument")) {
			offer_letter_of_credit(frm);
		}
		if (frm.doc.muhick_procurement_type !== "Local") {
			frm.add_custom_button(
				__("Consignment Tracking"),
				() => {
					frappe.new_doc("Import Shipment", {
						purchase_order: frm.doc.name,
						company: frm.doc.company,
						title: `${frm.doc.supplier_name || frm.doc.supplier} - ${frm.doc.name}`,
					});
				},
				__("Create")
			);
		}
	},
});
