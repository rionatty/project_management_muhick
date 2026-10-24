# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Daily reminders: accountability, site reports, claims, warranties, phases, payables, shipments."""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, nowdate

from project_management_muhick.utils.common import FINANCE_ROLES, PRM, PRO, get_settings, notify, notify_roles, project_manager_of

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def send_daily_reminders():
	jobs = (
		overdue_accountability, missing_weekly_reports, phases_due_for_claim, expiring_warranties,
		phases_starting, payables_falling_due, shipments_needing_attention,
		bids_needing_attention, bank_instruments_needing_attention, contracts_and_maintenance_due,
	)
	for job in jobs:
		try:
			job()
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"Muhick: reminder {job.__name__} failed")


def overdue_accountability():
	today = nowdate()
	rows = frappe.get_all(
		"Project Requisition",
		filters={"docstatus": 1, "status": "Paid", "accountability_due_date": ("<", today)},
		fields=["name", "requested_by", "accountability_due_date"],
	)
	for r in rows:
		doc = frappe._dict(doctype="Project Requisition", name=r.name)
		notify([r.requested_by], _("Accountability for {0} was due on {1}.").format(r.name, r.accountability_due_date), doc=doc)
	if rows:
		notify_roles(FINANCE_ROLES, _("{0} requisition(s) have overdue accountability.").format(len(rows)))


def missing_weekly_reports():
	settings = get_settings()
	if not settings.send_report_reminders:
		return
	today = getdate(nowdate())
	if WEEKDAYS[today.weekday()] != (settings.weekly_report_day or "Monday"):
		return
	since = add_days(today, -7)
	for p in frappe.get_all(
		"Project", filters={"muhick_stage": "Execution", "status": "Open"}, fields=["name", "project_name", "muhick_project_manager", "owner"]
	):
		reported = frappe.db.exists(
			"Site Report", {"project": p.name, "report_type": "Weekly", "docstatus": ("<", 2), "period_to": (">=", since)}
		)
		if not reported:
			notify(
				[p.muhick_project_manager or p.owner],
				_("The weekly site report for {0} is due.").format(p.project_name),
				doc=frappe._dict(doctype="Project", name=p.name),
			)


def phases_due_for_claim():
	"""A completed billing phase that has not been claimed is revenue waiting."""
	rows = frappe.get_all(
		"Task",
		filters={
			"is_group": 1, "muhick_is_billing_milestone": 1, "progress": (">=", 100),
			"status": ("!=", "Cancelled"), "muhick_billing_status": ("is", "not set"),
		},
		fields=["name", "subject", "project"],
	)
	for p in rows:
		notify(
			[project_manager_of(p.project)],
			_("Milestone {0} is complete but not yet claimed.").format(p.subject),
			doc=frappe._dict(doctype="Task", name=p.name),
		)


def expiring_warranties():
	settings = get_settings()
	today = getdate(nowdate())
	frappe.db.set_value("Project Warranty", {"status": "Active", "warranty_end": ("<", today)}, "status", "Expired")
	horizon = add_days(today, settings.warranty_reminder_days or 30)
	for w in frappe.get_all(
		"Project Warranty",
		filters={"status": "Active", "reminder_sent": 0, "warranty_end": ("<=", horizon)},
		fields=["name", "item_description", "project", "warranty_end"],
	):
		notify(
			[project_manager_of(w.project)],
			_("Warranty on {0} ends on {1}.").format(w.item_description, w.warranty_end),
			doc=frappe._dict(doctype="Project Warranty", name=w.name),
		)
		frappe.db.set_value("Project Warranty", w.name, "reminder_sent", 1)


def phases_starting():
	"""Tell Procurement and the Project Manager that a new phase is about to begin."""
	days = get_settings().phase_alert_days or 7
	today = getdate(nowdate())
	for p in frappe.get_all(
		"Task",
		filters={
			"is_group": 1, "parent_task": ("is", "not set"), "status": "Open",
			"exp_start_date": ("between", [today, add_days(today, days)]),
		},
		fields=["name", "subject", "project", "exp_start_date"],
	):
		start = getdate(p.exp_start_date)
		# once a week per phase is enough
		if today.weekday() != 0 and start != add_days(today, days):
			continue
		doc = frappe._dict(doctype="Task", name=p.name)
		subject = _("Milestone {0} of project {1} starts on {2}. Raise its material request so the items are ordered.").format(
			p.subject, p.project, start
		)
		notify_roles([PRM, PRO], subject, doc=doc, extra_users=[project_manager_of(p.project)])


def payables_falling_due():
	"""Tell Finance how many supplier invoices fall due soon and are not yet on a payment plan."""
	days = get_settings().payables_alert_days or 7
	today = getdate(nowdate())
	due = frappe.db.sql(
		"""
		select count(*), sum(pi.outstanding_amount) from `tabPurchase Invoice` pi
		where pi.docstatus = 1 and pi.outstanding_amount > 0 and pi.on_hold = 0 and pi.due_date <= %s
			and not exists (
				select 1 from `tabPayment Plan Line` l inner join `tabPayment Plan` p on p.name = l.parent
				where l.reference_doctype = 'Purchase Invoice' and l.reference_name = pi.name
					and p.docstatus < 2 and p.status in ('Draft', 'Pending Approval', 'Approved')
			)
		""",
		(add_days(today, days),),
	)
	count, amount = due[0] if due else (0, 0)
	if count:
		notify_roles(
			FINANCE_ROLES,
			_("{0} supplier invoice(s) totalling {1} fall due within {2} days and are not on a payment plan.").format(
				count, frappe.format_value(amount, "Currency"), days
			),
		)


