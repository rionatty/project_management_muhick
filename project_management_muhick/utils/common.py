# Copyright (c) 2026, CyveTech and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import fmt_money, get_url_to_form

PM = "Project Manager"
COO = "Chief Operating Officer"
FM = "Finance Manager"
GM = "General Manager"
FO = "Finance Officer"
PRM = "Procurement Manager"
PRO = "Procurement Officer"
SK = "Storekeeper"
SSK = "Site Storekeeper"
SE = "Sales Engineer"

FINANCE_ROLES = (FM, FO)


def get_settings():
	return frappe.get_cached_doc("Muhick Settings")


def setting(fieldname, default=None):
	value = get_settings().get(fieldname)
	return default if value in (None, "") else value


def user_has_any_role(*roles, user=None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return bool(set(roles) & set(frappe.get_roles(user)))


def require_roles(*roles):
	if not user_has_any_role(*roles, "System Manager"):
		frappe.throw(
			_("Only users with one of these roles can do this: {0}").format(", ".join(roles)),
			frappe.PermissionError,
		)


def users_with_roles(*roles) -> list[str]:
	from frappe.utils.user import get_users_with_role

	users = set()
	for role in roles:
		if role and frappe.db.exists("Role", role):
			users.update(get_users_with_role(role))
	users.discard("Administrator")
	users.discard("Guest")
	return sorted(users)


def notify(users, subject, doc=None, message=None):
	"""Bell notification (and email, where the user has it switched on) to a list of users."""
	users = [u for u in set(users or []) if u and u not in ("Administrator", "Guest")]
	if not users:
		return
	from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification

	log = {
		"type": "Alert",
		"subject": subject,
		"from_user": frappe.session.user,
		"email_content": message or subject,
	}
	if doc is not None:
		log.update({"document_type": doc.doctype, "document_name": doc.name})
	enqueue_create_notification(users, log)
	_send_sms(users, subject)


def _send_sms(users, message):
	"""Optional text message as well, for alerts that must reach a phone. Never blocks."""
	try:
		if not get_settings().get("send_sms_alerts") or not frappe.db.get_single_value("SMS Settings", "sms_gateway_url"):
			return
		numbers = [
			n
			for n in frappe.get_all("User", filters={"name": ("in", users), "enabled": 1}, pluck="mobile_no")
			if n
		]
		if numbers:
			from frappe.core.doctype.sms_settings.sms_settings import send_sms

			frappe.enqueue(send_sms, receiver_list=numbers, msg=message[:300], success_msg=False, enqueue_after_commit=True)
	except Exception:
		frappe.log_error(title="Muhick: SMS alert failed")


def notify_roles(roles, subject, doc=None, message=None, extra_users=None):
	if isinstance(roles, str):
		roles = [roles]
	notify(users_with_roles(*roles) + list(extra_users or []), subject, doc=doc, message=message)


def money(amount, company=None) -> str:
	currency = frappe.get_cached_value("Company", company, "default_currency") if company else None
	return fmt_money(amount, currency=currency)


def doc_link(doc) -> str:
	return f'<a href="{get_url_to_form(doc.doctype, doc.name)}">{doc.name}</a>'


def project_manager_of(project) -> str | None:
	return frappe.db.get_value("Project", project, "muhick_project_manager") if project else None


def project_stage(project) -> str | None:
	return frappe.db.get_value("Project", project, "muhick_stage") if project else None
