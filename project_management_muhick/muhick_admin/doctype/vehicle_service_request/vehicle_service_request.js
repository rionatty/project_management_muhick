// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Vehicle Service Request", {
	refresh(frm) {
		if (frm.doc.docstatus === 1 && frm.doc.status === "Approved") {
			frm.add_custom_button(__("Record Completion"), () => {
				muhick.prompt_and_run(
					frm,
					__("Service Completed"),
					[
						{ fieldname: "actual_cost", fieldtype: "Currency", label: __("Actual Cost"), reqd: 1, default: frm.doc.estimated_cost },
						{ fieldname: "completed_on", fieldtype: "Date", label: __("Completed On"), reqd: 1, default: frappe.datetime.get_today() },
						{ fieldname: "invoice_reference", fieldtype: "Data", label: __("Invoice / Job Card No.") },
						{ fieldname: "next_service_date", fieldtype: "Date", label: __("Next Service Due") },
						{ fieldname: "next_service_odometer", fieldtype: "Int", label: __("Next Service at (km)") },
					],
					"complete"
				);
			}).addClass("btn-primary");
		}
	},
});
