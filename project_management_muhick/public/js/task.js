// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

// A milestone (phase) is a group task of the project; its activities are the tasks under it.
frappe.ui.form.on("Task", {
	refresh(frm) {
		if (!frm.doc.is_group || frm.is_new() || !frm.doc.project) {
			return;
		}
		show_milestone_overview(frm);
		frm.add_custom_button(
			__("Material Request"),
			() =>
				frappe.new_doc("Material Request", {
					material_request_type: "Purchase",
					muhick_request_origin: "Project",
					muhick_project: frm.doc.project,
					muhick_phase: frm.doc.name,
				}),
			__("Create")
		);
		const done = frm.doc.status === "Completed" || flt(frm.doc.progress) >= 100;
		if (frm.doc.muhick_is_billing_milestone && done && !frm.doc.muhick_billing_status) {
			frm.add_custom_button(__("Create Claim"), () => {
				frappe.new_doc("Project Claim", { project: frm.doc.project, phase: frm.doc.name });
			}).addClass("btn-primary");
		}
	},
});

// the milestone's activities, the items the approved plan needs for it, and its budget
function show_milestone_overview(frm) {
	const field = frm.get_field("muhick_milestone_overview");
	if (!field) {
		return;
	}
	frappe
		.xcall("project_management_muhick.overrides.task.get_milestone_overview", { task: frm.doc.name })
		.then((r) => {
			const esc = frappe.utils.escape_html;
			const table = (head, rows) =>
				`<table class="table table-bordered table-condensed"><thead><tr>${head
					.map((h) => `<th>${h}</th>`)
					.join("")}</tr></thead><tbody>${rows.join("")}</tbody></table>`;
			const activities = r.activities.map(
				(a) => `<tr><td>${frappe.utils.get_form_link("Task", a.name, true, esc(a.subject))}</td>
					<td>${esc(__(a.status))}</td><td class="text-right">${flt(a.progress)}%</td></tr>`
			);
			const items = r.items.map((i) => {
				const short = flt(i.requested) + 1e-9 < flt(i.qty);
				return `<tr><td>${esc(i.item_code)}</td><td>${esc(i.item_name || "")}</td>
					<td class="text-right">${flt(i.qty)} ${esc(i.uom || "")}</td>
					<td class="text-right ${short ? "text-warning" : ""}">${flt(i.requested)}</td></tr>`;
			});
			let html = `<p><b>${__("Budget")}:</b> ${format_currency(r.budget)}</p>`;
			html += `<h6>${__("Activities (Tasks)")}</h6>`;
			html += activities.length
				? table([__("Activity"), __("Status"), __("Progress")], activities)
				: `<p class="text-muted">${__("No tasks under this milestone yet.")}</p>`;
			html += `<h6>${__("Items Required")}</h6>`;
			html += items.length
				? table([__("Item"), __("Name"), __("Required"), __("Requested")], items)
				: `<p class="text-muted">${__("The approved activity plan lists no items for this milestone.")}</p>`;
			field.$wrapper.html(html);
		});
}
