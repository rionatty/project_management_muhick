# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

"""Leads and opportunities follow the sales process: whether to pursue a lead is the Head of Sales'
decision, recorded with who made it and when, and only a qualified lead becomes an opportunity.

The opportunity is the bid: its tender, the three parts of the bid, the submission, the bid
security and the outcome. Its documents are on a checklist, each tracked as a document of its own, and
a part of the bid is ready once all its documents are; a bid is complete with all three parts before
it is submitted.

It has two statuses, each moving by itself. The bid status (the Sales Stage) follows the tender, from
Qualified to Won, Lost, Not Pursued or Cancelled; the opportunity status (the standard status) follows
the sale, from Open to Won, Quotation and Converted, or Lost or Closed. Won and lost come only from an
outcome report approved by the Head of Sales and the General Manager, and a bid's outcome stays
whatever happens to the sale afterwards. Its milestones, from the lead to the project and each carrying
a weight, give its progress. When an opportunity is lost or closed, Finance is asked to cancel its bid
security, because the bank charges for it until it is cancelled."""

import frappe
from frappe import _
from frappe.utils import flt, format_datetime, formatdate, get_datetime, getdate, now_datetime, today

from project_management_muhick.setup.workflows import PENDING_STATES
from project_management_muhick.utils import calc
from project_management_muhick.utils.common import FINANCE_ROLES, GM, notify_roles

DECIDED = ("Qualified", "Not Pursued")
DECIDERS = {"Head of Sales", "Sales Manager"}
HOS = "Head of Sales"
BID_PARTS = (
	("muhick_administrative_bid_ready", "Administrative"),
	("muhick_technical_bid_ready", "Technical"),
	("muhick_financial_bid_ready", "Financial"),
)
# the bid statuses of a bid still going
IN_PROGRESS = ("Qualified", "In Preparation", "Submitted", "Under Evaluation", "Outcome Pending Approval")
# milestones reached by the parts of the bid, and the one the sales engineer ticks
PART_MILESTONES = {
	"Administrative Bid Ready": "muhick_administrative_bid_ready",
	"Technical Bid Ready": "muhick_technical_bid_ready",
	"Financial Bid Ready": "muhick_financial_bid_ready",
}
BY_HAND = "Ticked by Hand"
# a sales requisition whose funds have gone out
FUNDS_OUT = ("Paid", "Accountability Submitted", "Accounted", "Closed")
# the document a bid with a bid security adds to its checklist
BID_SECURITY_DOCUMENT = "Bid Security"
PART_ORDER = {part: i for i, (_field, part) in enumerate(BID_PARTS)}
SECURITY_RUNNING = ("Requested", "Active")


def validate_lead(doc, method=None):
	if not doc.has_value_changed("qualification_status"):
		return
	before = doc.get_doc_before_save()
	deciding = doc.qualification_status in DECIDED or (before and before.qualification_status in DECIDED)
	if deciding and not DECIDERS & set(frappe.get_roles()):
		frappe.throw(_("Only the Head of Sales decides whether a lead is pursued."))
	if doc.qualification_status in DECIDED:
		doc.qualified_by, doc.qualified_on = frappe.session.user, today()
	else:
		doc.qualified_by = doc.qualified_on = None


def validate_opportunity(doc, method=None):
	if doc.is_new() and doc.opportunity_from not in ("Lead", "Customer"):
		frappe.throw(_("An opportunity comes from a qualified lead or from an existing customer."))
	if doc.is_new() and doc.opportunity_from == "Lead" and doc.party_name:
		if frappe.db.get_value("Lead", doc.party_name, "qualification_status") != "Qualified":
			frappe.throw(
				_("Lead {0} has not been qualified yet. The Head of Sales qualifies a lead before it becomes an opportunity.").format(
					doc.party_name
				)
			)
	if doc.get("items"):
		doc.opportunity_amount = flt(doc.total)
		doc.base_opportunity_amount = flt(doc.total) * flt(doc.conversion_rate or 1)
	price, cost = flt(doc.opportunity_amount), flt(doc.get("muhick_estimated_cost"))
	doc.set("muhick_margin_percent", (price - cost) / price * 100 if price and cost else 0)
	kinds = requirement_kinds(doc.get("muhick_financial_requirements"))
	securities = [r for r in doc.get("muhick_financial_requirements") or [] if kinds.get(r.requirement_type) == "Bid Security"]
	doc.set("muhick_bid_security_required", 1 if securities else 0)
	doc.set("muhick_bid_security_amount", sum(flt(r.amount) for r in securities))
	set_checklist(doc)
	record_submission(doc)
	check_outcome_changes(doc)
	if doc.status == "Closed" and doc.has_value_changed("status") and not (doc.get("muhick_outcome_notes") or "").strip():
		frappe.throw(_("Give the reason the bid is being closed."))
	set_milestones(doc)
	set_bid_status(doc)
	if doc.sales_stage in IN_PROGRESS:
		doc.set("muhick_outcome_date", None)
	elif doc.status in ("Lost", "Closed") and not doc.get("muhick_outcome_date"):
		doc.set("muhick_outcome_date", today())


