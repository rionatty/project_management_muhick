# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Accountability for one project, requisition by requisition: what was budgeted and asked for, what was given and what
was spent, the balance and who owes it, and the comment on any deviation. A purchase sets its LPO, delivery and invoice
side by side, and is accounted for once all three are in. Cash is accounted for once Finance has verified what was spent
and the balance is settled. A casual sheet or a claim is its own accounting, so it is done once paid."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from project_management_muhick.utils import calc

ACCOUNTED = "Accounted"
FULLY = 99.99


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "document_type", "label": _("Document Type"), "fieldtype": "Data", "width": 160},
		{"fieldname": "document", "label": _("Document"), "fieldtype": "Dynamic Link", "options": "document_type", "width": 170},
		{"fieldname": "date", "label": _("Date"), "fieldtype": "Date", "width": 105},
		{"fieldname": "milestone", "label": _("Milestone"), "fieldtype": "Data", "width": 170},
		{"fieldname": "purpose", "label": _("Purpose / Supplier"), "fieldtype": "Data", "width": 220},
		{"fieldname": "accountability", "label": _("Accountability"), "fieldtype": "Data", "width": 170},
		{"fieldname": "due_date", "label": _("Accountability Due"), "fieldtype": "Date", "width": 130},
		{"fieldname": "budgeted", "label": _("Budgeted"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "requested", "label": _("Requisitioned"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "given", "label": _("Given"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "spent", "label": _("Spent"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "balance", "label": _("Balance"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "returned", "label": _("Returned"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "to_return", "label": _("Still to Return"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "to_pay", "label": _("Still to Pay"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "lpo", "label": _("LPO"), "fieldtype": "Data", "width": 170},
		{"fieldname": "lpo_amount", "label": _("LPO Amount"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "delivery", "label": _("Delivery"), "fieldtype": "Data", "width": 170},
		{"fieldname": "delivered_amount", "label": _("Delivered Amount"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "invoice", "label": _("Invoice"), "fieldtype": "Data", "width": 170},
		{"fieldname": "invoiced_amount", "label": _("Invoiced Amount"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "variance", "label": _("Against Requisitioned"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "comments", "label": _("Comments"), "fieldtype": "Data", "width": 300},
	]
	if not filters.project:
		return columns, []
	data = [
		*cash_requisitions(filters.project),
		*purchases(filters.project),
		*casual_sheets(filters.project),
		*claims(filters.project),
	]
	data.sort(key=lambda row: (getdate(row["date"]) if row["date"] else getdate("1900-01-01"), row["document"]))
	if filters.only_open:
		data = [row for row in data if row["accountability"] != _(ACCOUNTED)]
	return columns, data


def _subjects(tasks) -> dict:
	tasks = {task for task in tasks if task}
	if not tasks:
		return {}
	return {t.name: t.subject for t in frappe.get_all("Task", filters={"name": ("in", list(tasks))}, fields=["name", "subject"])}


def cash_requisitions(project) -> list:
	"""Cash given against a requisition, accounted for with receipts; the balance is returned, or reimbursed if overspent."""
	docs = frappe.get_all(
		"Project Requisition",
		filters={"project": project, "docstatus": 1, "status": ("not in", ("Rejected", "Cancelled"))},
		fields=[
			"name", "requisition_date", "phase", "purpose_title", "payee", "status", "accountability_due_date", "total_amount",
			"amount_issued", "amount_spent", "returned_amount", "reimbursement_due", "reimbursed_amount", "budget_remarks",
		],
	)
	subjects = _subjects(doc.phase for doc in docs)
	# what the person said of a line that was not what was asked for
	reasons = defaultdict(list)
	if docs:
		for line in frappe.get_all(
			"Project Requisition Expense", filters={"parent": ("in", [doc.name for doc in docs])}, fields=["parent", "description", "reason"]
		):
			if line.reason:
				reasons[line.parent].append(f"{line.description}: {line.reason}")
	rows = []
	for doc in docs:
		position = calc.accountability_position(doc.amount_issued, doc.amount_spent, doc.returned_amount)
		verified = doc.status in ("Accounted", "Closed")
		rows.append(
			{
				"document_type": "Project Requisition",
				"document": doc.name,
				"date": doc.requisition_date,
				"milestone": subjects.get(doc.phase),
				"purpose": ", ".join(filter(None, (doc.purpose_title, doc.payee))),
				"accountability": _cash_status(doc, position),
				"due_date": doc.accountability_due_date,
				"requested": flt(doc.total_amount),
				"given": flt(doc.amount_issued),
				"spent": flt(doc.amount_spent),
				"balance": flt(doc.amount_issued) - flt(doc.amount_spent),
				"returned": flt(doc.returned_amount),
				"to_return": position["balance_outstanding"] if verified else 0,
				"to_pay": flt(doc.reimbursement_due) - flt(doc.reimbursed_amount) if doc.status == "Accounted" else 0,
				"variance": flt(doc.amount_spent) - flt(doc.total_amount) if flt(doc.amount_spent) else 0,
				"comments": "; ".join(reasons[doc.name]) or doc.budget_remarks,
			}
		)
	return rows


def _cash_status(doc, position) -> str:
	if doc.status == "Approved":
		return _("Not Yet Given")
	if doc.status == "Paid":
		overdue = doc.accountability_due_date and getdate(doc.accountability_due_date) < getdate(nowdate())
		return _("Overdue") if overdue else _("To Account For")
	if doc.status == "Accountability Submitted":
		return _("With Finance to Verify")
	if doc.status == "Accounted":
		return _("Balance to Return") if position["balance_outstanding"] > 0.005 else _("To Reimburse")
	return _(ACCOUNTED) if doc.status == "Closed" else _(doc.status)


def purchases(project) -> list:
	"""A procurement requisition's lines on the project, against its LPOs, what was delivered on them and what was
	invoiced, in the company's currency. All these are without VAT to compare with what was asked for; what was paid
	includes it, so what was spent, to compare with that, is what was invoiced with its VAT."""
	lines = frappe.get_all(
		"Procurement Requisition Item",
		filters={"project": project, "parenttype": "Procurement Requisition"},
		fields=["parent", "qty", "base_amount", "budget_rate", "purchase_order", "material_request"],
	)
	docs = (
		frappe.get_all(
			"Procurement Requisition",
			filters={"name": ("in", list({line.parent for line in lines})), "docstatus": 1, "status": ("not in", ("Rejected", "Cancelled"))},
			fields=["name", "requisition_date", "suppliers", "status", "amendment_summary", "budget_remarks"],
		)
		if lines
		else []
	)
	if not docs:
		return []
	by_requisition = defaultdict(list)
	for line in lines:
		by_requisition[line.parent].append(line)
	requests = {line.material_request for line in lines if line.material_request}
	phases = (
		{r.name: r.muhick_phase for r in frappe.get_all("Material Request", filters={"name": ("in", list(requests))}, fields=["name", "muhick_phase"])}
		if requests
		else {}
	)
	subjects = _subjects(phases.values())
	order_names = list({line.purchase_order for line in lines if line.purchase_order})
	orders = _orders(order_names)
	received = _lines_on_orders("Purchase Receipt Item", order_names)
	invoiced = _lines_on_orders("Purchase Invoice Item", order_names)
	invoices = _invoices(invoiced)
	paid_on, entries = _paid_on([*order_names, *invoices])
	on_account = _paid_on_account([doc.name for doc in docs], entries)
	rows = []
	for doc in docs:
		own = by_requisition[doc.name]
		names = sorted({line.purchase_order for line in own if line.purchase_order})
		bills = [row for name in names for row in invoiced.get(name, [])]
		requested = sum(flt(line.base_amount) for line in own)
		invoiced_amount = sum(flt(row.base_net_amount) for row in bills)
		# an invoice over several orders goes to each by its lines on it
		shares = defaultdict(float)
		for row in bills:
			if flt(invoices[row.parent].base_net_total):
				shares[row.parent] += flt(row.base_net_amount) / flt(invoices[row.parent].base_net_total)
		given = sum(paid_on.get(name, 0) for name in names) + on_account.get(doc.name, 0)
		given += sum(share * paid_on.get(invoice, 0) for invoice, share in shares.items())
		spent = sum(share * flt(invoices[invoice].base_grand_total) for invoice, share in shares.items())
		status = _purchase_status(doc, [orders[name] for name in names if name in orders])
		milestones = {subjects.get(phases.get(line.material_request)) for line in own}
		rows.append(
			{
				"document_type": "Procurement Requisition",
				"document": doc.name,
				"date": doc.requisition_date,
				"milestone": ", ".join(sorted(filter(None, milestones))),
				"purpose": doc.suppliers,
				"accountability": status,
				"budgeted": sum(flt(line.budget_rate) * flt(line.qty) for line in own),
				"requested": requested,
				"given": given,
				"spent": spent,
				"balance": given - spent,
				"to_return": max(given - spent, 0) if status == _(ACCOUNTED) else 0,
				"to_pay": max(spent - given, 0),
				"lpo": ", ".join(names),
				"lpo_amount": sum(flt(orders[name].base_net_total) for name in names if name in orders),
				"delivery": ", ".join(sorted({row.parent for name in names for row in received.get(name, [])})),
				"delivered_amount": sum(flt(row.base_net_amount) for name in names for row in received.get(name, [])),
				"invoice": ", ".join(sorted({row.parent for row in bills})),
				"invoiced_amount": invoiced_amount,
				"variance": invoiced_amount - requested if bills else 0,
				"comments": doc.amendment_summary or doc.budget_remarks,
			}
		)
	return rows


def _orders(names) -> dict:
	if not names:
		return {}
	return {
		order.name: order
		for order in frappe.get_all(
			"Purchase Order", filters={"name": ("in", names), "docstatus": 1}, fields=["name", "base_net_total", "per_received", "per_billed"]
		)
	}


def _lines_on_orders(doctype, orders) -> dict:
	"""{order: the submitted receipt or invoice lines on it}."""
	out = defaultdict(list)
	if orders:
		for row in frappe.get_all(
			doctype, filters={"purchase_order": ("in", orders), "docstatus": 1}, fields=["parent", "purchase_order", "base_net_amount"]
		):
			out[row.purchase_order].append(row)
	return out


def _invoices(invoiced) -> dict:
	"""{invoice: its totals without VAT and with it} for the invoice lines given."""
	names = list({row.parent for rows in invoiced.values() for row in rows})
	if not names:
		return {}
	return {
		i.name: i for i in frappe.get_all("Purchase Invoice", filters={"name": ("in", names)}, fields=["name", "base_net_total", "base_grand_total"])
	}


def _paid_on(names) -> tuple:
	"""What submitted payments have paid on these orders and invoices in the company's currency, as {order or invoice:
	paid}, and which payments those are."""
	amounts, entries = defaultdict(float), set()
	if names:
		for row in frappe.get_all(
			"Payment Entry Reference",
			filters={"reference_name": ("in", names), "docstatus": 1},
			fields=["parent", "reference_name", "allocated_amount", "exchange_rate"],
		):
			amounts[row.reference_name] += flt(row.allocated_amount) * (flt(row.exchange_rate) or 1)
			entries.add(row.parent)
	return amounts, entries


def _paid_on_account(requisitions, counted) -> dict:
	"""{requisition: what was paid on it before an order existed}, leaving out the payments already counted on an order."""
	out = defaultdict(float)
	for entry in frappe.get_all(
		"Payment Entry",
		filters={"muhick_procurement_requisition": ("in", requisitions), "docstatus": 1},
		fields=["name", "muhick_procurement_requisition", "base_paid_amount"],
	):
		if entry.name not in counted:
			out[entry.muhick_procurement_requisition] += flt(entry.base_paid_amount)
	return out


def _purchase_status(doc, orders) -> str:
	if not orders:
		return _("Waiting for LPO")
	if doc.status == "Partly Ordered":
		return _("Waiting for LPO on the Rest")
	if any(flt(order.per_received) < FULLY for order in orders):
		return _("Waiting for Delivery")
	if any(flt(order.per_billed) < FULLY for order in orders):
		return _("Waiting for Invoice")
	return _(ACCOUNTED)


def casual_sheets(project) -> list:
	docs = frappe.get_all(
		"Casual Sheet",
		filters={"project": project, "docstatus": 1, "status": ("not in", ("Rejected", "Cancelled"))},
		fields=["name", "period_to", "phase", "status", "scheduled_amount", "total_amount", "paid_amount", "variance", "variance_explanation"],
	)
	subjects = _subjects(doc.phase for doc in docs)
	rows = []
	for doc in docs:
		paid = flt(doc.paid_amount) or (flt(doc.total_amount) if doc.status == "Paid" else 0)
		rows.append(
			{
				"document_type": "Casual Sheet",
				"document": doc.name,
				"date": doc.period_to,
				"milestone": subjects.get(doc.phase),
				"purpose": _("Casual labour"),
				"accountability": _(ACCOUNTED) if paid else _("Not Yet Given"),
				"budgeted": flt(doc.scheduled_amount),
				"requested": flt(doc.total_amount),
				"given": paid,
				"spent": paid,
				"to_pay": flt(doc.total_amount) - paid,
				"variance": flt(doc.variance),
				"comments": doc.variance_explanation,
			}
		)
	return rows


def claims(project) -> list:
	"""Money someone spent of their own and claims back: spent from the start, given once paid."""
	rows = []
	for doc in frappe.get_all(
		"Reimbursement Claim",
		filters={"project": project, "docstatus": 1, "status": ("not in", ("Rejected", "Cancelled"))},
		fields=["name", "posting_date", "claimant_name", "purpose", "status", "total_amount", "emergency_reason"],
	):
		paid = flt(doc.total_amount) if doc.status == "Paid" else 0
		rows.append(
			{
				"document_type": "Reimbursement Claim",
				"document": doc.name,
				"date": doc.posting_date,
				"purpose": ", ".join(filter(None, (doc.claimant_name, doc.purpose))),
				"accountability": _(ACCOUNTED) if paid else _("To Reimburse"),
				"requested": flt(doc.total_amount),
				"given": paid,
				"spent": flt(doc.total_amount),
				"balance": paid - flt(doc.total_amount),
				"to_pay": flt(doc.total_amount) - paid,
				"comments": doc.emergency_reason,
			}
		)
	return rows
