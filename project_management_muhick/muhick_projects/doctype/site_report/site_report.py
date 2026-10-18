# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Weekly, monthly, progress and completion reports. The system fills in what it already knows
(phase progress against plan, casual labour by trade, materials issued, equipment on site);
the Project Manager adds the narrative, the reasons for being ahead or behind, and photos."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from project_management_muhick.muhick_projects.utils import get_phases, validate_dates
from project_management_muhick.utils import calc


class SiteReport(Document):
	def validate(self):
		validate_dates(self.period_from, self.period_to, _("Period From"), _("Period To"))
		if not self.prepared_by:
			self.prepared_by = frappe.session.user
		weights = {}
		if self.phases:
			weights = dict(
				frappe.get_all(
					"Task",
					filters={"name": ("in", [r.phase for r in self.phases])},
					fields=["name", "task_weight"],
					as_list=True,
				)
			)
		for row in self.phases:
			row.variance_percent = flt(row.actual_percent) - flt(row.planned_percent)
		self.planned_progress = calc.weighted_progress([(weights.get(r.phase), r.planned_percent) for r in self.phases])
		self.overall_progress = calc.weighted_progress([(weights.get(r.phase), r.actual_percent) for r in self.phases])

	@frappe.whitelist()
	def fetch_from_system(self):
		"""Fill the tables and summaries from the project's records for the period."""
		if self.docstatus != 0:
			frappe.throw(_("Only a draft report can be refreshed."))
		if not (self.project and self.period_from and self.period_to):
			frappe.throw(_("Select the project and the period first."))
		self.fetch_phases()
		self.fetch_manpower()
		self.materials_used = self.get_materials_used()
		self.equipment_on_site = self.get_equipment_on_site()
		self.subcontractor_progress = self.get_subcontractor_progress()

	def fetch_phases(self):
		remarks = {r.phase: r.remarks for r in self.phases}
		self.set("phases", [])
		for p in get_phases(self.project):
			self.append(
				"phases",
				{
					"phase": p.name,
					"planned_percent": calc.planned_percent(p.exp_start_date, p.exp_end_date, self.period_to),
					"actual_percent": p.progress,
					"remarks": remarks.get(p.name),
				},
			)

	def fetch_manpower(self):
		rows = frappe.db.sql(
			"""
			select l.trade, count(distinct lower(trim(l.worker_name))) as headcount, sum(l.days_worked) as man_days
			from `tabCasual Sheet Line` l inner join `tabCasual Sheet` s on s.name = l.parent
			where s.project = %(project)s and s.docstatus < 2
				and s.period_from <= %(to)s and s.period_to >= %(from)s
			group by l.trade order by l.trade
			""",
			{"project": self.project, "from": self.period_from, "to": self.period_to},
			as_dict=True,
		)
		self.set("manpower", [])
		for r in rows:
			self.append("manpower", {"trade": r.trade, "headcount": r.headcount, "man_days": r.man_days})

	def get_materials_used(self) -> str:
		rows = frappe.db.sql(
			"""
			select d.item_code, d.stock_uom, sum(d.transfer_qty) as qty
			from `tabStock Entry Detail` d inner join `tabStock Entry` se on se.name = d.parent
			where se.docstatus = 1 and se.purpose = 'Material Issue'
				and ifnull(nullif(d.project, ''), se.project) = %(project)s
				and se.posting_date between %(from)s and %(to)s
			group by d.item_code, d.stock_uom order by sum(d.amount) desc limit 25
			""",
			{"project": self.project, "from": self.period_from, "to": self.period_to},
			as_dict=True,
		)
		return "\n".join(f"{r.item_code}: {flt(r.qty):g} {r.stock_uom or ''}".strip() for r in rows)

	def get_equipment_on_site(self) -> str:
		rows = frappe.get_all(
			"Project Equipment Allocation",
			filters={"project": self.project, "status": ("in", ("Allocated", "Under Repair"))},
			fields=["equipment_name", "quantity", "status", "condition_out"],
			order_by="equipment_name asc",
		)
		return "\n".join(f"{r.equipment_name} x{r.quantity} ({_(r.status)}, {_(r.condition_out)})" for r in rows)

	def get_subcontractor_progress(self) -> str:
		rows = frappe.get_all(
			"Subcontract Agreement",
			filters={"project": self.project, "docstatus": 1, "status": ("in", ("Active", "Completed"))},
			fields=["supplier_name", "title", "contract_amount", "certified_to_date", "status"],
		)
		lines = []
		for r in rows:
			percent = flt(r.certified_to_date) / flt(r.contract_amount) * 100 if flt(r.contract_amount) else 0
			lines.append(f"{r.supplier_name}, {r.title}: {percent:.0f}% certified ({_(r.status)})")
		return "\n".join(lines)