def set_checklist(doc):
	"""The bid's document checklist: a new bid starts with the documents every bid needs, a bid with a bid
	security adds it, and each line shows the document made for it and where it stands."""
	if doc.is_new() and not doc.get("muhick_checklist"):
		default_checklist(doc)
	add_bid_security(doc)
	apply_documents(doc, documents_of(doc))
	set_parts_ready(doc)


def add_bid_security(doc):
	listed = {r.document_type for r in doc.get("muhick_checklist") or []}
	if doc.get("muhick_bid_security_required") and BID_SECURITY_DOCUMENT not in listed:
		if frappe.db.exists("Bid Document Type", BID_SECURITY_DOCUMENT):
			doc.append("muhick_checklist", {"document_type": BID_SECURITY_DOCUMENT})


def default_checklist(doc):
	types = frappe.get_all("Bid Document Type", filters={"in_every_bid": 1}, fields=["name", "part"])
	for t in sorted(types, key=lambda t: (PART_ORDER.get(t.part, 9), t.name)):
		doc.append("muhick_checklist", {"document_type": t.name})


def documents_of(doc) -> list:
	if doc.is_new():
		return []
	return frappe.get_all(
		"Bid Document",
		filters={"opportunity": doc.name},
		fields=["name", "document_type", "status", "prepared_by"],
		order_by="creation asc",
	)


def apply_documents(doc, documents):
	"""Each checklist line with the document made for it (a document not on the checklist gets a line of
	its own) and that document's status."""
	by_name = {d.name: d for d in documents}
	rows = doc.get("muhick_checklist") or []
	for row in rows:
		linked = by_name.get(row.bid_document)
		if not (linked and linked.document_type == row.document_type):
			row.bid_document = None
	taken = {row.bid_document for row in rows if row.bid_document}
	for d in documents:
		if d.name in taken:
			continue
		row = next((r for r in rows if not r.bid_document and r.document_type == d.document_type), None)
		if not row:
			row = doc.append("muhick_checklist", {"document_type": d.document_type})
		row.bid_document = d.name
		taken.add(d.name)
	parts = dict(frappe.get_all("Bid Document Type", fields=["name", "part"], as_list=True))
	for row in doc.get("muhick_checklist") or []:
		linked = by_name.get(row.bid_document)
		row.part = parts.get(row.document_type)
		row.status = linked.status if linked else "Not Created"
		row.prepared_by = linked.prepared_by if linked else None


def set_parts_ready(doc):
	"""A part of the bid is ready once every document of that part on the checklist is ready; the
	technical part also needs every requirement answered."""
	answered = not open_requirements(doc)
	for field, part in BID_PARTS:
		rows = [r for r in doc.get("muhick_checklist") or [] if r.part == part]
		ready = bool(rows) and all(r.status == "Ready" for r in rows) and (answered or part != "Technical")
		doc.set(field, 1 if ready else 0)


def open_requirements(doc) -> list:
	return [str(r.idx) for r in doc.get("muhick_requirements") or [] if r.compliance in (None, "", "Clarification Needed")]


def sync_checklist(opportunity):
	"""After one of a bid's documents changed: its checklist line, the parts ready and the bid's status
	follow, without saving the whole bid."""
	if not opportunity or not frappe.db.exists("Opportunity", opportunity):
		return
	doc = frappe.get_doc("Opportunity", opportunity)
	known = {row.name: (row.bid_document, row.status, row.prepared_by, row.part) for row in doc.get("muhick_checklist")}
	apply_documents(doc, documents_of(doc))
	set_parts_ready(doc)
	for row in doc.get("muhick_checklist"):
		if row.name not in known:
			row.db_insert()
		elif known[row.name] != (row.bid_document, row.status, row.prepared_by, row.part):
			row.db_update()
	doc.db_set({field: doc.get(field) for field, _part in BID_PARTS}, update_modified=False)
	refresh_bid_status(opportunity)
	doc.notify_update()


