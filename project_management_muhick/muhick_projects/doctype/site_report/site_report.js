// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

// Progress is reported on each task: each milestone shows with its group tasks and subtasks, as on the activity schedule,
// and what sits above a task adds up as the server will add it up on saving. The rows live in the table behind the view.
frappe.ui.form.on("Site Report", {
	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Fetch from System"), () => fetch_tasks(frm)).addClass("btn-primary");
		}
		show_progress(frm);
	},

	project(frm) {
		// the rows are that project's
		frm.clear_table("phases");
		frm.__fetched = false;
		show_progress(frm);
		fetch_when_ready(frm);
	},

	period_from: fetch_when_ready,

	period_to(frm) {
		fetch_when_ready(frm);
		if ((frm.doc.phases || []).length) {
			add_up(frm);
			show_progress(frm);
		}
	},

	report_type(frm) {
		if (frm.doc.period_from || !frm.doc.report_type) {
			return;
		}
		const today = frappe.datetime.get_today();
		const days = { Weekly: -6, Monthly: -29 }[frm.doc.report_type];
		if (days) {
			frm.set_value("period_from", frappe.datetime.add_days(today, days));
			frm.set_value("period_to", today);
		}
	},
});

// a new report brings the tasks as soon as it knows the project and the period
function fetch_when_ready(frm) {
	clearTimeout(frm.__fetch_timer);
	frm.__fetch_timer = setTimeout(() => {
		if (frm.is_new() && frm.doc.project && frm.doc.period_from && frm.doc.period_to && !(frm.doc.phases || []).length) {
			fetch_tasks(frm);
		}
	}, 100);
}

function fetch_tasks(frm) {
	if (!(frm.doc.project && frm.doc.period_from && frm.doc.period_to)) {
		frappe.msgprint(__("Select the project and the period first."));
		return;
	}
	// fills each milestone with its tasks, labour by trade, materials issued and equipment on site
	frm.call("fetch_from_system").then(() => {
		frm.__fetched = true;
		frm.refresh_fields();
		frm.dirty();
		show_progress(frm);
	});
}

function outline(frm) {
	const rows = [...(frm.doc.phases || [])].sort((a, b) => a.idx - b.idx);
	const under = {};
	rows.forEach((row) => (under[row.parent_task || ""] = under[row.parent_task || ""] || []).push(row));
	return { rows, under, milestones: under[""] || [] };
}

function weighted(pairs) {
	if (!pairs.length) {
		return 0;
	}
	const total = pairs.reduce((sum, [weight]) => sum + flt(weight), 0);
	const reading = total > 0 ? pairs.reduce((sum, [weight, percent]) => sum + flt(weight) * flt(percent), 0) / total : pairs.reduce((sum, [, percent]) => sum + flt(percent), 0) / pairs.length;
	return flt(reading, 2);
}

function planned(row, on_date) {
	const days = (from, to) => frappe.datetime.get_diff(to, from);
	if (!on_date || days(row.planned_start, on_date) < 0) {
		return 0;
	}
	if (days(row.planned_end, on_date) >= 0 || days(row.planned_start, row.planned_end) <= 0) {
		return 100;
	}
	return flt((days(row.planned_start, on_date) / days(row.planned_start, row.planned_end)) * 100, 2);
}

function add_up(frm) {
	const { under, milestones } = outline(frm);
	const settle = (row) => {
		const tasks = under[row.phase] || [];
		if (tasks.length) {
			tasks.forEach(settle);
			row.planned_percent = weighted(tasks.map((task) => [task.task_weight, task.planned_percent]));
			row.actual_percent = weighted(tasks.map((task) => [task.task_weight, task.actual_percent]));
		} else if (row.planned_start && row.planned_end) {
			row.planned_percent = planned(row, frm.doc.period_to);
		}
		row.variance_percent = flt(flt(row.actual_percent) - flt(row.planned_percent), 2);
	};
	milestones.forEach(settle);
	frm.doc.planned_progress = weighted(milestones.map((row) => [row.task_weight, row.planned_percent]));
	frm.doc.overall_progress = weighted(milestones.map((row) => [row.task_weight, row.actual_percent]));
	frm.refresh_field("planned_progress");
	frm.refresh_field("overall_progress");
}

const COLUMNS = "display: grid; grid-template-columns: 20px 30px minmax(240px, 1fr) 64px 64px 62px 62px 72px 66px minmax(170px, 1fr); gap: 6px; align-items: center;";
const STYLE = `<style>
	.muhick-progress a { text-decoration: none; }
	.muhick-progress .sr-columns { ${COLUMNS} margin-left: 28px; padding-bottom: 4px; font-size: var(--text-xs, 11px); color: var(--text-muted); }
	.muhick-progress .sr-row { ${COLUMNS} padding: 3px 0; border-top: 1px solid var(--border-color); }
	.muhick-progress .sr-head { ${COLUMNS} padding: 6px 0 4px; font-weight: 600; font-size: var(--text-md, 13px); }
	.muhick-progress .sr-group { font-weight: 600; background: var(--subtle-fg, transparent); }
	.muhick-progress .sr-small { font-size: var(--text-xs, 11px); font-weight: normal; }
	.muhick-progress .sr-num { text-align: right; }
	.muhick-progress .sr-card { border-left: 2px solid; padding-left: 10px; margin-bottom: 10px; }
	.muhick-progress input { height: 26px; padding: 2px 6px; font-weight: normal; }
	.muhick-progress input[type="number"] { text-align: right; }
</style>`;

