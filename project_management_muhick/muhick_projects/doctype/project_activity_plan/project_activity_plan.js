// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

// The schedule reads as muhick.schedule draws it (muhick_common.bundle.js), and is worked out on the server as it is
// changed, so the dates on screen are the ones saving will keep.
const ROW = "Project Activity Plan Activity";
const ordered = (frm) => [...(frm.doc.activities || [])].sort((a, b) => a.idx - b.idx);

frappe.ui.form.on("Project Activity Plan", {
	setup(frm) {
		frm.set_query("item_code", "items", () => ({ filters: { disabled: 0 } }));
	},

	refresh(frm) {
		set_phase_options(frm);
		frm.__schedule_error = null;
		show_schedule(frm);
		const follows_schedule = Boolean((frm.doc.activities || []).length);
		frm.set_df_property("phases", "cannot_add_rows", follows_schedule);
		["phase_name", "planned_start", "planned_end"].forEach((field) =>
			frm.fields_dict.phases.grid.update_docfield_property(field, "read_only", follows_schedule ? 1 : 0)
		);
		const group = __("Schedule");
		if (frm.doc.docstatus === 0 && frm.perm[0].write) {
			frm.add_custom_button(__("Upload from Excel"), () => upload_schedule(frm), group);
		}
		frm.add_custom_button(__("Download Excel"), () => download_schedule(frm), group);
		if (frm.doc.docstatus === 0 && frm.doc.project && !frm.doc.revision_of) {
			frm.add_custom_button(__("Get Milestones"), () => get_phases(frm), group);
		}
		if (frm.doc.docstatus === 1 && frm.doc.is_current) {
			frm.add_custom_button(__("Revise Plan"), () => {
				frappe.model.open_mapped_doc({
					method: "project_management_muhick.muhick_projects.doctype.project_activity_plan.project_activity_plan.make_revision",
					frm: frm,
				});
			});
		}
	},

	project(frm) {
		set_phase_options(frm);
	},
});

frappe.ui.form.on("Project Activity Plan Phase", {
	phase_name: set_phase_options,
	phases_remove: set_phase_options,
});

frappe.ui.form.on(ROW, {
	...Object.fromEntries(["outline_level", "duration", "start_date", "predecessors", "activities_add", "activities_remove", "activities_move"].map((event) => [event, work_out])),
	// a finish typed by hand sets the duration
	end_date(frm, cdt, cdn) {
		locals[cdt][cdn].duration = null;
		work_out(frm);
	},
	subject: show_schedule,
	responsibility: show_schedule,
});

// the milestones of the items table are this plan's
function set_phase_options(frm) {
	const rows = ordered(frm);
	const names = rows.length ? muhick.schedule.milestones(rows) : (frm.doc.phases || []).map((r) => r.phase_name);
	frm.fields_dict.items.grid.update_docfield_property("phase_name", "options", ["", ...names.filter(Boolean)]);
}

function show_schedule(frm) {
	const place = frm.fields_dict.schedule_view;
	if (!place) {
		return; // until the site is migrated
	}
	const options = { error: frm.__schedule_error };
	if (frm.doc.docstatus === 1) {
		frappe.xcall("project_management_muhick.muhick_projects.doctype.project_activity_plan.project_activity_plan.get_live_schedule", { plan: frm.doc.name }).then((result) =>
			muhick.schedule.render(place.$wrapper, frm.doc.activities || [], { ...options, ...result, can_write: frappe.model.can_write("Task"), on_change: () => show_schedule(frm) })
		);
		return;
	}
	muhick.schedule.render(
		place.$wrapper,
		frm.doc.activities || [],
		frm.doc.docstatus === 0 && frm.perm[0].write ? { ...options, on_edit: (row) => edit_row(frm, row), on_add: (under) => add_row(frm, under) } : options
	);
}

// the schedule as it now works out: its IDs follow the rows' order and the predecessors follow the IDs, as in a
// scheduling tool; a mistake shows above the schedule until it is put right
function work_out(frm) {
	clearTimeout(frm.__schedule_timer);
	frm.__schedule_timer = setTimeout(() => {
		const rows = ordered(frm);
		frappe
			.xcall("project_management_muhick.muhick_projects.doctype.project_activity_plan.project_activity_plan.get_worked_schedule", {
				rows: rows.map((r) => ({
					row_id: r.row_id, outline_level: r.outline_level, duration: r.duration, start_date: r.start_date, end_date: r.end_date, predecessors: r.predecessors,
				})),
				project: frm.doc.project,
				plan_date: frm.doc.plan_date,
			})
			.then((result) => {
				frm.__schedule_error = result.error || null;
				(result.rows || []).forEach((values, i) => rows[i] && Object.assign(rows[i], values));
				frm.refresh_field("activities");
				set_phase_options(frm);
				show_schedule(frm);
			});
	}, 200);
}

function row_fields(values, summary) {
	return [
		{ fieldname: "subject", fieldtype: "Data", label: __("Task Name"), reqd: 1, default: values.subject },
		{ fieldname: "outline_level", fieldtype: "Int", label: __("Level"), default: cint(values.outline_level) },
		{ fieldname: "column_break", fieldtype: "Column Break" },
		{ fieldname: "duration", fieldtype: "Int", label: __("Duration (Days)"), default: values.duration, hidden: summary },
		{ fieldname: "start_date", fieldtype: "Date", label: __("Start"), default: values.start_date, hidden: summary, read_only: Boolean(values.predecessors) },
		{ fieldname: "section", fieldtype: "Section Break" },
		{ fieldname: "predecessors", fieldtype: "Data", label: __("Predecessors"), default: values.predecessors },
		{ fieldname: "responsibility", fieldtype: "Select", label: __("Responsibility"), options: "Muhick\nClient\nSubcontractor\nJoint", default: values.responsibility || "Muhick" },
		{ fieldname: "description", fieldtype: "Small Text", label: __("Description"), default: values.description },
	];
}

