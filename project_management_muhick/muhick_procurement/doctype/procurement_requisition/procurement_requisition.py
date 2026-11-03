# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Procurement Requisition: raised once the suppliers are selected, from one approved supplier quotation or
several. Each line keeps its source and its currency and, where there is one, the request it comes from. The
payment and delivery terms are the requisition's. Approved COO -> Finance Manager -> General Manager, as far as
the approval limits ask for its value and risk, and only then is one Purchase Order raised per supplier. A line's
rate is in its quotation's currency; the totals, the budget and the limits read it in the company's.

Prices are compared with the project budget line by line and any variance is flagged. Prices or
quantities may still be corrected while it is under approval: the change needs a written summary,
is logged, and Finance is told; the approval does not start again.
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, fmt_money, formatdate, getdate, now_datetime, nowdate

from project_management_muhick.muhick_projects import budget_engine
from project_management_muhick.muhick_projects.utils import draft_status, leaving_draft
from project_management_muhick.overrides import supplier as supplier_api
from project_management_muhick.overrides.buying import OVER_BUDGET, _approved_overrun
from project_management_muhick.utils import calc
from project_management_muhick.utils.approval import get_route
from project_management_muhick.utils.common import COO, FINANCE_ROLES, administration_purchase, get_settings, notify_roles

BEING_PREPARED = (None, "", "Draft", "Rejected")
RANK = {"Not Applicable": 0, "Within Budget": 1, "Exceeds Budget": 2, "Not Budgeted": 3}
RISKS = ("Low", "Medium", "High")


