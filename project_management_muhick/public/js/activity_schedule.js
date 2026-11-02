// Copyright (c) 2026, CyveTech and contributors
// For license information, please see license.txt

// The activity schedule on the plan and the project, as the business writes it and organised milestone by milestone:
// a milestone is a card with its group tasks and subtasks under it, each with its ID, days, start, finish, predecessors
// and a bar; once the plan is approved each shows where it stands. It comes with those two forms (doctype_js in
// hooks.py), so it needs nothing but the form. The rows are worked out by calc.work_out_schedule; outline here reads
// them the same way.
frappe.provide("muhick");

muhick.schedule = (() => {
	const WEEK = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
	const DAY = 86400000;
	const COLUMNS = "display: grid; grid-template-columns: 22px 30px minmax(260px, 1fr) 96px 40px 84px 84px 84px minmax(200px, 1fr) 44px; gap: 6px; align-items: center;";
	const STYLE = `<style>
		.muhick-schedule a { text-decoration: none; }
		.muhick-schedule .ms-columns { ${COLUMNS} margin-left: 38px; padding-bottom: 4px; font-size: var(--text-xs, 11px); color: var(--text-muted); }
		.muhick-schedule .ms-row { ${COLUMNS} padding: 5px 0; border-top: 1px solid var(--border-color); }
		.muhick-schedule .ms-heading { ${COLUMNS} margin-left: 38px; padding: 4px 0; font-weight: 600; }
		.muhick-schedule .ms-head { ${COLUMNS} padding: 6px 0 2px; font-weight: 600; font-size: var(--text-md, 13px); }
		.muhick-schedule .ms-group { font-weight: 600; background: var(--subtle-fg, transparent); }
		.muhick-schedule .ms-small { font-size: var(--text-xs, 11px); font-weight: normal; }
		.muhick-schedule .ms-actions { text-align: right; font-weight: normal; opacity: 0.45; }
		.muhick-schedule .ms-row:hover .ms-actions, .muhick-schedule .ms-head:hover .ms-actions { opacity: 1; }
		.muhick-schedule .ms-bar { position: relative; height: 14px; }
		.muhick-schedule .ms-card { border-left: 2px solid; padding-left: 10px; margin-bottom: 10px; }
		.muhick-schedule .ms-add { padding: 4px 0; font-size: var(--text-xs, 11px); }
	</style>`;
	const esc = (text) => frappe.utils.escape_html(text === null || text === undefined ? "" : String(text));
	const utc = (value) => {
		const [year, month, day] = String(value).slice(0, 10).split("-").map(Number);
		return Date.UTC(year, month - 1, day);
	};
	const two = (number) => String(number).padStart(2, "0");
	const shown_date = (value) => {
		if (!value) {
			return "";
		}
		const day = new Date(utc(value));
		return `${WEEK[day.getUTCDay()]} ${two(day.getUTCDate())}/${two(day.getUTCMonth() + 1)}/${String(day.getUTCFullYear()).slice(2)}`;
	};

	function outline(rows) {
		const levels = rows.map((row) => cint(row.outline_level));
		const parents = [];
		const open = [];
		levels.forEach((level, i) => {
			while (open.length && levels[open[open.length - 1]] >= level) {
				open.pop();
			}
			parents.push(open.length ? open[open.length - 1] : null);
			open.push(i);
		});
		const children = rows.map(() => []);
		const roots = [];
		parents.forEach((parent, i) => (parent === null ? roots : children[parent]).push(i));
		let top = roots;
		while (top.length === 1 && children[top[0]].some((child) => children[child].length)) {
			top = children[top[0]];
		}
		return { levels, parents, children, milestones: new Set(top) };
	}

	function request_signoff(row, options) {
		frappe.prompt(
			[
				{ fieldname: "email", fieldtype: "Data", options: "Email", label: __("Send To"), reqd: 1, default: options.client_email },
				{ fieldname: "message", fieldtype: "Small Text", label: __("Message"), reqd: 1, default: __("Please confirm that {0} is complete.", [row.subject]) },
			],
			(values) =>
				frappe
					.xcall("project_management_muhick.muhick_projects.doctype.project_activity_plan.project_activity_plan.request_signoff", { task: row.task, ...values })
					.then(options.on_change),
			__("Request Client Sign-off"),
			__("Send")
		);
	}

	function record_signoff(row, options) {
		frappe.prompt(
			{ fieldname: "signed_on", fieldtype: "Date", label: __("Signed Off On"), reqd: 1, default: frappe.datetime.get_today() },
			(values) =>
				frappe
					.xcall("project_management_muhick.muhick_projects.doctype.project_activity_plan.project_activity_plan.record_signoff", { task: row.task, signed_on: values.signed_on })
					.then(options.on_change),
			__("Record Client Sign-off"),
			__("Record")
		);
	}

	function render($wrapper, unsorted, options = {}) {
		const el = $wrapper[0];
		const rows = [...unsorted].sort((a, b) => a.idx - b.idx);
		const state = (el.__schedule = el.__schedule || { folded: new Set(), filter: "All" });
		const { levels, parents, children, milestones } = outline(rows);
		const can_edit = Boolean(options.on_add);
		const live = options.live;
		const groups_of_top = [...milestones].filter((i) => children[i].length);
		const all_shut = groups_of_top.length > 0 && groups_of_top.every((i) => state.folded.has(rows[i].name));
		el.onclick = (event) => {
			const target = event.target.closest("[data-act]");
			if (!target) {
				return;
			}
			event.preventDefault();
			const act = target.dataset.act;
			const row = rows[cint(target.dataset.row)];
			if (act === "edit") {
				options.on_edit(row);
			} else if (act === "add") {
				options.on_add(row);
			} else if (act === "add-milestone") {
				options.on_add(null);
			} else if (act === "request") {
				request_signoff(row, options);
			} else if (act === "record") {
				record_signoff(row, options);
			} else {
				if (act === "fold") {
					state.folded[state.folded.has(row.name) ? "delete" : "add"](row.name);
				} else if (act === "fold-all") {
					state.folded = new Set(all_shut ? [] : groups_of_top.map((i) => rows[i].name));
				} else if (act === "filter") {
					state.filter = target.dataset.value;
				}
				render($wrapper, unsorted, options);
			}
		};
		const problem = options.error ? `<div class="text-danger" style="margin-bottom: 8px">${esc(options.error)}</div>` : "";
		const add_milestone = can_edit ? `<button class="btn btn-xs btn-default" data-act="add-milestone">+ ${__("Add Milestone")}</button>` : "";
		if (!rows.length) {
			el.innerHTML = `<div class="muhick-schedule">${problem}${add_milestone}</div>`;
			return;
		}

		const task_of = (row) => (live && live[row.task]) || {};
		const is_done = (row) => task_of(row).status === "Completed" || flt(task_of(row).progress) >= 100;
		const has_begun = (row) => task_of(row).status === "Working" || flt(task_of(row).progress) > 0;
		const subtasks_of = (i) => (children[i].length ? children[i].flatMap(subtasks_of) : [i]);
		const passes = (i) => (children[i].length ? children[i].some(passes) : state.filter === "All" || (rows[i].responsibility || "Muhick") === state.filter);
		const dated = rows.filter((row) => row.start_date && row.end_date);
		const first = dated.length ? Math.min(...dated.map((row) => utc(row.start_date))) : 0;
		const last = dated.length ? Math.max(...dated.map((row) => utc(row.end_date))) : 0;
		const span = Math.max(last - first + DAY, DAY);
		const month = (30 * DAY * 100) / span;
		const month_lines = `background-image: repeating-linear-gradient(90deg, var(--border-color) 0, var(--border-color) 1px, transparent 1px, transparent ${month}%);`;

		const standing_of = (i) => {
			const under = subtasks_of(i).map((at) => rows[at]);
			if (under.every(is_done)) {
				return [__("Done"), "green"];
			}
			return under.some((row) => is_done(row) || has_begun(row)) ? [__("In Progress"), "blue"] : [__("Upcoming"), "gray"];
		};
		const bar = (row, i) => {
			if (!row.start_date || !row.end_date) {
				return "";
			}
			const left = ((utc(row.start_date) - first) / span) * 100;
			const width = Math.max(((utc(row.end_date) - utc(row.start_date) + DAY) / span) * 100, 0.8);
			if (children[i].length) {
				return `<div style="position: absolute; left: ${left}%; width: ${width}%; top: 5px; height: 4px; background: var(--text-color);"></div>`;
			}
			const done = is_done(row) ? 100 : flt(task_of(row).progress);
			return (
				`<div style="position: absolute; left: ${left}%; width: ${width}%; top: 2px; height: 10px; border-radius: 2px; background: var(--blue-300, #93c5fd);">` +
				(done ? `<div style="height: 100%; width: ${done}%; border-radius: 2px; background: var(--green-500, #22c55e);"></div>` : "") +
				`</div>`
			);
		};
		// a row's cells, as the business's schedule has them; the first says what it is: a fold for a group, a circle for a subtask
		const cells = (row, i, name, is_heading) => {
			const group = children[i].length > 0;
			const fold = `<a data-act="fold" data-row="${i}" href="#">${state.folded.has(row.name) ? "&#9656;" : "&#9662;"}</a>`;
			const circle = `<span style="color: var(--${is_done(row) ? "green" : has_begun(row) ? "blue" : "gray"}-500, inherit);">${is_done(row) ? "&#10004;" : has_begun(row) ? "&#9680;" : "&#9675;"}</span>`;
			const mark = is_heading ? "<span></span>" : group ? fold : circle;
			const status = live && !group && (is_done(row) || has_begun(row)) ? ` · ${is_done(row) ? __("Done") : __("In Progress")}` : "";
			const who = group ? "" : `<span class="ms-small text-muted">${esc(row.responsibility || "Muhick")}${status}</span>`;
			const actions = can_edit
				? `<a data-act="edit" data-row="${i}" href="#" title="${__("Edit")}">&#9998;</a> <a data-act="add" data-row="${i}" href="#" title="${__("Add a subtask under this row")}">+</a>`
				: "";
			return (
				`${mark}<span class="text-muted ms-small">${esc(row.row_id)}</span><div>${name}</div>${who ? `<span>${who}</span>` : "<span></span>"}` +
				`<span style="text-align: right;">${cint(row.duration) || ""}</span><span class="ms-small">${shown_date(row.start_date)}</span><span class="ms-small">${shown_date(row.end_date)}</span>` +
				`<span class="ms-small text-muted" style="overflow-wrap: anywhere;">${esc(row.predecessors)}</span><div class="ms-bar" style="${month_lines}">${bar(row, i)}</div><span class="ms-actions">${actions}</span>`
			);
		};
		const title = (row) => (live && row.task ? `<a href="${frappe.utils.get_form_link("Task", row.task)}">${esc(row.subject)}</a>` : esc(row.subject));

		// a group task or subtask, and what is under it, stepped in by its depth below the milestone
		const block = (i, depth) => {
			if (!passes(i)) {
				return "";
			}
			const row = rows[i];
			const group = children[i].length > 0;
			const struck = live && !group && is_done(row) ? "text-decoration: line-through;" : "";
			const count = group ? ` <span class="ms-small text-muted">${children[i].length === 1 ? __("1 subtask") : __("{0} subtasks", [children[i].length])}</span>` : "";
			const name = `<div style="padding-left: ${depth * 16}px; ${struck}">${title(row)}${count}</div>`;
			let html = `<div class="ms-row ${group ? "ms-group" : ""}" data-schedule-row="${esc(row.row_id || i + 1)}" data-row-type="${group ? "group" : "subtask"}">${cells(row, i, name)}</div>`;
			if (group && !state.folded.has(row.name)) {
				html += children[i].map((child) => block(child, depth + 1)).join("");
				if (can_edit) {
					html += add_subtask(i, depth + 1);
				}
			}
			return html;
		};
		const add_subtask = (i, depth) => `<div class="ms-add" style="margin-left: ${58 + depth * 16}px;"><a data-act="add" data-row="${i}" href="#">+ ${__("Add Subtask")}</a></div>`;

		const card = (i, is_last) => {
			if (!passes(i)) {
				return "";
			}
			const row = rows[i];
			const under = subtasks_of(i);
			const group = children[i].length > 0;
			const [label, colour] = live ? standing_of(i) : ["", "blue"];
			const badge = live ? `<span class="indicator-pill ${colour} ms-small" style="margin-left: 6px;">${label}</span>` : "";
			const done = live ? under.filter((at) => is_done(rows[at])).length : 0;
			const progress = group
				? `<div class="ms-small text-muted" style="display: flex; align-items: center; gap: 8px; margin-top: 2px;">` +
				  (live
						? `<span style="display: inline-block; width: 110px; height: 4px; border-radius: 2px; background: var(--border-color);"><span style="display: block; height: 100%; width: ${(done / under.length) * 100}%; border-radius: 2px; background: var(--green-500, #22c55e);"></span></span>${__("{0} of {1} tasks done", [done, under.length])}`
						: __("{0} tasks", [under.length])) +
				  `</div>`
				: "";
			const task = task_of(row);
			let signoff = "";
			if (live && row.task) {
				if (task.muhick_client_signed_off_on) {
					signoff = `<span class="text-muted ms-small">${__("Client signed off {0}", [shown_date(task.muhick_client_signed_off_on)])}</span>`;
				} else if (options.can_write) {
					signoff =
						(task.muhick_signoff_requested_on
							? `<span class="text-muted ms-small">${__("Sign-off requested {0}", [shown_date(task.muhick_signoff_requested_on)])}</span> `
							: `<button class="btn btn-xs btn-default" data-act="request" data-row="${i}">${__("Request client sign-off")}</button> `) +
						`<a class="ms-small" data-act="record" data-row="${i}" href="#">${__("Record sign-off")}</a>`;
				}
			}
			const name = `<span>${title(row)}</span>${badge}${progress}`;
			const shut = state.folded.has(row.name);
			return (
				`<div style="display: grid; grid-template-columns: 18px minmax(0, 1fr); gap: 8px;" data-milestone="${esc(row.row_id)}">` +
				`<div style="display: flex; flex-direction: column; align-items: center;"><span style="width: 14px; height: 14px; margin-top: 8px; border-radius: 50%; background: var(--${colour}-500, #3b82f6);"></span>` +
				(is_last ? "" : `<span style="flex: 1; width: 2px; background: var(--${colour}-300, #93c5fd);"></span>`) +
				`</div><div class="ms-card" style="border-left-color: var(--${colour}-500, #3b82f6);">` +
				`<div class="ms-head" data-schedule-row="${esc(row.row_id || i + 1)}" data-row-type="milestone">${cells(row, i, name)}</div>` +
				(group && !shut ? children[i].map((child) => block(child, 0)).join("") + (can_edit ? add_subtask(i, 0) : "") : "") +
				(signoff ? `<div style="margin-top: 6px;">${signoff}</div>` : "") +
				`</div></div>`
			);
		};

		const shown_milestones = [...milestones].filter(passes);
		const in_a_milestone = (i) => {
			for (let at = i; at !== null; at = parents[at]) {
				if (milestones.has(at)) {
					return true;
				}
			}
			return false;
		};
		const body = rows
			.map((row, i) => {
				if (milestones.has(i)) {
					return card(i, i === shown_milestones[shown_milestones.length - 1]);
				}
				// a row above the milestones only wraps them
				return in_a_milestone(i) ? "" : `<div class="ms-heading" data-schedule-row="${esc(row.row_id || i + 1)}" data-row-type="heading">${cells(row, i, esc(row.subject), true)}</div>`;
			})
			.join("");
		const ticks = [];
		for (let n = 0; n * 30 * DAY < span; n += 1) {
			ticks.push(`<span style="position: absolute; left: ${n * month}%;">M${n + 1}</span>`);
		}
		const pills = ["All", "Muhick", "Client", "Subcontractor", "Joint"]
			.map((value) => `<button class="btn btn-xs ${state.filter === value ? "btn-primary" : "btn-default"}" data-act="filter" data-value="${value}">${__(value)}</button>`)
			.join(" ");
		el.innerHTML =
			`<div class="muhick-schedule">${STYLE}${problem}` +
			`<div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 8px;">` +
			`<b>${__("Milestones")}</b><span class="text-muted">· ${milestones.size}</span><span class="text-muted ms-small">${shown_date(dated.length ? new Date(first).toISOString() : "")} – ${shown_date(dated.length ? new Date(last).toISOString() : "")}</span>` +
			`<span style="flex: 1;"></span><a href="#" data-act="fold-all">${all_shut ? __("Expand All") : __("Collapse All")}</a>${add_milestone}</div>` +
			`<div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 10px;"><span class="text-muted ms-small">${__("Responsibility")}</span>${pills}</div>` +
			`<div style="overflow-x: auto;"><div style="min-width: 1040px;">` +
			`<div class="ms-columns"><span></span><span>${__("ID")}</span><span>${__("Task Name")}</span><span>${__("Responsibility")}</span><span style="text-align: right;">${__("Days")}</span><span>${__("Start")}</span><span>${__("Finish")}</span><span>${__("Predecessors")}</span>` +
			`<div style="position: relative; height: 14px;">${ticks.join("")}</div><span></span></div>` +
			body +
			`</div></div></div>`;
	}

	return {
		render,
		// the names of the milestones of some rows, in their order
		milestones(rows) {
			const sorted = [...rows].sort((a, b) => a.idx - b.idx);
			return [...outline(sorted).milestones].map((i) => sorted[i].phase_name || sorted[i].subject);
		},
		// the ID of the row the milestones sit under, 0 for none: where a new milestone goes
		milestone_group(rows) {
			const sorted = [...rows].sort((a, b) => a.idx - b.idx);
			const { parents, milestones } = outline(sorted);
			const first = [...milestones][0];
			return first === undefined || parents[first] === null ? 0 : cint(sorted[parents[first]].row_id);
		},
		// the rows under a row, however deep
		under(rows, row) {
			const sorted = [...rows].sort((a, b) => a.idx - b.idx);
			const { children } = outline(sorted);
			const all = (i) => children[i].flatMap((child) => [sorted[child], ...all(child)]);
			return all(sorted.indexOf(row));
		},
	};
})();
