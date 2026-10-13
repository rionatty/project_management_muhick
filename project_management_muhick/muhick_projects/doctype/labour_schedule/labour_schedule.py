# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Weekly labour schedule: the planned casual labour for a project, approved by the COO and
then the Finance Manager. It is the plan the Casual Sheet is
checked against; it does not itself commit the budget."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, flt

from project_management_muhick.muhick_projects import budget_engine


class LabourSchedule(Document):
	def validate(self):
		self.week_end = add_days(self.week_start, 6)
		self.total_headcount = 0
		self.total_man_days = self.total_amount = 0.0
		for row in self.lines:
			if flt(row.headcount) <= 0 or flt(row.days) <= 0:
				frappe.throw(_("Labour Schedule row {0}: enter the number of workers and days.").format(row.idx))
			row.amount = flt(row.headcount) * flt(row.days) * flt(row.daily_rate)
			self.total_headcount += int(row.headcount)
			self.total_man_days += flt(row.headcount) * flt(row.days)
			self.total_amount += row.amount
		self.budget_status, self.budget_remarks = budget_engine.evaluate(self.project, {self.cost_code: self.total_amount})
