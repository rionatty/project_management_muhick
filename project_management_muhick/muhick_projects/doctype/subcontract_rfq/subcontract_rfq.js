// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Subcontract RFQ", {
	setup(frm) {
		muhick.set_project_queries(frm);
	},

	refresh(frm) {
		if (frm.doc.workflow_state === "RFQ Issued" && (frm.doc.quotations || []).length) {
			frm.add_custom_button(__("Email RFQ"), () => email_rfq(frm));
		}
		if (frm.doc.docstatus === 1 && !frm.doc.subcontract_agreement) {
			frm.add_custom_button(__("Subcontract Agreement"), () => {
				frappe.model.open_mapped_doc({
					method: "project_management_muhick.muhick_projects.doctype.subcontract_rfq.subcontract_rfq.make_subcontract_agreement",
					frm: frm,
				});
			}, __("Create"));
		}
	},
});

// to each subcontractor separately, saved first so it goes to the email addresses on the form
function email_rfq(frm) {
	frappe.confirm(__("Email the RFQ to each subcontractor who has not quoted yet?"), () => {
		const send = () =>
			frm.call("email_rfq").then((r) => {
				const { sent, no_email } = r.message;
				const lines = [];
				if (sent.length) {
					lines.push(__("Sent to: {0}.", [sent.map(frappe.utils.escape_html).join(", ")]));
				}
				if (no_email.length) {
					lines.push(__("No email address for: {0}. Enter it on their line, or print the RFQ for them.", [no_email.map(frappe.utils.escape_html).join(", ")]));
				}
				frappe.msgprint({
					title: __("Email RFQ"),
					indicator: no_email.length ? "orange" : "green",
					message: lines.join("<br>") || __("Every subcontractor asked has already quoted."),
				});
			});
		frm.is_dirty() ? frm.save().then(send) : send();
	});
}

frappe.ui.form.on("Subcontract RFQ Quotation", {
	// only one subcontractor can be selected
	is_selected(frm, cdt, cdn) {
		const picked = locals[cdt][cdn];
		if (!picked.is_selected) {
			return;
		}
		(frm.doc.quotations || []).forEach((row) => {
			if (row.name !== picked.name && row.is_selected) {
				frappe.model.set_value(row.doctype, row.name, "is_selected", 0);
			}
		});
	},
	quoted_amount(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (flt(row.quoted_amount) > 0 && !row.quotation_received) {
			frappe.model.set_value(cdt, cdn, "quotation_received", 1);
		}
	},
});