def shipments_needing_attention():
	"""Imports: the 72-hour tax deadline, and consignments running behind schedule."""
	today = getdate(nowdate())
	for s in frappe.get_all(
		"Import Shipment",
		filters={"shipment_status": ("not in", ("Delivered", "Closed"))},
		fields=["name", "title", "project", "tax_payment_deadline", "tax_paid_on", "is_delayed", "last_alert_on"],
	):
		doc = frappe._dict(doctype="Import Shipment", name=s.name)
		if s.tax_payment_deadline and not s.tax_paid_on:
			notify_roles(
				[*FINANCE_ROLES, PRM],
				_("{0}: import taxes must be paid by {1}.").format(s.title, s.tax_payment_deadline),
				doc=doc,
			)
		if s.is_delayed and (not s.last_alert_on or (today - getdate(s.last_alert_on)).days >= 7):
			notify_roles([PRM, PRO], _("{0} is behind schedule.").format(s.title), doc=doc, extra_users=[project_manager_of(s.project)])
			frappe.db.set_value("Import Shipment", s.name, "last_alert_on", today, update_modified=False)


def _alert_due(doctype, name, last_alert_on, today, every_days=7) -> bool:
	"""True when a record has not been alerted on for a while; stamps it so it is not repeated daily."""
	if last_alert_on and (today - getdate(last_alert_on)).days < every_days:
		return False
	frappe.db.set_value(doctype, name, "last_alert_on", today, update_modified=False)
	return True


def bids_needing_attention():
	"""Bid submission deadlines coming up. Follow-ups are the opportunity's own activities."""
	today = getdate(nowdate())
	days = get_settings().bid_deadline_alert_days or 3
	for o in frappe.get_all(
		"Opportunity",
		filters={
			"status": "Open",
			"sales_stage": ("in", ("Qualified", "In Preparation")),
			"muhick_submission_deadline": ("is", "set"),
		},
		fields=["name", "customer_name", "opportunity_owner", "muhick_submission_deadline"],
	):
		left = (getdate(o.muhick_submission_deadline) - today).days
		if 0 <= left <= days:
			notify_roles(
				"Head of Sales",
				_("Bid {0} ({1}) is due for submission in {2} day(s).").format(o.name, o.customer_name, left),
				doc=frappe._dict(doctype="Opportunity", name=o.name),
				extra_users=[o.opportunity_owner],
			)


def bank_instruments_needing_attention():
	"""Quarterly bank fees falling due, instruments about to expire, and cancellations not yet done."""
	today = getdate(nowdate())
	for i in frappe.get_all(
		"Bank Instrument",
		filters={"status": ("in", ("Active", "Cancellation Requested"))},
		fields=["name", "title", "status", "expiry_date", "next_fee_due", "last_alert_on"],
	):
		messages = []
		if i.status == "Cancellation Requested":
			messages.append(_("cancellation was requested and is still open; the bank keeps charging for it"))
		if i.next_fee_due and (getdate(i.next_fee_due) - today).days <= 7:
			messages.append(_("the next quarterly fee falls due on {0}").format(i.next_fee_due))
		if i.expiry_date and (getdate(i.expiry_date) - today).days <= 30:
			messages.append(_("it ends on {0}").format(i.expiry_date))
		if messages and _alert_due("Bank Instrument", i.name, i.last_alert_on, today):
			notify_roles(
				FINANCE_ROLES, f"{i.title}: " + "; ".join(messages) + ".", doc=frappe._dict(doctype="Bank Instrument", name=i.name)
			)


def contracts_and_maintenance_due():
	"""Administration: contracts to renew, facility servicing and vehicle servicing falling due."""
	today = getdate(nowdate())
	admin = "Administration Manager"
	frappe.db.set_value("Service Contract", {"status": "Active", "end_date": ("<", today)}, "status", "Expired")
	for c in frappe.get_all(
		"Service Contract",
		filters={"status": "Active", "reminder_sent": 0},
		fields=["name", "title", "end_date", "reminder_days"],
	):
		if (getdate(c.end_date) - today).days <= (c.reminder_days or 30):
			notify_roles(
				[admin, *FINANCE_ROLES],
				_("Contract {0} is due for renewal on {1}.").format(c.title, c.end_date),
				doc=frappe._dict(doctype="Service Contract", name=c.name),
			)
			frappe.db.set_value("Service Contract", c.name, "reminder_sent", 1)
	for m in frappe.get_all(
		"Facility Maintenance Schedule",
		filters={"next_due": ("<=", add_days(today, 14))},
		fields=["name", "facility_item", "next_due", "responsible", "last_alert_on"],
	):
		status = "Overdue" if getdate(m.next_due) < today else "Due"
		frappe.db.set_value("Facility Maintenance Schedule", m.name, "status", status, update_modified=False)
		if _alert_due("Facility Maintenance Schedule", m.name, m.last_alert_on, today):
			notify_roles(
				admin,
				_("{0} is due for servicing on {1}.").format(m.facility_item, m.next_due),
				doc=frappe._dict(doctype="Facility Maintenance Schedule", name=m.name),
				extra_users=[m.responsible],
			)
	for v in frappe.get_all(
		"Vehicle Service Request",
		filters={"status": "Completed", "reminder_sent": 0, "next_service_date": ("<=", add_days(today, 14))},
		fields=["name", "vehicle", "next_service_date"],
	):
		notify_roles(
			[admin, "Fleet Officer"],
			_("Vehicle {0} is due for service on {1}.").format(v.vehicle, v.next_service_date),
			doc=frappe._dict(doctype="Vehicle Service Request", name=v.name),
		)
		frappe.db.set_value("Vehicle Service Request", v.name, "reminder_sent", 1)