@frappe.whitelist()
def create_bid_documents(opportunity: str) -> int:
	"""A document for every checklist line that has none, prepared by the sales engineer by the
	submission deadline unless it is given to someone else; each is then tracked on its own."""
	doc = frappe.get_doc("Opportunity", opportunity)
	doc.check_permission("write")
	frappe.has_permission("Bid Document", "create", throw=True)
	made = 0
	for row in doc.get("muhick_checklist") or []:
		if row.bid_document:
			continue
		document = frappe.get_doc({"doctype": "Bid Document", "opportunity": doc.name, "document_type": row.document_type})
		document.flags.skip_checklist_sync = True
		document.insert()
		made += 1
	if made:
		sync_checklist(doc.name)
	return made


def record_submission(doc):
	"""A bid is submitted once its submission is recorded with the acknowledgement, and only a complete
	bid goes in. A submission after the deadline is flagged."""
	if doc.get("muhick_acknowledgement") and not doc.get("muhick_submitted_at"):
		doc.set("muhick_submitted_at", now_datetime())
	if not (doc.has_value_changed("muhick_submitted_at") or doc.has_value_changed("muhick_acknowledgement")):
		return
	if doc.get("muhick_submitted_at") and not doc.get("muhick_acknowledgement"):
		frappe.msgprint(
			_("The bid counts as submitted once the acknowledgement is attached: the stamped receipt, the e-GP confirmation or the email."),
			indicator="orange",
			alert=True,
		)
	if is_submitted(doc):
		missing = [_(part).lower() for field, part in BID_PARTS if not doc.get(field)]
		if missing:
			waiting = [r.document_type for r in doc.get("muhick_checklist") or [] if r.status != "Ready"]
			unanswered = open_requirements(doc)
			message = [_("A bid is complete only with all three parts. Not ready yet: {0}.").format(", ".join(missing))]
			if waiting:
				message.append(_("Documents still to prepare: {0}.").format(", ".join(waiting)))
			if unanswered:
				message.append(_("Requirements still to answer: row {0}.").format(", ".join(unanswered)))
			frappe.throw(" ".join(message))
	deadline, submitted = doc.get("muhick_submission_deadline"), doc.get("muhick_submitted_at")
	if deadline and submitted and doc.has_value_changed("muhick_submitted_at") and get_datetime(submitted) > get_datetime(deadline):
		frappe.msgprint(
			_("This bid went in after its submission deadline of {0}.").format(format_datetime(deadline)),
			title=_("Submitted Late"),
			indicator="orange",
		)


def check_outcome_changes(doc):
	"""Won and lost come only from an approved outcome report, and only cancelling it reopens the bid. A
	won opportunity whose sale falls through can still be closed, and reopened as won."""
	if doc.is_new() or doc.flags.get("muhick_outcome"):
		return
	before = doc.get_doc_before_save()
	if not before:
		return
	if (doc.get("muhick_bid_outcome") or None) != (before.get("muhick_bid_outcome") or None):
		frappe.throw(_("The outcome report of a bid is set by its approval."))
	outcome = doc.get("muhick_bid_outcome")
	approved = frappe.db.get_value("Bid Outcome", outcome, "outcome") if outcome else None
	if doc.status in ("Won", "Lost") and doc.status != before.status and doc.status != approved:
		frappe.throw(
			_("A bid is won or lost with its outcome report (Outcome > Won or Lost on the opportunity), approved by the Head of Sales and the General Manager."),
			title=_("Outcome Needs Approval"),
		)
	if approved and doc.status == "Open":
		frappe.throw(_("The outcome of this bid was approved in {0}. Cancel that outcome report to reopen the bid.").format(outcome))


def is_submitted(doc) -> bool:
	return bool(doc.get("muhick_submitted_at") and doc.get("muhick_acknowledgement"))


def is_preparing(doc) -> bool:
	"""Work on the bid has started: a document made for it, or money requested for it."""
	return not doc.is_new() and any(
		frappe.db.exists(doctype, {"opportunity": doc.name, "docstatus": ("<", 2)})
		for doctype in ("Bid Document", "Sales Requisition", "Bid Security Request")
	)


