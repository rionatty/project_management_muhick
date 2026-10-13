# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Project lifecycle: contract data, site store, activation gates and certified position."""

import frappe
from frappe import _
from frappe.utils import add_months, flt, getdate, nowdate

from project_management_muhick.utils import calc
from project_management_muhick.utils.common import COO, PM, get_settings, require_roles

STAGES = ("Planning", "Execution", "Practical Completion", "Full Completion")
CERTIFIED = ("Certified", "Invoiced", "Paid")


# ------------------------------------------------------------------ doc events
def validate(doc, method=None):
	settings = get_settings()
	if doc.is_new():
		if doc.get("muhick_retention_percent") is None:
			doc.muhick_retention_percent = settings.default_retention_percent
		if not doc.get("muhick_dlp_months"):
			doc.muhick_dlp_months = settings.default_dlp_months
	if not doc.get("muhick_stage"):
		doc.muhick_stage = "Planning"
	if doc.get("muhick_contract_start") and doc.get("muhick_contract_end"):
		if getdate(doc.muhick_contract_end) < getdate(doc.muhick_contract_start):
			frappe.throw(_("Contract End cannot be before Contract Start."))
	doc.muhick_revised_contract_value = flt(doc.get("muhick_contract_value")) + flt(doc.get("muhick_approved_variations"))
	if flt(doc.get("muhick_advance_percent")) and not flt(doc.get("muhick_advance_amount")):
		doc.muhick_advance_amount = flt(doc.muhick_contract_value) * flt(doc.muhick_advance_percent) / 100


def after_insert(doc, method=None):
	create_site_warehouse(doc)


def create_site_warehouse(doc):
	"""A project-specific store, created with the project."""
	settings = get_settings()
	if not settings.auto_create_site_warehouse or doc.get("muhick_site_warehouse"):
		return
	parent = settings.site_store_parent_warehouse
	if not parent:
		frappe.msgprint(
			_("No site store was created: set the Parent Warehouse for Site Stores in Muhick Settings."),
			indicator="orange",
			alert=True,
		)
		return
	if frappe.db.get_value("Warehouse", parent, "company") != doc.company:
		frappe.msgprint(
			_("No site store was created: the parent warehouse {0} belongs to another company.").format(parent),
			indicator="orange",
			alert=True,
		)
		return
	client_store = doc.get("muhick_site_store_type") == "Client"
	try:
		warehouse = frappe.get_doc(
			doctype="Warehouse",
			warehouse_name=f"{doc.name} {doc.project_name}"[:120],
			parent_warehouse=parent,
			company=doc.company,
			muhick_store_type="Client Store" if client_store else "Site Store",
			muhick_project=doc.name,
			# stock stays the company's until installed, even in a client-run store
			muhick_stock_ownership="Project",
		).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(title=f"Muhick: site store creation failed for {doc.name}")
		frappe.msgprint(_("The site store could not be created. See the Error Log."), indicator="orange", alert=True)
		return
	doc.db_set("muhick_site_warehouse", warehouse.name, update_modified=False)


# ------------------------------------------------------------------ stage
def set_stage(project, stage):
	if stage not in STAGES:
		frappe.throw(_("Unknown project stage {0}").format(stage))
	frappe.db.set_value("Project", project, "muhick_stage", stage)


def get_gate_status(project) -> list[dict]:
	"""The conditions a project must meet before execution starts, and whether each is met."""
	settings = get_settings()
	p = frappe.db.get_value("Project", project, ["muhick_handover", "muhick_budget", "muhick_activity_plan"], as_dict=True)
	gates = []
	if settings.require_handover_before_execution:
		ok = bool(p.muhick_handover and frappe.db.get_value("Project Handover", p.muhick_handover, "docstatus") == 1)
		gates.append({"gate": _("Sales handover accepted by the Project Manager"), "met": ok})
	if settings.require_budget_before_execution:
		ok = bool(frappe.db.exists("Project Budget", {"project": project, "docstatus": 1}))
		gates.append({"gate": _("Project budget approved"), "met": ok})
	if settings.require_activity_plan_before_execution:
		ok = bool(frappe.db.exists("Project Activity Plan", {"project": project, "docstatus": 1, "is_current": 1}))
		gates.append({"gate": _("Activity plan approved"), "met": ok})
	return gates


@frappe.whitelist()
def get_gates(project: str):
	frappe.has_permission("Project", "read", project, throw=True)
	return get_gate_status(project)