class ProcurementRequisition(Document):
	def validate(self):
		quotations = self.set_lines()
		self.administration_purchase = administration_purchase(self.items)
		self.set_item_values()
		self.set_budget_status()
		self.set_route()
		self.status = draft_status(self)
		self.check_rejection()
		self.log_change()
		self.warn_about_suppliers(quotations)

	def set_lines(self) -> dict:
		"""Every line stands on an approved quotation, which says who supplies it and at what exchange rate. A
		quotation's line is taken up once, here or on another open requisition."""
		if not self.items:
			frappe.throw(_("Get the items from at least one approved supplier quotation."))
		quotations = {
			q.name: q
			for q in frappe.get_all(
				"Supplier Quotation",
				filters={"name": ("in", list({row.supplier_quotation for row in self.items if row.supplier_quotation}))},
				fields=["name", "docstatus", "company", "supplier", "supplier_name", "currency", "conversion_rate", "transaction_date", "valid_till"],
			)
		}
		quotation_rows = [row.supplier_quotation_item for row in self.items if row.supplier_quotation_item]
		taken = _on_open_requisitions(quotation_rows, self.name)
		seen = set()
		for row in self.items:
			quotation = quotations.get(row.supplier_quotation)
			if not quotation or quotation.docstatus != 1:
				frappe.throw(
					_("Row {0}: {1} needs an approved supplier quotation. The supplier selection must be approved first.").format(
						row.idx, row.item_code
					)
				)
			if quotation.company != self.company:
				frappe.throw(_("Row {0}: Supplier Quotation {1} belongs to {2}.").format(row.idx, quotation.name, quotation.company))
			if row.supplier_quotation_item in taken:
				frappe.throw(
					_("Row {0}: {1} from {2} is already on requisition {3}.").format(
						row.idx, row.item_code, quotation.name, taken[row.supplier_quotation_item]
					)
				)
			if row.supplier_quotation_item and row.supplier_quotation_item in seen:
				frappe.throw(_("Row {0}: {1} from {2} is listed twice.").format(row.idx, row.item_code, quotation.name))
			seen.add(row.supplier_quotation_item)
			row.supplier, row.supplier_name = quotation.supplier, quotation.supplier_name
			row.currency, row.conversion_rate = quotation.currency, quotation.conversion_rate
		self.suppliers = ", ".join(sorted({row.supplier_name or row.supplier for row in self.items}))
		self.quotations_compared = _quotations_compared(quotation_rows, quotations)
		return quotations

	def set_item_values(self):
		self.total_amount = self.total_budget_amount = self.total_price_variance = 0
		requested = {
			row.name: row
			for row in frappe.get_all(
				"Material Request Item",
				filters={"name": ("in", [row.material_request_item for row in self.items if row.material_request_item])},
				fields=["name", "stock_qty", "muhick_cost_code"],
			)
		}
		for row in self.items:
			exchange_rate = flt(row.conversion_rate) or 1
			row.amount = flt(row.qty) * flt(row.rate)
			row.base_amount = row.amount * exchange_rate
			row.stock_qty = budget_engine.in_stock_unit(row.item_code, row.qty, row.uom)
			if not row.project:
				row.project = self.project
			source = requested.get(row.material_request_item)
			row.requested_qty = source.stock_qty if source else 0
			if not row.cost_code and source:
				row.cost_code = source.muhick_cost_code
			if not row.cost_code and row.project:
				row.cost_code = budget_engine.get_budget_cost_code(row.project, row.item_code)
			row.budget_rate = budget_engine.get_budget_rate(row.project, row.item_code) if row.project else 0
			row.price_variance = (flt(row.rate) * exchange_rate - flt(row.budget_rate)) * flt(row.qty) if flt(row.budget_rate) else 0
			self.total_amount += row.base_amount
			self.total_budget_amount += flt(row.budget_rate) * flt(row.qty)
			self.total_price_variance += row.price_variance
		projects = {row.project or None for row in self.items}
		self.project = projects.pop() if len(projects) == 1 else None
		for project in {row.project for row in self.items if row.project}:
			budgeted = budget_engine.budgeted_quantities(project, {row.item_code for row in self.items if row.project == project})[0]
			for row in self.items:
				if row.project == project:
					row.budget_qty = budgeted.get(row.item_code, 0)

	def amounts_by_project(self) -> dict:
		amounts = defaultdict(lambda: defaultdict(float))
		for row in self.items:
			if row.project:
				amounts[row.project][row.cost_code or ""] += flt(row.base_amount)
		return amounts

	def new_quantities(self, project) -> dict:
		"""What the requisition asks for on the project beyond the approved requests it comes from."""
		return budget_engine.beyond_requests(
			[
				(row.item_code, budget_engine.in_stock_unit(row.item_code, row.qty, row.uom), row.material_request_item)
				for row in self.items
				if row.item_code and row.project == project
			]
		)

	def set_budget_status(self):
		"""Worst result across the projects on the requisition (normally one)."""
		self.budget_status, remarks = "Not Applicable", []
		# an over-budget Material Request that was approved covers the same value here
		allowance = _approved_overrun(self)
		for project, amounts in self.amounts_by_project().items():
			status, note = budget_engine.evaluate(project, amounts, allowance=allowance.get(project))
			status, note = budget_engine.with_quantities(project, status, note, self.new_quantities(project))
			if RANK[status] > RANK[self.budget_status]:
				self.budget_status = status
			if note:
				remarks.append(f"{project}: {note}")
		self.budget_remarks = "; ".join(remarks)

	def set_route(self):
		"""Who approves follows the value and the risk. What is over budget takes the full route."""
		settings = get_settings()
		reasons = [
			reason
			for applies, reason in (
				(settings.high_risk_single_quotation and cint(self.quotations_compared) < 2, _("single quotation")),
				(settings.high_risk_advance_payment and self.payment_terms_type == "Advance", _("advance payment")),
				(settings.high_risk_international and self.procurement_type == "International", _("international procurement")),
			)
			if applies
		]
		self.risk_reasons = ", ".join(reasons)
		self.risk_class = "High" if reasons else (self.risk_class or "Medium")
		# under approval it can go up, not down: that would shorten the route it is on
		before = self.get_doc_before_save()
		if before and before.get("workflow_state") not in BEING_PREPARED and RISKS.index(self.risk_class) < RISKS.index(before.risk_class or "Low"):
			self.risk_class = before.risk_class
		over_budget = self.budget_status in OVER_BUDGET
		self.approval_route = calc.FULL_ROUTE if over_budget else get_route(self.doctype, self.total_amount, self.risk_class)

	def check_rejection(self):
		"""An approver says why it goes back. Once it is sent again the reason has served."""
		before = self.get_doc_before_save()
		was = before.get("workflow_state") if before else None
		if self.workflow_state == "Rejected":
			if was != "Rejected" and not (self.rejection_reason or "").strip():
				frappe.throw(_("Give the reason for rejecting this requisition in Reason for Rejection."))
		elif was == "Rejected":
			self.rejection_reason = None

	def log_change(self):
		"""A change made while the requisition is under approval is logged, not restarted."""
		before = self.get_doc_before_save()
		leaving = bool(before) and before.get("workflow_state") in BEING_PREPARED and self.workflow_state not in BEING_PREPARED
		# prices above budget are brought to the head of department as soon as it goes for approval
		self.flags.variance_alert = leaving and flt(self.total_price_variance) > 0.5
		if not before or before.get("workflow_state") in BEING_PREPARED:
			return
		was = [(r.item_code, flt(r.qty), flt(r.rate)) for r in before.items]
		now = [(r.item_code, flt(r.qty), flt(r.rate)) for r in self.items]
		if was == now:
			return
		summary = (self.amendment_summary or "").strip()
		if not summary:
			frappe.throw(_("Prices or quantities were changed. Summarise what changed and why before saving."))
		self.append(
			"amendments",
			{
				"changed_on": now_datetime(),
				"changed_by": frappe.session.user,
				"summary": summary,
				"total_before": before.total_amount,
				"total_after": self.total_amount,
			},
		)
		self.amendment_summary = None
		self.flags.change_summary = summary

	def warn_about_suppliers(self, quotations):
		"""What an order to these suppliers would meet, said now: onboarding not finished, or a quotation past its date."""
		enforce = leaving_draft(self)
		for supplier in sorted({row.supplier for row in self.items}):
			supplier_api.check_purchase_order(frappe._dict(supplier=supplier), enforce)
		for quotation in quotations.values():
			if quotation.valid_till and getdate(quotation.valid_till) < getdate(self.requisition_date):
				frappe.msgprint(
					_("Supplier Quotation {0} ran out on {1}.").format(quotation.name, formatdate(quotation.valid_till)),
					indicator="orange",
					alert=True,
				)

	def on_update(self):
		if self.flags.change_summary:
			notify_roles(
				FINANCE_ROLES,
				_("{0} was changed while under approval: {1}").format(self.name, self.flags.change_summary),
				doc=self,
			)
		if self.flags.variance_alert:
			notify_roles(
				COO,
				_("{0}: sourced prices are {1} above the project budget.").format(
					self.name, frappe.format_value(self.total_price_variance, "Currency")
				),
				doc=self,
			)

	def before_submit(self):
		for project, amounts in self.amounts_by_project().items():
			status, note = budget_engine.evaluate(project, amounts, allowance=_approved_overrun(self).get(project))
			status, note = budget_engine.with_quantities(project, status, note, self.new_quantities(project))
			budget_engine.enforce(self, "budget_action_on_purchase_order", status, f"{project}: {note}")
		self.status = "Approved"

	def on_cancel(self):
		orders = {row.purchase_order for row in self.items if row.purchase_order}
		standing = sorted(order for order in orders if frappe.db.get_value("Purchase Order", order, "docstatus") != 2)
		if standing:
			frappe.throw(_("Purchase Order {0} was raised from this requisition. Cancel it first.").format(", ".join(standing)))
		self.db_set("status", "Cancelled")