def bid_status(doc) -> str:
	"""Where the bid stands, from what is recorded on it. Once its outcome report is approved the bid is
	won or lost for good, whatever happens to the sale afterwards."""
	outcome = doc.get("muhick_bid_outcome")
	if outcome:
		return frappe.db.get_value("Bid Outcome", outcome, "outcome") or "Won"
	if doc.status == "Lost":
		return "Lost"
	if doc.status == "Closed":
		return "Cancelled" if is_submitted(doc) else "Not Pursued"
	if not doc.is_new() and frappe.db.exists(
		"Bid Outcome", {"opportunity": doc.name, "docstatus": 0, "workflow_state": ("in", PENDING_STATES)}
	):
		return "Outcome Pending Approval"
	if is_submitted(doc):
		deadline = doc.get("muhick_submission_deadline")
		return "Under Evaluation" if deadline and get_datetime(deadline) < now_datetime() else "Submitted"
	return "In Preparation" if is_preparing(doc) else "Qualified"


def set_bid_status(doc):
	doc.sales_stage = bid_status(doc)
	if doc.has_value_changed("sales_stage") or not doc.get("muhick_stage_since"):
		doc.set("muhick_stage_since", today())


def set_milestones(doc):
	"""The opportunity's milestones, each carrying its weight: reached as the record shows (or ticked by
	hand), and its progress the weight reached out of the weight that applies. While the bid is going,
	its milestones and weights follow the Opportunity Milestones list."""
	if not doc.get("muhick_milestones") or doc.is_new() or doc.sales_stage in IN_PROGRESS:
		follow_milestone_list(doc)
	facts = milestone_facts(doc)
	# who reached a milestone: nobody is named for those found reached when the milestones were first drawn up
	who = None if frappe.flags.in_patch else frappe.session.user
	for row in doc.get("muhick_milestones"):
		if row.reached_when == BY_HAND:
			if row.status == "Reached":
				row.update({"reached_on": row.reached_on or today(), "reached_by": row.reached_by or who, "note": _("Ticked by hand")})
			else:
				row.update({"reached_on": None, "reached_by": None, "note": None})
			continue
		applies, reached_on, note = milestone_state(doc, row, facts)
		status = "Reached" if applies and reached_on else ("Pending" if applies else "Not Applicable")
		reached_by = (row.reached_by if row.status == "Reached" else who) if status == "Reached" else None
		row.update(
			{
				"status": status,
				"reached_on": reached_on if status == "Reached" else None,
				"reached_by": reached_by,
				"note": note if status == "Reached" else None,
			}
		)
	doc.set("muhick_progress", flt(calc.milestone_progress([(r.weight, r.status) for r in doc.get("muhick_milestones")]), 2))


def follow_milestone_list(doc):
	"""The milestones of the list, in its order and with its weights: one taken off the list (disabled or
	deleted) leaves the opportunity, a new one joins it, and those already reached keep their date."""
	milestones = frappe.get_all(
		"Opportunity Milestone", filters={"disabled": 0}, fields=["name", "weight", "reached_when"], order_by="sequence asc, name asc"
	)
	active = {m.name for m in milestones}
	kept = {row.milestone: row for row in doc.get("muhick_milestones") or [] if row.milestone in active}
	rows = []
	for m in milestones:
		row = kept.get(m.name) or frappe._dict(milestone=m.name, status="Pending")
		row.update({"weight": m.weight, "reached_when": m.reached_when})
		rows.append(row)
	doc.set("muhick_milestones", rows)
	for idx, row in enumerate(doc.get("muhick_milestones"), 1):
		row.idx = idx


