# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""A plan's activities become its schedule: a row for each milestone with its activities under it, numbered in that
order, the activity each depended on as its predecessor."""

import frappe
from frappe.utils import getdate, now

from project_management_muhick.utils import calc

ROW = "Project Activity Plan Activity"


def execute():
	with_dependency = frappe.db.has_column(ROW, "depends_on_subject")
	for plan in frappe.get_all("Project Activity Plan", fields=["name", "docstatus"]):
		if frappe.db.exists(ROW, {"parent": plan.name, "row_id": (">", 0)}):
			continue
		phases = frappe.get_all(
			"Project Activity Plan Phase", filters={"parent": plan.name}, fields=["phase_name", "phase", "planned_start", "planned_end"], order_by="idx asc"
		)
		activities = frappe.db.sql(
			f"""select name, subject, phase_name, start_date, end_date, {"depends_on_subject" if with_dependency else "'' as depends_on_subject"}
			from `tab{ROW}` where parent = %s order by idx asc""",
			(plan.name,),
			as_dict=True,
		)
		numbers = {}
		rows = []
		for phase in phases:
			under = [a for a in activities if a.phase_name == phase.phase_name]
			rows.append(("milestone", phase, bool(under)))
			rows += [("activity", a, False) for a in under]
		for number, (kind, row, _under) in enumerate(rows, 1):
			if kind == "activity":
				numbers[row.subject] = number
		for number, (kind, row, under) in enumerate(rows, 1):
			if kind == "milestone":
				doc = frappe.new_doc(ROW)
				doc.update(
					{
						"parent": plan.name, "parenttype": "Project Activity Plan", "parentfield": "activities", "docstatus": plan.docstatus,
						"idx": number, "row_id": number, "outline_level": 0, "subject": row.phase_name, "phase_name": row.phase_name,
						"start_date": row.planned_start, "end_date": row.planned_end, "task": row.phase, "is_summary": 1 if under else 0,
						"duration": calc.workdays_between(getdate(row.planned_start), getdate(row.planned_end)), "responsibility": "Muhick",
						"owner": "Administrator", "modified_by": "Administrator", "creation": now(), "modified": now(),
					}
				)
				doc.db_insert()
			else:
				frappe.db.set_value(
					ROW,
					row.name,
					{
						"idx": number, "row_id": number, "outline_level": 1, "responsibility": "Muhick",
						"duration": calc.workdays_between(getdate(row.start_date), getdate(row.end_date)),
						"predecessors": str(numbers[row.depends_on_subject]) if row.depends_on_subject in numbers else None,
					},
					update_modified=False,
				)
