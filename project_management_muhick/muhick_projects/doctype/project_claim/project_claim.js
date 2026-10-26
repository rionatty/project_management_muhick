// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Project Claim", {
	setup(frm) {
		muhick.set_project_queries(frm);
	},

	refresh(frm) {
		const status = frm.doc.status;
		if (frm.doc.docstatus === 0 && frm.doc.claim_type !== "Advance") {
			frm.add_custom_button(__("Get BOQ Items"), () => get_boq_items(frm));
		}
		if (frm.doc.docstatus !== 1) {
			return;
		}
		if (status === "Submitted to Client") {
			frm.set_intro(__("When the client issues the Interim Certificate: sign it, attach it in Client Certification, then record it."), "blue");
			frm.add_custom_button(__("Record Client Certificate"), () => record_certificate(frm)).addClass("btn-primary");
			frm.add_custom_button(__("Rejected by Client"), () => {
				muhick.prompt_and_run(
					frm,
					__("Claim Rejected by the Client"),
					[{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 }],
					"reject_by_client"
				);
			});
		}
		const finance = frappe.user.has_role(["Finance Manager", "Finance Officer", "System Manager"]);
		if (status === "Certified" && finance) {
			frm.add_custom_button(__("Sales Invoice"), () => {
				frappe
					.call({ method: "project_management_muhick.muhick_projects.doctype.project_claim.project_claim.make_sales_invoice", args: { source_name: frm.doc.name }, freeze: true })
					.then((r) => r.message && frappe.set_route("Form", "Sales Invoice", r.message));
			}, __("Create"));
		}
	},

	project(frm) {
		frm.clear_table("items");
		frm.refresh_field("items");
	},
});

frappe.ui.form.on("Project Claim Item", {
	rate: (frm, cdt, cdn) => frm.script_manager.trigger("this_qty", cdt, cdn),
	this_qty(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		const cumulative = flt(row.previous_qty) + flt(row.this_qty);
		frappe.model.set_value(cdt, cdn, "cumulative_qty", cumulative);
		frappe.model.set_value(cdt, cdn, "this_amount", flt(row.this_qty) * flt(row.rate));
		frappe.model.set_value(cdt, cdn, "cumulative_amount", cumulative * flt(row.rate));
		frappe.model.set_value(cdt, cdn, "percent_complete", flt(row.contract_qty) ? (cumulative / flt(row.contract_qty)) * 100 : 0);
	},
});

function get_boq_items(frm) {
	if (!frm.doc.project) {
		frappe.msgprint(__("Select the project first."));
		return;
	}
	frappe
		.call({
			method: "project_management_muhick.muhick_projects.doctype.project_claim.project_claim.get_claim_items",
			args: { project: frm.doc.project, claim: frm.is_new() ? null : frm.doc.name },
			freeze: true,
		})
		.then((r) => {
			const items = r.message || [];
			if (!items.length) {
				frappe.msgprint(__("This project has no approved BOQ or variation to claim against."));
				return;
			}
			// keep quantities already typed in for this claim
			const typed = {};
			(frm.doc.items || []).forEach((row) => (typed[row.source_row] = row.this_qty));
			frm.clear_table("items");
			items.forEach((item) => {
				const row = frm.add_child("items", item);
				row.this_qty = flt(typed[item.source_row]);
				row.cumulative_qty = flt(row.previous_qty) + row.this_qty;
				row.this_amount = row.this_qty * flt(row.rate);
			});
			frm.refresh_field("items");
			frm.dirty();
		});
}

function record_certificate(frm) {
	if (!frm.doc.signed_certificate) {
		frappe.msgprint(__("Attach the signed certificate in the Client Certification section and save first."));
		return;
	}
	const fields = [
		{ fieldname: "certificate_no", fieldtype: "Data", label: __("Interim Certificate No."), reqd: 1 },
		{ fieldname: "certificate_date", fieldtype: "Date", label: __("Certificate Date"), reqd: 1, default: frappe.datetime.get_today() },
		{ fieldname: "certified_amount", fieldtype: "Currency", label: __("Gross Amount Certified"), reqd: 1, default: frm.doc.gross_claim },
		{ fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks") },
	];
	const certify = () => muhick.prompt_and_run(frm, __("Client Certificate"), fields, "certify");
	// quantities the client reduced are entered on the rows; save them before certifying
	frm.is_dirty() ? frm.save("Update").then(certify) : certify();
}