def milestone_facts(doc) -> dict:
	"""What the milestones are read from, beyond the opportunity itself: the bid's requisitions and
	security, its outcome, and the quotation, sales order and handover that follow a win."""
	facts = frappe._dict(funds_issued_on=None, requisitions=False, security_issued_on=None)
	facts.outcome = frappe.db.get_value("Bid Outcome", doc.muhick_bid_outcome, "outcome") if doc.get("muhick_bid_outcome") else None
	facts.costs = "Cost" in requirement_kinds(doc.get("muhick_financial_requirements")).values()
	if not doc.is_new():
		issued = frappe.get_all(
			"Sales Requisition",
			filters={"opportunity": doc.name, "docstatus": 1, "status": ("in", FUNDS_OUT)},
			fields=["issued_on"],
			order_by="issued_on asc",
			limit=1,
		)
		facts.funds_issued_on = getdate(issued[0].issued_on) if issued and issued[0].issued_on else None
		facts.requisitions = bool(frappe.db.exists("Sales Requisition", {"opportunity": doc.name, "docstatus": ("<", 2)}))
		quotations = frappe.db.sql(
			"""
			select distinct quotation.name, quotation.transaction_date from `tabQuotation` quotation
			left join `tabQuotation Item` item on item.parent = quotation.name and item.prevdoc_doctype = 'Opportunity'
			where quotation.docstatus = 1 and (quotation.opportunity = %(name)s or item.prevdoc_docname = %(name)s)
			""",
			{"name": doc.name},
			as_dict=True,
		)
		if quotations:
			facts.quotation_on = min(getdate(q.transaction_date) for q in quotations)
			ordered = frappe.db.sql(
				"""
				select min(so.transaction_date) from `tabSales Order` so
				where so.docstatus = 1
					and so.name in (select parent from `tabSales Order Item` where prevdoc_docname in %(quotations)s)
				""",
				{"quotations": [q.name for q in quotations]},
			)[0][0]
			facts.sales_order_on = getdate(ordered) if ordered else None
		handed_over = frappe.db.get_value("Project Handover", {"opportunity": doc.name, "docstatus": 1}, "accepted_on")
		facts.handover_on = getdate(handed_over) if handed_over else None
	if doc.get("muhick_bid_security"):
		issued_on = frappe.db.get_value("Bank Instrument", doc.muhick_bid_security, "issue_date")
		facts.security_issued_on = getdate(issued_on or today())
	return facts


def milestone_state(doc, row, facts) -> tuple:
	"""(whether a milestone applies to the bid, the day it was reached or None, how)."""
	rule = row.reached_when
	kept = getdate(row.reached_on) if row.status == "Reached" and row.reached_on else None
	if rule == "Opportunity Opened":
		return True, getdate(doc.get("transaction_date") or today()), _("Opportunity opened")
	if rule == "Site Visit Done":
		visit = doc.get("muhick_site_visit_date")
		done = bool(visit) and getdate(visit) <= getdate(today())
		return bool(doc.get("muhick_site_visit_required")), getdate(visit) if done else None, _("Site visit on {0}").format(formatdate(visit))
	if rule == "Funds Issued":
		return bool(facts.costs or facts.requisitions), facts.funds_issued_on, _("Funds for the bid issued")
	if rule == "Bid Security Issued":
		return bool(doc.get("muhick_bid_security_required")), facts.security_issued_on, _("Bid security {0} issued").format(
			doc.get("muhick_bid_security")
		)
	if rule in PART_MILESTONES:
		ready = doc.get(PART_MILESTONES[rule])
		return True, (kept or getdate(today())) if ready else None, _("Every document of the part ready")
	if rule == "Bid Submitted":
		submitted = getdate(doc.muhick_submitted_at) if is_submitted(doc) else None
		return True, submitted, _("Submission recorded with its acknowledgement")
	if rule == "Submission Deadline Passed":
		deadline = doc.get("muhick_submission_deadline")
		passed = bool(deadline) and is_submitted(doc) and get_datetime(deadline) < now_datetime()
		return bool(deadline), getdate(deadline) if passed else None, _("Submission deadline passed")
	if rule in ("Outcome Approved", "Bid Won"):
		outcome = doc.get("muhick_bid_outcome")
		reached = outcome and (rule == "Outcome Approved" or facts.outcome == "Won")
		return True, getdate(doc.get("muhick_outcome_date") or today()) if reached else None, _("Outcome report {0} approved").format(outcome)
	if rule == "Quotation Submitted":
		return True, facts.quotation_on, _("Quotation submitted")
	if rule == "Sales Order Submitted":
		return True, facts.sales_order_on, _("Sales order submitted")
	if rule == "Project Handed Over":
		return True, facts.handover_on, _("Handover to projects accepted")
	return True, kept, None