def _on_open_requisitions(quotation_rows, requisition=None) -> dict:
	"""{supplier quotation row: the open requisition it is on}. A rejected requisition holds nothing; when it is sent
	again its own save finds what has been taken since."""
	if not quotation_rows:
		return {}
	return dict(
		frappe.db.sql(
			"""
			select line.supplier_quotation_item, req.name
			from `tabProcurement Requisition Item` line
			inner join `tabProcurement Requisition` req on req.name = line.parent
			where line.supplier_quotation_item in %(rows)s and req.docstatus < 2 and req.name != %(requisition)s
				and ifnull(req.workflow_state, '') != 'Rejected'
			""",
			{"rows": tuple(quotation_rows), "requisition": requisition or ""},
		)
	)


def _quotations_compared(quotation_rows, quotations) -> int:
	"""How many quotations were weighed for a line: those for its request or enquiry or, with neither, those for its
	item that were open at the same time as its own. The thinnest comparison stands for the requisition."""
	counts = {}
	for row in frappe.get_all(
		"Supplier Quotation Item",
		filters={"name": ("in", quotation_rows)},
		fields=["parent", "item_code", "material_request", "request_for_quotation"],
	):
		own = quotations.get(row.parent)
		if not own:
			continue
		if row.material_request:
			rule, values = "sqi.material_request = %(value)s", {"value": row.material_request}
		elif row.request_for_quotation:
			rule, values = "sqi.request_for_quotation = %(value)s", {"value": row.request_for_quotation}
		else:
			rule = """sqi.item_code = %(value)s and sq.company = %(company)s and sq.transaction_date <= %(till)s
				and ifnull(sq.valid_till, sq.transaction_date) >= %(since)s"""
			values = {
				"value": row.item_code,
				"company": own.company,
				"since": own.transaction_date,
				"till": own.valid_till or own.transaction_date,
			}
		key = (rule, *values.values())
		if key not in counts:
			counts[key] = frappe.db.sql(
				f"""
				select count(distinct sqi.parent) from `tabSupplier Quotation Item` sqi
				inner join `tabSupplier Quotation` sq on sq.name = sqi.parent
				where sq.docstatus < 2 and {rule}
				""",
				values,
			)[0][0]
	return min(counts.values(), default=0)