@frappe.whitelist()
def start_execution(project: str):
	"""Move a project from Planning to Execution once every activation gate is met."""
	require_roles(PM, COO)
	frappe.has_permission("Project", "write", project, throw=True)
	if frappe.db.get_value("Project", project, "muhick_stage") != "Planning":
		frappe.throw(_("Only a project in Planning can be started."))
	missing = [g["gate"] for g in get_gate_status(project) if not g["met"]]
	if missing:
		frappe.throw(
			_("The project cannot start execution yet:") + "<br>" + "<br>".join(f"- {m}" for m in missing),
			title=_("Activation Gates Not Met"),
		)
	set_stage(project, "Execution")
	frappe.get_doc("Project", project).add_comment("Info", _("Execution started by {0}").format(frappe.session.user))
	return "Execution"


# ------------------------------------------------------------------ progress and position
def update_progress(project):
	"""Project progress from its milestones, weighted as in the approved activity plan."""
	rows = frappe.get_all("Project Milestone", filters={"project": project}, fields=["weight", "percent_complete"])
	if not rows:
		return
	progress = calc.weighted_progress([(r.weight, r.percent_complete) for r in rows])
	# ERPNext recalculates the figure itself unless the project is on manual progress
	if frappe.db.get_value("Project", project, "percent_complete_method") == "Manual":
		frappe.db.set_value("Project", project, "percent_complete", progress, update_modified=False)
	return progress


def update_position(project):
	"""Contract value, certified work, retention and advance recovery from the source documents."""
	p = frappe.db.get_value(
		"Project",
		project,
		[
			"muhick_contract_value", "muhick_opening_certified", "muhick_opening_retention_held",
			"muhick_opening_retention_released", "muhick_opening_advance_recovered",
		],
		as_dict=True,
	)
	if not p:
		return
	claims = frappe.get_all(
		"Project Claim",
		filters={"project": project, "docstatus": 1, "status": ("in", CERTIFIED)},
		fields=["claim_type", "certified_amount", "certified_retention", "certified_advance_recovery"],
	)
	variations = sum(
		flt(v)
		for v in frappe.get_all("Project Variation Order", filters={"project": project, "docstatus": 1}, pluck="total_amount")
	)
	released = sum(
		flt(a)
		for a in frappe.get_all(
			"Retention Release", filters={"project": project, "docstatus": 1, "retention_for": "Client"}, pluck="amount"
		)
	)
	frappe.db.set_value(
		"Project",
		project,
		{
			"muhick_approved_variations": variations,
			"muhick_revised_contract_value": flt(p.muhick_contract_value) + variations,
			# an advance claim is money received early, not work certified
			"muhick_certified_to_date": flt(p.muhick_opening_certified)
			+ sum(flt(c.certified_amount) for c in claims if c.claim_type != "Advance"),
			"muhick_retention_held": flt(p.muhick_opening_retention_held) + sum(flt(c.certified_retention) for c in claims),
			"muhick_advance_recovered": flt(p.muhick_opening_advance_recovered)
			+ sum(flt(c.certified_advance_recovery) for c in claims),
			"muhick_retention_released": flt(p.muhick_opening_retention_released) + released,
		},
		update_modified=False,
	)


# ------------------------------------------------------------------ scheduled
def send_dlp_reminders():
	"""The system tracks the Defects Liability Period and reminds
	the Project Manager as it approaches its end and once it has ended."""
	from project_management_muhick.utils.common import notify

	settings = get_settings()
	lead_days = settings.dlp_reminder_days or 30
	every = settings.dlp_reminder_frequency_days or 7
	today = getdate(nowdate())
	projects = frappe.get_all(
		"Project",
		filters={"muhick_stage": "Practical Completion", "muhick_dlp_end_date": ("is", "set")},
		fields=["name", "project_name", "muhick_dlp_end_date", "muhick_project_manager", "muhick_last_dlp_reminder", "owner"],
	)
	for p in projects:
		days_left = (getdate(p.muhick_dlp_end_date) - today).days
		if days_left > lead_days:
			continue
		if p.muhick_last_dlp_reminder and (today - getdate(p.muhick_last_dlp_reminder)).days < every:
			continue
		open_defects = frappe.db.count("Project Defect", {"project": p.name, "status": ("in", ("Open", "In Progress"))})
		if days_left >= 0:
			subject = _("{0}: Defects Liability Period ends in {1} days ({2} open defects)").format(p.project_name, days_left, open_defects)
		else:
			subject = _("{0}: Defects Liability Period ended {1} days ago. Record Full Completion and release retention ({2} open defects)").format(
				p.project_name, -days_left, open_defects
			)
		notify([p.muhick_project_manager or p.owner], subject, doc=frappe._dict(doctype="Project", name=p.name))
		frappe.db.set_value("Project", p.name, "muhick_last_dlp_reminder", today, update_modified=False)
	frappe.db.commit()


def dlp_end_date(practical_completion_date, months):
	return add_months(practical_completion_date, int(months or 0))