def refresh_bid_status(opportunity):
	"""An opportunity's bid status and milestones after something recorded elsewhere: a document, a
	requisition and its funds, the bid security, its outcome report, a quotation, sales order or
	handover, or a date passing."""
	if not opportunity or not frappe.db.exists("Opportunity", opportunity):
		return
	doc = frappe.get_doc("Opportunity", opportunity)
	stored = {row.name: row.as_dict() for row in doc.get("muhick_milestones")}
	stage, progress = doc.sales_stage, flt(doc.get("muhick_progress"), 2)
	set_milestones(doc)
	kept = set()
	for row in doc.get("muhick_milestones"):
		if not row.name or row.name not in stored:
			row.db_insert()
		elif any(
			stored[row.name].get(f) != row.get(f) for f in ("idx", "weight", "reached_when", "status", "reached_on", "reached_by", "note")
		):
			row.db_update()
		kept.add(row.name)
	dropped = [name for name in stored if name not in kept]
	if dropped:
		frappe.db.delete("Opportunity Milestone Line", {"name": ("in", dropped)})
	values = {}
	new_stage = bid_status(doc)
	if new_stage != stage:
		values.update({"sales_stage": new_stage, "muhick_stage_since": today()})
	if flt(doc.muhick_progress) != progress:
		values["muhick_progress"] = doc.muhick_progress
	if values:
		doc.db_set(values, notify=True)


def refresh_bid_statuses():
	"""Daily: a submitted bid goes under evaluation once its submission deadline has passed, and the
	milestones that come with a date (a site visit, the deadline) are reached."""
	for name in frappe.get_all("Opportunity", filters={"sales_stage": ("in", IN_PROGRESS)}, pluck="name"):
		refresh_bid_status(name)


def requirement_kinds(rows, field="requirement_type") -> dict:
	"""{financial requirement type: its kind} for the types on these lines."""
	types = list({r.get(field) for r in rows or [] if r.get(field)})
	if not types:
		return {}
	return dict(frappe.get_all("Financial Requirement Type", filters={"name": ("in", types)}, fields=["name", "kind"], as_list=True))


def on_update_opportunity(doc, method=None):
	before = doc.get_doc_before_save()
	if is_submitted(doc) and not (before and is_submitted(before)):
		notify_roles(
			[HOS, GM],
			_("Bid {0} ({1}) was submitted on {2}{3}.").format(
				doc.name,
				doc.customer_name,
				format_datetime(doc.get("muhick_submitted_at")),
				f" ({_(doc.muhick_submission_mode)})" if doc.get("muhick_submission_mode") else "",
			),
			doc=doc,
			extra_users=[doc.opportunity_owner],
		)
	if doc.has_value_changed("status") and doc.status in ("Lost", "Closed"):
		request_security_cancellation(doc)


def refresh_from_sale(doc, method=None):
	"""A quotation or sales order submitted or cancelled: the opportunity's milestones follow."""
	for name in sale_opportunities(doc):
		refresh_bid_status(name)


def sale_opportunities(doc) -> set:
	"""The opportunities a quotation or a sales order comes from."""
	quotations = [doc.name] if doc.doctype == "Quotation" else list({i.prevdoc_docname for i in doc.items if i.prevdoc_docname})
	if not quotations:
		return set()
	names = set(frappe.get_all("Quotation", filters={"name": ("in", quotations), "opportunity": ("is", "set")}, pluck="opportunity"))
	names.update(
		frappe.get_all(
			"Quotation Item",
			filters={"parent": ("in", quotations), "prevdoc_doctype": "Opportunity", "prevdoc_docname": ("is", "set")},
			pluck="prevdoc_docname",
		)
	)
	return names


def quotation_cancelled(doc, method=None):
	"""A won bid's quotation cancelled: ERPNext puts the opportunity back to Open, but the bid was won."""
	opportunities = {i.prevdoc_docname for i in doc.items if i.prevdoc_doctype == "Opportunity" and i.prevdoc_docname}
	if doc.get("opportunity"):
		opportunities.add(doc.opportunity)
	for name in opportunities:
		bid = frappe.db.get_value("Opportunity", name, ["status", "muhick_bid_outcome"], as_dict=True)
		if bid and bid.status == "Open" and bid.muhick_bid_outcome:
			if frappe.db.get_value("Bid Outcome", bid.muhick_bid_outcome, "outcome") == "Won":
				frappe.db.set_value("Opportunity", name, "status", "Won")
	refresh_from_sale(doc)