def _is_abroad(quotation, countries, home_country, home_currency) -> bool:
	"""By the supplier's country where it is known: a local supplier may well quote in dollars."""
	country = countries.get(quotation.supplier)
	return country != home_country if country else quotation.currency != home_currency


def _quotation_lines(names, requisition=None) -> tuple[list, dict]:
	"""The lines of approved quotations not yet on an open requisition, and what they say of the requisition's header.
	The request behind a line fills in what it knows, where there is one."""
	quotations = []
	for name in names:
		quotation = frappe.get_doc("Supplier Quotation", name)
		quotation.check_permission("read")
		if quotation.docstatus != 1:
			frappe.throw(
				_("Supplier Quotation {0} has not been approved. The supplier selection must be approved before the requisition is raised.").format(name)
			)
		quotations.append(quotation)
	if not quotations:
		frappe.throw(_("Select at least one approved supplier quotation."))
	company = quotations[0].company
	if any(q.company != company for q in quotations):
		frappe.throw(_("These supplier quotations belong to different companies."))
	taken = _on_open_requisitions([item.name for q in quotations for item in q.items], requisition)
	requested = {
		row.name: row
		for row in frappe.get_all(
			"Material Request Item",
			filters={"name": ("in", [item.material_request_item for q in quotations for item in q.items if item.material_request_item])},
			fields=["name", "project", "warehouse", "schedule_date", "muhick_cost_code"],
		)
	}
	lines = []
	for quotation in quotations:
		for item in quotation.items:
			if item.name in taken:
				continue
			source = requested.get(item.material_request_item) or frappe._dict()
			lines.append(
				{
					"item_code": item.item_code,
					"item_name": item.item_name,
					"description": item.description,
					"supplier": quotation.supplier,
					"supplier_name": quotation.supplier_name,
					"supplier_quotation": quotation.name,
					"supplier_quotation_item": item.name,
					"currency": quotation.currency,
					"conversion_rate": quotation.conversion_rate,
					"qty": item.qty,
					"uom": item.uom,
					"rate": item.rate,
					"amount": flt(item.qty) * flt(item.rate),
					"project": source.project or item.project or quotation.project,
					"warehouse": item.warehouse or source.warehouse,
					"schedule_date": item.expected_delivery_date or source.schedule_date,
					"cost_code": source.muhick_cost_code,
					"material_request": item.material_request,
					"material_request_item": item.material_request_item,
				}
			)
	if not lines:
		frappe.throw(_("Every line of these quotations is already on a requisition: {0}.").format(", ".join(sorted(set(taken.values())))))
	home_currency, home_country = frappe.get_cached_value("Company", company, ["default_currency", "country"])
	countries = {
		s.name: s.country for s in frappe.get_all("Supplier", filters={"name": ("in", [q.supplier for q in quotations])}, fields=["name", "country"])
	}
	projects = {line["project"] or None for line in lines}
	warehouses = {line["warehouse"] for line in lines if line["warehouse"]}
	lead_time = max((cint(item.lead_time_days) for q in quotations for item in q.items), default=0)
	return lines, {
		"company": company,
		"project": projects.pop() if len(projects) == 1 else None,
		"procurement_type": "International" if any(_is_abroad(q, countries, home_country, home_currency) for q in quotations) else "Local",
		"delivery_location": warehouses.pop() if len(warehouses) == 1 else None,
		"delivery_period": _("{0} days").format(lead_time) if lead_time else None,
	}


@frappe.whitelist()
def make_from_supplier_quotation(source_name: str):
	"""Start a requisition from an approved quotation, or from several picked on the list."""
	names = frappe.parse_json(source_name) if source_name.startswith("[") else [source_name]
	lines, values = _quotation_lines(names)
	doc = frappe.new_doc("Procurement Requisition")
	doc.update({field: value for field, value in values.items() if value})
	for line in lines:
		doc.append("items", line)
	return doc


