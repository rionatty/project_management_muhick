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
		frm.__schedule_error = null;
		const follows_schedule = Boolean((frm.doc.activities || []).length);
		frm.set_df_property("phases", "cannot_add_rows", follows_schedule);
		["phase_name", "planned_start", "planned_end"].forEach((field) =>
			frm.fields_dict.phases.grid.update_docfield_property(field, "read_only", follows_schedule ? 1 : 0)
		);
		const group = __("Schedule");
		if (frm.doc.docstatus === 0 && frm.perm[0].write) {
			frm.add_custom_button(__("Upload from Excel"), () => upload_schedule(frm), group);
		}
		frm.add_custom_button(__("Download Template"), download_template, group);
		if (!frm.is_new()) {
			frm.add_custom_button(__("Download Excel"), () => download_schedule(frm), group);
		}
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
		set_phase_options(frm);
		show_schedule(frm);
		show_unplaced_stages(frm);
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
	...Object.fromEntries(["parent_row", "duration", "start_date", "predecessors", "activities_add", "activities_remove", "activities_move"].map((event) => [event, work_out])),
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

function show_unplaced_stages(frm) {
	if (!frm.doc.project || frm.doc.docstatus === 2 || !(frm.doc.phases || []).length) {
		return;
	}
	frappe
		.xcall("project_management_muhick.muhick_projects.doctype.project_activity_plan.project_activity_plan.unplaced_budget_stages", {
			project: frm.doc.project,
			milestones: frm.doc.phases.map((row) => row.phase_name),
		})
		.then((stages) => {
			if (stages.length) {
				frm.set_intro(
					__("These budget stages have no milestone in this plan, so a request per milestone will not load their items: {0}. Name a milestone after them, or link them on the budget: Budget Lines > Link Stages to Milestones.", [
						stages.map((stage) => frappe.utils.escape_html(stage || __("No Stage"))).join(", "),
					]),
					"orange"
				);
			}
		});
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

// the schedule as it now works out: a subtask goes under its group task, the IDs follow the rows' order and the
// predecessors and group tasks follow the IDs, as in a scheduling tool; a mistake shows above the schedule until it
// is put right
function work_out(frm) {
	clearTimeout(frm.__schedule_timer);
	frm.__schedule_timer = setTimeout(() => {
		const rows = ordered(frm);
		frappe
			.xcall("project_management_muhick.muhick_projects.doctype.project_activity_plan.project_activity_plan.get_worked_schedule", {
				rows: rows.map((r) => ({
					row_id: r.row_id, parent_row: r.parent_row, duration: r.duration, start_date: r.start_date, end_date: r.end_date, predecessors: r.predecessors,
				})),
				project: frm.doc.project,
				plan_date: frm.doc.plan_date,
			})
			.then((result) => {
				frm.__schedule_error = result.error || null;
				(result.rows || []).forEach(({ from, ...values }, position) => Object.assign(rows[from], values, { idx: position + 1 }));
				frm.refresh_field("activities");
				set_phase_options(frm);
				show_schedule(frm);
			});
	}, 200);
}

// what a row is under: any row but itself and those under it, or nothing, which makes it a milestone
function group_options(frm, row) {
	const rows = ordered(frm);
	const out = row ? [row, ...muhick.schedule.under(rows, row)] : [];
	return [{ value: "", label: __("None: it is a milestone") }, ...rows.filter((r) => r.row_id && !out.includes(r)).map((r) => ({ value: String(r.row_id), label: `${r.row_id}: ${r.subject}` }))];
}

function row_fields(frm, values, row, summary) {
	return [
		{ fieldname: "subject", fieldtype: "Data", label: __("Task Name"), reqd: 1, default: values.subject },
		{ fieldname: "parent_row", fieldtype: "Select", label: __("Subtask Of (Group Task)"), options: group_options(frm, row), default: String(values.parent_row || "") },
		{ fieldname: "column_break", fieldtype: "Column Break" },
		{ fieldname: "duration", fieldtype: "Int", label: __("Duration (Days)"), default: values.duration, hidden: summary },
		{ fieldname: "start_date", fieldtype: "Date", label: __("Start"), default: values.start_date, hidden: summary, read_only: Boolean(values.predecessors) },
		{ fieldname: "section", fieldtype: "Section Break" },
		{ fieldname: "predecessors", fieldtype: "Data", label: __("Predecessors"), default: values.predecessors },
		{ fieldname: "responsibility", fieldtype: "Select", label: __("Responsibility"), options: "Muhick\nClient\nSubcontractor\nJoint", default: values.responsibility || "Muhick" },
		{ fieldname: "description", fieldtype: "Small Text", label: __("Description"), default: values.description },
	];
}

// a row moved under another group task takes its subtasks along; one removed takes them too, and the links to them
function edit_row(frm, row) {
	const under = muhick.schedule.under(ordered(frm), row);
	const dialog = new frappe.ui.Dialog({
		title: __("Row {0}", [row.row_id || row.idx]),
		fields: row_fields(frm, row, row, under.length > 0),
		primary_action_label: __("Done"),
		primary_action(values) {
			// a field left empty does not come back with the values
			Object.assign(row, { predecessors: "", description: "", duration: null, start_date: null }, values, { parent_row: cint(values.parent_row) });
			finish_edit(frm, dialog);
		},
		secondary_action_label: __("Remove"),
		secondary_action() {
			const gone = [row, ...under];
			const ids = new Set(gone.map((r) => cint(r.row_id)));
			gone.forEach((r) => frappe.model.clear_doc(ROW, r.name));
			ordered(frm).forEach((r, i) => {
				r.idx = i + 1;
				r.predecessors = String(r.predecessors || "").split(",").filter((link) => link.trim() && !ids.has(parseInt(link))).join(",");
			});
			finish_edit(frm, dialog);
		},
	});
	dialog.show();
}

// a new row goes at the end of the group task's subtasks, or at the end as a milestone
function add_row(frm, under) {
	const group = under ? under.row_id : muhick.schedule.milestone_group(ordered(frm));
	const dialog = new frappe.ui.Dialog({
		title: under ? __("Add Subtask to {0}", [under.subject]) : __("Add Milestone"),
		fields: row_fields(frm, { parent_row: group, duration: 1 }, null, false),
		primary_action_label: __("Add"),
		primary_action(values) {
			Object.assign(frappe.model.add_child(frm.doc, ROW, "activities"), values, { parent_row: cint(values.parent_row), outline_level: under ? cint(under.outline_level) + 1 : 0 });
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
	if (frm.is_dirty()) {
		frappe.msgprint(__("Save first, so the Excel file has the latest rows."));
		return;
	}
	const args = new URLSearchParams({ name: frm.doc.name });
	window.open(`/api/method/project_management_muhick.muhick_projects.doctype.project_activity_plan.project_activity_plan.download_schedule?${args}`);
}

function download_template() {
	window.open("/api/method/project_management_muhick.muhick_projects.doctype.project_activity_plan.project_activity_plan.download_schedule");
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
