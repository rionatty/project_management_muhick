// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

frappe.ui.form.on("Resource Allocation", {
	setup(frm) {
		["from_project", "to_project"].forEach((field) => {
			frm.set_query(field, () => ({ filters: { company: frm.doc.company || "", status: ["!=", "Cancelled"] } }));
		});
	},

	refresh(frm) {
		show_funds(frm);
		if (frm.doc.docstatus !== 1) {
			return;
		}
		const finance = frappe.user.has_role(["Finance Manager", "Finance Officer", "System Manager"]);
		if (finance && flt(frm.doc.outstanding_amount) > 0.005) {
			frm.add_custom_button(__("Record Refund"), () => record_refund(frm));
		}
		["from_project", "to_project"].forEach((field) => {
			frm.add_custom_button(
				__("Funds Statement: {0}", [frm.doc[field]]),
				() => frappe.set_route("query-report", "Project Funds Statement", { project: frm.doc[field] }),
				__("View")
			);
		});
	},

	from_project: show_funds,
	to_project: show_funds,
	company: show_funds,
});

// while it is prepared, what each project has available
function show_funds(frm) {
	frm.set_intro("");
	const projects = [frm.doc.from_project, frm.doc.to_project].filter(Boolean);
	if (frm.doc.docstatus !== 0 || !frm.doc.company || !projects.length) {
		return;
	}
	frappe
		.xcall("project_management_muhick.muhick_finance.doctype.resource_allocation.resource_allocation.get_project_funds", {
			company: frm.doc.company,
			projects,
		})
		.then((funds) => {
			const currency = erpnext.get_currency(frm.doc.company);
			const lines = projects.map((project) =>
				__("{0} has {1} available.", [frappe.utils.escape_html(project), format_currency(funds[project], currency)])
			);
			frm.set_intro(lines.join("<br>"), "blue");
		});
}

function record_refund(frm) {
	frappe.prompt(
		[
			{
				fieldname: "amount",
				fieldtype: "Currency",
				label: __("Amount Refunded"),
				default: frm.doc.outstanding_amount,
				reqd: 1,
			},
			{ fieldname: "refund_date", fieldtype: "Date", label: __("Date"), default: frappe.datetime.get_today(), reqd: 1 },
			{ fieldname: "reference", fieldtype: "Data", label: __("Reference") },
		],
		(values) => frm.call("record_refund", values).then(() => frm.reload_doc()),
		__("Record Refund"),
		__("Record")
	);
}