@frappe.whitelist()
def get_quotation_lines(quotations, requisition: str | None = None) -> dict:
	"""For Get Items From on the requisition's form."""
	lines, values = _quotation_lines(frappe.parse_json(quotations), requisition)
	return {"lines": lines, "values": values}


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def open_quotations(doctype, txt, searchfield, start, page_len, filters, as_dict=False):
	"""What Get Items From offers: approved quotations with a line not yet on an open requisition."""
	filters = frappe._dict(filters or {})
	names = [
		row[0]
		for row in frappe.db.sql(
			"""
			select distinct sqi.parent from `tabSupplier Quotation Item` sqi
			inner join `tabSupplier Quotation` sq on sq.name = sqi.parent
			where sq.docstatus = 1 and ifnull(sq.status, '') != 'Stopped' and sqi.name not in (
				select line.supplier_quotation_item from `tabProcurement Requisition Item` line
				inner join `tabProcurement Requisition` req on req.name = line.parent
				where req.docstatus < 2 and req.name != %(requisition)s and ifnull(req.workflow_state, '') != 'Rejected'
					and line.supplier_quotation_item is not null
			)
			""",
			{"requisition": filters.requisition or ""},
		)
	]
	if not names:
		return []
	conditions = {"name": ("in", names)}
	for field in ("company", "supplier"):
		if filters.get(field):
			conditions[field] = filters.get(field)
	rows = frappe.get_list(
		doctype,
		filters=conditions,
		or_filters={"name": ("like", f"%{txt}%"), "supplier_name": ("like", f"%{txt}%")} if txt else None,
		fields=["name", "supplier", "supplier_name", "transaction_date", "valid_till", "currency", "grand_total"],
		order_by="transaction_date desc",
		limit_start=start,
		limit_page_length=page_len,
	)
	for row in rows:
		row.transaction_date = formatdate(row.transaction_date)
		row.valid_till = formatdate(row.valid_till) if row.valid_till else ""
		row.grand_total = fmt_money(row.grand_total, currency=row.currency)
	return rows


def _make_order(requisition, rows) -> str:
	today = getdate(nowdate())
	projects = {row.project for row in rows}
	order = frappe.new_doc("Purchase Order")
	order.update(
		{
			"supplier": rows[0].supplier,
			"company": requisition.company,
			"currency": rows[0].currency,
			"conversion_rate": rows[0].conversion_rate,
			"project": projects.pop() if len(projects) == 1 else None,
			"muhick_procurement_requisition": requisition.name,
			"muhick_procurement_type": requisition.procurement_type,
			"muhick_payment_type": requisition.payment_terms_type,
			"muhick_advance_percent": requisition.advance_percent,
			"muhick_credit_days": requisition.credit_days,
			"muhick_mode_of_payment": requisition.mode_of_payment,
			"muhick_delivery_location": requisition.delivery_location,
			"muhick_delivery_period": requisition.delivery_period,
		}
	)
	for row in rows:
		required = max(getdate(row.schedule_date), today) if row.schedule_date else today
		order.append(
			"items",
			{
				"item_code": row.item_code,
				"description": row.description,
				"qty": row.qty,
				"rate": row.rate,
				"uom": row.uom,
				"schedule_date": required,
				"warehouse": row.warehouse,
				"project": row.project,
				"muhick_cost_code": row.cost_code,
				"material_request": row.material_request,
				"material_request_item": row.material_request_item,
				"supplier_quotation": row.supplier_quotation,
				"supplier_quotation_item": row.supplier_quotation_item,
			},
		)
	order.schedule_date = max(i.schedule_date for i in order.items)
	# saved on the server so ERPNext fills taxes and accounts and the approved rates are kept
	order.insert()
	return order.name


@frappe.whitelist()
def make_purchase_order(source_name: str) -> list:
	"""Raise the approved requisition's orders as saved drafts for the lines not yet ordered: one per supplier, and per
	currency should a supplier have quoted in two. A draft already raised is used, not raised again."""
	requisition = frappe.get_doc("Procurement Requisition", source_name)
	requisition.check_permission("read")
	if requisition.docstatus != 1:
		frappe.throw(_("The requisition must be approved before the order is raised."))
	groups = defaultdict(list)
	for row in requisition.items:
		if not row.purchase_order:
			groups[row.supplier, row.currency].append(row)
	if not groups:
		frappe.throw(_("Every line of this requisition is already ordered."))
	drafts = {
		(order.supplier, order.currency): order.name
		for order in frappe.get_all(
			"Purchase Order",
			filters={"muhick_procurement_requisition": requisition.name, "docstatus": 0},
			fields=["name", "supplier", "currency"],
		)
	}
	return [drafts.get(key) or _make_order(requisition, rows) for key, rows in groups.items()]