def request_security_cancellation(doc):
	outcome = _(doc.status).lower()
	for security in frappe.get_all(
		"Bank Instrument",
		filters={"opportunity": doc.name, "instrument_type": "Bid Security", "status": ("in", SECURITY_RUNNING)},
		pluck="name",
	):
		frappe.db.set_value(
			"Bank Instrument", security, {"status": "Cancellation Requested", "closing_reason": _("Bid {0} was {1}.").format(doc.name, outcome)}
		)
		notify_roles(
			FINANCE_ROLES,
			_("Cancel bid security {0}: bid {1} ({2}) was {3}. The bank charges for it until it is cancelled.").format(
				security, doc.name, doc.customer_name, outcome
			),
			doc=frappe._dict(doctype="Bank Instrument", name=security),
		)


@frappe.whitelist()
def make_bid_outcome(source_name: str):
	"""The outcome report of a submitted bid, won or lost, for the Head of Sales and then the General
	Manager to approve. A won bid's BOQ comes priced at the lowest of its supplier quotations."""
	opportunity = frappe.get_doc("Opportunity", source_name)
	opportunity.check_permission("read")
	outcome = (frappe.flags.args or {}).get("outcome")
	doc = frappe.new_doc("Bid Outcome")
	doc.update({"opportunity": opportunity.name, "outcome": outcome if outcome in ("Won", "Lost") else None})
	doc.check_bid(opportunity)
	doc.prepare(opportunity)
	return doc


@frappe.whitelist()
def make_sales_requisition(source_name: str):
	"""Funds for preparing the bid on an opportunity, filled in from its financial requirements."""
	opportunity = frappe.get_doc("Opportunity", source_name)
	opportunity.check_permission("read")
	costs = bid_costs(opportunity)
	if not costs["items"]:
		frappe.msgprint(costs["note"], alert=True, indicator="orange")
	doc = frappe.new_doc("Sales Requisition")
	doc.update(
		{
			"opportunity": opportunity.name,
			"organisation": opportunity.customer_name,
			"company": opportunity.company,
			"required_by": costs["required_by"],
		}
	)
	for line in costs["items"]:
		doc.append("items", line)
	return doc


@frappe.whitelist()
def get_bid_costs(opportunity: str) -> dict:
	"""For a new sales requisition where the opportunity is picked: its cost lines and date."""
	doc = frappe.get_doc("Opportunity", opportunity)
	doc.check_permission("read")
	return bid_costs(doc)


def bid_costs(opportunity) -> dict:
	"""The cost lines of an opportunity's financial requirements, which a sales requisition pays,
	and the date the money is needed by: the site visit or, failing that, the submission deadline."""
	rows = opportunity.get("muhick_financial_requirements") or []
	kinds = requirement_kinds(rows)
	needed_by = opportunity.get("muhick_site_visit_date") or opportunity.get("muhick_submission_deadline")
	return {
		"items": [
			{"expense_type": r.requirement_type, "description": r.description, "amount": r.amount}
			for r in rows
			if kinds.get(r.requirement_type) == "Cost"
		],
		"required_by": getdate(needed_by) if needed_by else None,
		"note": _(
			"Opportunity {0} has no cost lines in its financial requirements. The bid security has a request of its own: "
			"Create > Bid Security Request on the opportunity."
		).format(opportunity.name),
	}


@frappe.whitelist()
def make_bid_security_request(source_name: str):
	"""The request for the bid security, from the Bid Security lines of the financial requirements,
	needed by the submission deadline. It goes to the Finance Manager for approval."""
	opportunity = frappe.get_doc("Opportunity", source_name)
	opportunity.check_permission("read")
	raised = frappe.db.get_value(
		"Bid Security Request", {"opportunity": opportunity.name, "docstatus": ("<", 2), "status": ("!=", "Rejected")}, "name"
	)
	if raised:
		frappe.throw(_("Bid security request {0} is already raised for this bid.").format(raised))
	rows = opportunity.get("muhick_financial_requirements") or []
	kinds = requirement_kinds(rows)
	deadline = opportunity.get("muhick_submission_deadline")
	doc = frappe.new_doc("Bid Security Request")
	doc.update(
		{
			"opportunity": opportunity.name,
			"organisation": opportunity.customer_name,
			"company": opportunity.company,
			"beneficiary": opportunity.customer_name,
			"required_by": getdate(deadline) if deadline else None,
		}
	)
	for r in rows:
		if kinds.get(r.requirement_type) == "Bid Security":
			doc.append("securities", {"security_type": r.requirement_type, "description": r.description, "amount": r.amount})
		elif kinds.get(r.requirement_type) == "Bid Security Expense":
			doc.append("expenses", {"expense_type": r.requirement_type, "description": r.description, "amount": r.amount})
	return doc