// a row moved to another level takes the rows under it along
function edit_row(frm, row) {
	const rows = ordered(frm);
	const at = rows.indexOf(row);
	const level = cint(row.outline_level);
	const end = rows.findIndex((r, i) => i > at && cint(r.outline_level) <= level);
	const under = rows.slice(at + 1, end < 0 ? rows.length : end);
	const dialog = new frappe.ui.Dialog({
		title: __("Row {0}", [row.row_id || row.idx]),
		fields: row_fields(row, under.length > 0),
		primary_action_label: __("Done"),
		primary_action(values) {
			const moved = cint(values.outline_level) - level;
			under.forEach((r) => (r.outline_level = Math.max(cint(r.outline_level) + moved, 0)));
			// a field left empty does not come back with the values
			Object.assign(row, { predecessors: "", description: "", duration: null, start_date: null }, values, { outline_level: Math.max(cint(values.outline_level), 0) });
			finish_edit(frm, dialog);
		},
		secondary_action_label: __("Remove"),
		secondary_action() {
			[row, ...under].forEach((r) => frappe.model.clear_doc(ROW, r.name));
			ordered(frm).forEach((r, i) => (r.idx = i + 1));
			finish_edit(frm, dialog);
		},
	});
	dialog.show();
}

// a new row goes at the end of what sits under the row it is added to, or at the end as a milestone
function add_row(frm, under) {
	const rows = ordered(frm);
	const at = under ? rows.indexOf(under) : -1;
	const level = under ? cint(under.outline_level) + 1 : muhick.schedule.milestone_level(rows);
	const end = under ? rows.findIndex((r, i) => i > at && cint(r.outline_level) < level) : -1;
	const dialog = new frappe.ui.Dialog({
		title: under ? __("Add under {0}", [under.subject]) : __("Add Milestone"),
		fields: row_fields({ outline_level: level, duration: 1 }, false),
		primary_action_label: __("Add"),
		primary_action(values) {
			Object.assign(frappe.model.add_child(frm.doc, ROW, "activities", end < 0 ? undefined : rows[end].idx), values);
			finish_edit(frm, dialog);
		},
	});
	dialog.show();
}

function finish_edit(frm, dialog) {
	dialog.hide();
	frm.dirty();
	frm.refresh_field("activities");
	work_out(frm);
}

function upload_schedule(frm) {
	new frappe.ui.FileUploader({
		as_dataurl: true,
		allow_multiple: false,
		restrictions: { allowed_file_types: [".xlsx", ".xls", ".csv"] },
		on_success: (file) => frappe.xcall("project_management_muhick.muhick_projects.doctype.project_activity_plan.project_activity_plan.read_schedule", { filename: file.name, content: file.dataurl }).then((result) => take_schedule(frm, result)),
	});
}

function take_schedule(frm, result) {
	if (result.errors.length) {
		frappe.msgprint({ title: __("Nothing was uploaded"), indicator: "red", message: result.errors.map((text) => frappe.utils.escape_html(text)).join("<br>") });
		return;
	}
	const take = () => {
		frm.clear_table("activities");
		result.rows.forEach((row) => frm.add_child("activities", row));
		frm.refresh_field("activities");
		frm.dirty();
		work_out(frm);
		frappe.show_alert({ message: __("{0} row(s) taken from the Excel file. Save to keep them.", [result.rows.length]), indicator: "green" });
	};
	if ((frm.doc.activities || []).length) {
		frappe.confirm(__("Replace this plan's schedule with the rows of the Excel file?"), take);
	} else {
		take();
	}
}

function download_schedule(frm) {
	if (frm.is_dirty() && !frm.is_new()) {
		frappe.msgprint(__("Save first, so the Excel file has the latest rows."));
		return;
	}
	const args = new URLSearchParams({ name: frm.is_new() ? "" : frm.doc.name });
	window.open(`/api/method/project_management_muhick.muhick_projects.doctype.project_activity_plan.project_activity_plan.download_schedule?${args}`);
}

// load the milestones and their activities from a Project Template, or from the project's own tasks
function get_phases(frm) {
	frappe.prompt(
		[
			{
				fieldname: "project_template",
				fieldtype: "Link",
				options: "Project Template",
				label: __("Project Template"),
			},
		],
		(values) => {
			frappe
				.xcall("project_management_muhick.muhick_projects.doctype.project_activity_plan.project_activity_plan.load_phases", {
					project: frm.doc.project,
					project_template: values.project_template || null,
				})
				.then((r) => {
					if (!r.phases.length) {
						frappe.msgprint(__("No milestones found. Add them in the table, or set up a Project Template."));
						return;
					}
					frm.clear_table("phases");
					frm.clear_table("activities");
					r.phases.forEach((row) => frm.add_child("phases", row));
					r.activities.forEach((row) => frm.add_child("activities", row));
					if ((r.items || []).length) {
						frm.clear_table("items");
						r.items.forEach((row) => frm.add_child("items", row));
					}
					frm.refresh_fields();
					frm.dirty();
					work_out(frm);
				});
		},
		__("Get Milestones"),
		__("Load")
	);
}