def _over_budget_lines(requisition, project) -> list:
	"""Per cost code and item, what goes over the budget: the price above budget, the quantity above budget, and at
	least what the cost code is short of when the requisition is over budget."""
	excess = budget_engine.quantities_over_budget(project, requisition.new_quantities(project))
	lines = {}
	for row in requisition.items:
		if row.project != project:
			continue
		line = lines.setdefault(
			(row.cost_code or "", row.item_code),
			frappe._dict(cost_code=row.cost_code, item_code=row.item_code, description=row.item_name, amount=0, qty=0, reasons=[]),
		)
		above_price = max(flt(row.price_variance), 0)
		if above_price:
			line.amount += above_price
			line.reasons.append(
				_("{0} quoted {1} against {2} budgeted").format(
					row.supplier_name,
					frappe.format_value(flt(row.rate) * (flt(row.conversion_rate) or 1), "Currency"),
					frappe.format_value(row.budget_rate, "Currency"),
				)
			)
		above_qty = excess.pop(row.item_code, 0)
		if above_qty:
			# at what the budget allows for one, or at what it costs where the budget has no price for it
			unit = (flt(row.budget_rate) * flt(row.qty) or flt(row.base_amount)) / (flt(row.stock_qty) or 1)
			line.amount += above_qty * unit
			line.qty += above_qty
			line.reasons.append(_("{0} above the budgeted quantity").format(f"{above_qty:g}"))
	if requisition.budget_status in OVER_BUDGET:
		available = budget_engine.get_available(project) or {}
		allowance = _approved_overrun(requisition).get(project) or {}
		for cost_code, amount in requisition.amounts_by_project()[project].items():
			short = amount - flt(available.get(cost_code)) - flt(allowance.get(cost_code))
			on_code = [line for key, line in lines.items() if key[0] == cost_code]
			missing = short - sum(line.amount for line in on_code)
			if missing > 0.5 and on_code:
				on_code[0].amount += missing
				on_code[0].reasons.append(_("cost code short by {0}").format(frappe.format_value(short, "Currency")))
	return [
		{
			"cost_code": line.cost_code,
			"item_code": line.item_code,
			"description": line.description,
			"change_amount": flt(line.amount, 2),
			"change_qty": line.qty,
			"justification": "; ".join(line.reasons),
		}
		for line in lines.values()
		if line.amount or line.qty
	]


@frappe.whitelist()
def make_cost_control_sheet(source_name: str):
	"""The Cost Control Sheet for what the requisition takes over budget on one project, filled in and not yet saved.
	Approving the sheet raises the budget, and the requisition then passes its check."""
	requisition = frappe.get_doc("Procurement Requisition", source_name)
	requisition.check_permission("read")
	projects = sorted({row.project for row in requisition.items if row.project})
	project = (frappe.flags.args or {}).get("project") or (projects[0] if projects else None)
	if project not in projects:
		frappe.throw(_("This requisition has no lines on a project."))
	if not budget_engine.get_approved_budget(project):
		frappe.throw(_("Project {0} has no approved budget to revise.").format(project))
	lines = _over_budget_lines(requisition, project)
	if not lines:
		frappe.throw(_("Nothing on this requisition is over budget for project {0}.").format(project))
	requests = {row.material_request for row in requisition.items if row.project == project and row.material_request}
	sheet = frappe.new_doc("Project Budget Revision")
	sheet.update(
		{
			"project": project,
			"project_name": frappe.db.get_value("Project", project, "project_name"),
			"company": requisition.company,
			"revision_type": "Cost Control Sheet",
			"revision_date": nowdate(),
			"material_request": requests.pop() if len(requests) == 1 else None,
			"reason": _("Procurement Requisition {0}: {1}").format(
				requisition.name, requisition.budget_remarks or _("sourced prices are above the budget")
			),
		}
	)
	for line in lines:
		sheet.append("lines", line)
	return sheet