function show_progress(frm) {
	const place = frm.fields_dict.progress_view;
	if (!place) {
		return; // until the site is migrated
	}
	const el = place.$wrapper[0];
	const { rows, under, milestones } = outline(frm);
	if (!rows.length) {
		el.__progress = null;
		el.innerHTML = frm.__fetched ? `<div class="text-muted">${__("This project has no milestones or tasks yet.")}</div>` : "";
		return;
	}
	const esc = frappe.utils.escape_html;
	const can_edit = frm.doc.docstatus === 0 && frm.perm[0].write;
	const tasks_of = (row) => (under[row.phase] || []).length ? under[row.phase].flatMap(tasks_of) : [row];
	const is_done = (row) => flt(row.actual_percent) >= 100;
	const has_begun = (row) => flt(row.actual_percent) > 0;
	// the milestones work is due on stay open, or else the first not finished
	const due = (row) => tasks_of(row).some((task) => !is_done(task) && flt(task.planned_percent) > 0);
	if (!el.__progress || el.__progress.report !== frm.doc.name) {
		const first_open = milestones.find((row) => tasks_of(row).some((task) => !is_done(task)));
		el.__progress = { report: frm.doc.name, filter: "All", folded: new Set(milestones.filter((row) => !due(row) && row !== first_open).map((row) => row.phase)) };
	}
	const state = el.__progress;
	const passes = (row) => {
		if ((under[row.phase] || []).length) {
			return under[row.phase].some(passes);
		}
		if (state.filter === "This Period") {
			return (!row.planned_start || row.planned_start <= frm.doc.period_to) && (!row.planned_end || row.planned_end >= frm.doc.period_from);
		}
		return state.filter === "Behind" ? flt(row.variance_percent) < 0 : true;
	};
	const percent = (value) => `${flt(value, 2)}%`;
	const shown_date = (value) => (value ? String(value).slice(0, 10).split("-").reverse().map((part, i) => (i === 2 ? part.slice(2) : part)).join("/") : "");
	const variance = (row) => {
		const value = flt(row.variance_percent);
		return `<span class="sr-num ${value < 0 ? "text-danger" : value > 0 ? "text-success" : ""}">${value > 0 ? "+" : ""}${percent(value)}</span>`;
	};
	const at = (row) => rows.indexOf(row);
	const comment = (row) =>
		can_edit
			? `<input type="text" class="form-control" data-row="${at(row)}" data-field="remarks" value="${esc(row.remarks || "")}">`
			: `<span class="sr-small" style="white-space: pre-wrap;">${esc(row.remarks || "")}</span>`;
	const actual = (row, group) =>
		can_edit && !group
			? `<input type="number" min="0" max="100" step="any" class="form-control" data-row="${at(row)}" data-field="actual_percent" value="${flt(row.actual_percent)}">`
			: `<span class="sr-num">${percent(row.actual_percent)}</span>`;
	const cells = (row, name, group) => {
		const fold = `<a data-act="fold" data-row="${at(row)}" href="#">${state.folded.has(row.phase) ? "&#9656;" : "&#9662;"}</a>`;
		const circle = `<span style="color: var(--${is_done(row) ? "green" : has_begun(row) ? "blue" : "gray"}-500, inherit);">${is_done(row) ? "&#10004;" : has_begun(row) ? "&#9680;" : "&#9675;"}</span>`;
		return (
			`${group ? fold : circle}<span class="text-muted sr-small">${esc(row.row_id || "")}</span><div>${name}</div>` +
			`<span class="sr-small">${shown_date(row.planned_start)}</span><span class="sr-small">${shown_date(row.planned_end)}</span>` +
			`<span class="sr-num">${percent(row.planned_percent)}</span><span class="sr-num text-muted">${group ? "" : percent(row.previous_percent)}</span>` +
			`${actual(row, group)}${variance(row)}${comment(row)}`
		);
	};
	const title = (row) => `<a href="${frappe.utils.get_form_link("Task", row.phase)}">${esc(row.subject || row.phase)}</a>`;
	const block = (row, depth) => {
		if (!passes(row)) {
			return "";
		}
		const tasks = under[row.phase] || [];
		const group = tasks.length > 0;
		const count = group ? ` <span class="sr-small text-muted">${tasks.length === 1 ? __("1 subtask") : __("{0} subtasks", [tasks.length])}</span>` : "";
		const html = `<div class="sr-row ${group ? "sr-group" : ""}" data-task="${esc(row.phase)}" data-row-type="${group ? "group" : "subtask"}">${cells(row, `<div style="padding-left: ${depth * 16}px;">${title(row)}${count}</div>`, group)}</div>`;
		return html + (group && !state.folded.has(row.phase) ? tasks.map((task) => block(task, depth + 1)).join("") : "");
	};
	const card = (row, is_last) => {
		const tasks = under[row.phase] || [];
		const group = tasks.length > 0;
		const all = tasks_of(row);
		const done = all.filter(is_done).length;
		const [label, colour] = done === all.length ? [__("Done"), "green"] : all.some((task) => is_done(task) || has_begun(task)) ? [__("In Progress"), "blue"] : [__("Upcoming"), "gray"];
		const count = group
			? `<div class="sr-small text-muted" style="display: flex; align-items: center; gap: 8px; margin-top: 2px;"><span style="display: inline-block; width: 110px; height: 4px; border-radius: 2px; background: var(--border-color);"><span style="display: block; height: 100%; width: ${(done / all.length) * 100}%; border-radius: 2px; background: var(--green-500, #22c55e);"></span></span>${__("{0} of {1} tasks done", [done, all.length])}</div>`
			: "";
		const name = `<span>${title(row)}</span><span class="indicator-pill ${colour} sr-small" style="margin-left: 6px;">${label}</span>${count}`;
		return (
			`<div style="display: grid; grid-template-columns: 18px minmax(0, 1fr);" data-milestone="${esc(row.phase)}">` +
			`<div style="display: flex; flex-direction: column; align-items: center;"><span style="width: 14px; height: 14px; margin-top: 8px; border-radius: 50%; background: var(--${colour}-500, #3b82f6);"></span>` +
			(is_last ? "" : `<span style="flex: 1; width: 2px; background: var(--${colour}-300, #93c5fd);"></span>`) +
			`</div><div class="sr-card" style="border-left-color: var(--${colour}-500, #3b82f6);">` +
			`<div class="sr-head" data-task="${esc(row.phase)}" data-row-type="milestone">${cells(row, name, group)}</div>` +
			(group && !state.folded.has(row.phase) ? tasks.map((task) => block(task, 0)).join("") : "") +
			`</div></div>`
		);
	};
	const redraw = () => {
		const shown = milestones.filter(passes);
		const with_tasks = milestones.filter((row) => (under[row.phase] || []).length);
		const all_shut = with_tasks.length > 0 && with_tasks.every((row) => state.folded.has(row.phase));
		const pills = [
			["All", __("All")],
			["This Period", __("This Period")],
			["Behind", __("Behind")],
		]
			.map(([value, label]) => `<button class="btn btn-xs ${state.filter === value ? "btn-primary" : "btn-default"}" data-act="filter" data-value="${value}">${label}</button>`)
			.join(" ");
		el.innerHTML =
			`<div class="muhick-progress">${STYLE}` +
			`<div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 10px;"><b>${__("Milestones")}</b><span class="text-muted">· ${milestones.length}</span>${pills}` +
			`<span style="flex: 1;"></span><a href="#" data-act="fold-all">${all_shut ? __("Expand All") : __("Collapse All")}</a></div>` +
			`<div style="overflow-x: auto;"><div style="min-width: 960px;">` +
			`<div class="sr-columns"><span></span><span>${__("ID")}</span><span>${__("Task Name")}</span><span>${__("Start")}</span><span>${__("Finish")}</span><span class="sr-num">${__("Planned %")}</span><span class="sr-num">${__("Last Report %")}</span><span class="sr-num">${__("Actual %")}</span><span class="sr-num">${__("Variance %")}</span><span>${__("Comments / Reason")}</span></div>` +
			shown.map((row, i) => card(row, i === shown.length - 1)).join("") +
			`</div></div></div>`;
	};
	el.onclick = (event) => {
		const target = event.target.closest("[data-act]");
		if (!target) {
			return;
		}
		event.preventDefault();
		if (target.dataset.act === "fold") {
			const { phase } = rows[cint(target.dataset.row)];
			state.folded[state.folded.has(phase) ? "delete" : "add"](phase);
		} else if (target.dataset.act === "fold-all") {
			const with_tasks = milestones.filter((row) => (under[row.phase] || []).length);
			const all_shut = with_tasks.every((row) => state.folded.has(row.phase));
			state.folded = new Set(all_shut ? [] : with_tasks.map((row) => row.phase));
		} else {
			state.filter = target.dataset.value;
		}
		redraw();
	};
	el.onchange = (event) => {
		const { row: place_of_row, field } = event.target.dataset;
		const row = rows[cint(place_of_row)];
		if (!row || !field) {
			return;
		}
		if (field === "remarks") {
			row.remarks = event.target.value;
			frm.dirty();
			return;
		}
		const value = flt(event.target.value);
		if (value < 0 || value > 100) {
			frappe.msgprint(__("Progress must be between 0 and 100."));
			event.target.value = flt(row.actual_percent);
			return;
		}
		row.actual_percent = value;
		add_up(frm);
		frm.dirty();
		// once the cursor has gone where it was going, and back there after the figures are redrawn
		setTimeout(() => {
			const { row: next_row, field: next_field } = el.contains(document.activeElement) ? document.activeElement.dataset : {};
			redraw();
			if (next_field) {
				el.querySelector(`[data-row="${next_row}"][data-field="${next_field}"]`)?.focus();
			}
		});
	};
	redraw();
}
