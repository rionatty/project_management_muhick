"""Static checks for this app against the local frappe / erpnext / hrms sources.

Usage: python check.py <app_root> <frappe_bench_apps_dir>
Stands in for the checks a bench would run at install: nothing here needs a database.
"""

import ast
import glob
import importlib
import json
import os
import re
import sys
import types
from unittest import mock

APP, SRC = sys.argv[1], sys.argv[2]
PKG = "project_management_muhick"
errors, warnings = [], []


def err(msg):
	errors.append(msg)


def warn(msg):
	warnings.append(msg)


# ------------------------------------------------------------------ load doctypes
def load_doctypes(root):
	out = {}
	for path in glob.glob(os.path.join(root, "**", "doctype", "*", "*.json"), recursive=True):
		if os.path.basename(os.path.dirname(path)) + ".json" != os.path.basename(path):
			continue
		try:
			d = json.load(open(path, encoding="utf-8"))
		except Exception as e:  # noqa: BLE001
			err(f"bad json {path}: {e}")
			continue
		if d.get("doctype") == "DocType":
			d["__path"] = path
			out[d["name"]] = d
	return out


OURS = load_doctypes(os.path.join(APP, PKG))
STD = {}
for app in ("frappe", "erpnext", "hrms"):
	STD.update(load_doctypes(os.path.join(SRC, app, app)))
ALL = {**STD, **OURS}

NO_VALUE = {"Section Break", "Column Break", "Tab Break", "Attachment Gallery", "HTML", "Table", "Table MultiSelect", "Button", "Image", "Fold", "Heading"}
RESTRICTED = {"name", "parent", "creation", "owner", "modified", "modified_by", "parentfield", "parenttype", "file_list", "flags", "docstatus", "doctype", "idx"}
VALID_TYPES = {
	"Data", "Link", "Dynamic Link", "Select", "Check", "Currency", "Float", "Int", "Percent", "Date", "Datetime", "Time",
	"Small Text", "Text", "Text Editor", "Long Text", "Code", "Attach", "Attach Image", "Table", "Table MultiSelect", "Rating",
	"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Read Only", "Password", "Color", "Duration", "JSON",
}


def fields_of(doctype, with_custom=True):
	d = ALL[doctype]
	f = {x["fieldname"]: x for x in d["fields"]}
	if with_custom:
		for cf in CUSTOM.get(doctype, []):
			f[cf["fieldname"]] = cf
	return f


# ------------------------------------------------------------------ import app modules with a fake frappe
class _Fake(types.ModuleType):
	def __getattr__(self, name):
		if name.startswith("__") and name.endswith("__"):
			raise AttributeError(name)
		m = mock.MagicMock(name=f"{self.__name__}.{name}")
		setattr(self, name, m)
		return m


class _Finder:
	def find_spec(self, name, path=None, target=None):
		if name.split(".")[0] in ("frappe", "erpnext"):
			from importlib.machinery import ModuleSpec

			return ModuleSpec(name, self, is_package=True)
		return None

	def create_module(self, spec):
		m = _Fake(spec.name)
		m.__path__ = []
		return m

	def exec_module(self, module):
		if module.__name__ == "frappe":
			module._ = lambda s, *a, **k: s
			module.whitelist = lambda *a, **k: (lambda f: f)
			module._dict = dict
		if module.__name__ == "frappe.model.document":
			module.Document = type("Document", (), {})


sys.meta_path.insert(0, _Finder())
sys.path.insert(0, APP)

cf_mod = importlib.import_module(f"{PKG}.setup.custom_fields")
roles_mod = importlib.import_module(f"{PKG}.setup.roles")
wf_mod = importlib.import_module(f"{PKG}.setup.workflows")

CUSTOM = cf_mod.CUSTOM_FIELDS
STD_ROLES = {
	"System Manager", "Stock User", "Stock Manager", "Purchase User", "Purchase Manager", "Projects User", "Projects Manager",
	"Accounts User", "Accounts Manager", "Sales User", "Sales Manager", "Desk User", "Employee",
}
ROLES = set(roles_mod.ROLES) | STD_ROLES

# Select fields whose options a form script fills in (Frappe skips server validation of empty options)
DYNAMIC_SELECTS = set()
for _js in glob.glob(os.path.join(APP, PKG, "**", "*.js"), recursive=True):
	DYNAMIC_SELECTS |= set(re.findall(r"""(?:update_docfield_property|set_df_property)\(\s*["'](\w+)["']\s*,\s*["']options["']""", open(_js, encoding="utf-8").read()))

# ------------------------------------------------------------------ 1. doctype json
for name, d in OURS.items():
	flds = d["fields"]
	names = [f["fieldname"] for f in flds]
	if d["field_order"] != names:
		err(f"{name}: field_order differs from fields")
	if len(set(names)) != len(names):
		err(f"{name}: duplicate fieldnames")
	byname = {f["fieldname"]: f for f in flds}
	folder = os.path.basename(os.path.dirname(d["__path"]))
	if folder != name.lower().replace(" ", "_").replace("-", "_"):
		err(f"{name}: folder {folder} does not match the doctype name")
	for f in flds:
		fn, ft = f["fieldname"], f["fieldtype"]
		where = f"{name}.{fn}"
		if ft not in VALID_TYPES:
			err(f"{where}: unknown fieldtype {ft}")
		if not re.fullmatch(r"[a-z][a-z0-9_]*", fn) or len(fn) > 64:
			err(f"{where}: invalid fieldname")
		if fn in RESTRICTED:
			err(f"{where}: restricted fieldname")
		if ft in ("Link", "Table", "Table MultiSelect"):
			opt = f.get("options")
			if not opt or opt not in ALL:
				err(f"{where}: {ft} options '{opt}' is not a known doctype")
			elif ft == "Table" and not ALL[opt].get("istable"):
				err(f"{where}: Table options {opt} is not a child table")
			elif ft == "Link" and ALL[opt].get("istable"):
				err(f"{where}: Link to child table {opt}")
		if ft == "Dynamic Link" and f.get("options") not in byname:
			err(f"{where}: Dynamic Link options must be a field of the doctype")
		if ft == "Select" and not f.get("options") and f["fieldname"] not in DYNAMIC_SELECTS:
			err(f"{where}: Select without options (and no form script sets them)")
		if f.get("in_list_view") and ft in NO_VALUE:
			err(f"{where}: {ft} cannot be in list view")
		if f.get("reqd") and f.get("read_only") and not f.get("fetch_from") and not f.get("default"):
			warn(f"{where}: mandatory and read-only with no default or fetch")
		if f.get("fetch_from"):
			link, _, target = f["fetch_from"].partition(".")
			if link not in byname or byname[link]["fieldtype"] != "Link":
				err(f"{where}: fetch_from link field {link} missing")
			else:
				tdt = byname[link]["options"]
				if tdt in ALL and target not in fields_of(tdt) and target != "name":
					err(f"{where}: fetch_from target {tdt}.{target} does not exist")
		for key in ("depends_on", "mandatory_depends_on", "read_only_depends_on"):
			for ref in re.findall(r"doc\.([a-z_0-9]+)", f.get(key) or ""):
				if ref not in byname and ref != "docstatus":
					err(f"{where}: {key} refers to missing field {ref}")
		default = f.get("default")
		if ft == "Select" and default and default not in (f.get("options") or "").split("\n"):
			err(f"{where}: default '{default}' is not one of the options")
	for key in ("title_field",):
		if d.get(key) and d[key] not in byname:
			err(f"{name}: {key} {d[key]} missing")
	for sf in (d.get("search_fields") or "").split(","):
		if sf.strip() and sf.strip() not in byname:
			err(f"{name}: search field {sf} missing")
	if d.get("autoname") == "naming_series:" and "naming_series" not in byname:
		err(f"{name}: naming series field missing")
	if (d.get("autoname") or "").startswith("field:") and d["autoname"][6:] not in byname:
		err(f"{name}: autoname field missing")
	if d.get("is_submittable") and "amended_from" not in byname:
		err(f"{name}: submittable without amended_from")
	if d.get("istable") and d.get("permissions"):
		err(f"{name}: child table with permissions")
	if not d.get("istable") and not d.get("permissions"):
		err(f"{name}: no permissions")
	for p in d.get("permissions", []):
		if p["role"] not in ROLES:
			err(f"{name}: permission for unknown role {p['role']}")
		if (p.get("submit") or p.get("cancel") or p.get("amend")) and not d.get("is_submittable"):
			err(f"{name}: submit/cancel/amend permission on a non-submittable doctype")
	in_list = [f for f in flds if f.get("in_list_view")]
	if d.get("istable") and not in_list:
		warn(f"{name}: child table with no columns in the grid")
	if d.get("istable") and sum(int(f.get("columns") or 0) for f in in_list) > 12 and any(f.get("columns") for f in in_list):
		# frappe shows up to 10 grid columns by default; flag heavy tables
		tot = sum(int(f.get("columns") or 2) for f in in_list)
		warn(f"{name}: grid columns total {tot}")

# every child table we define is used
used_tables = {f["options"] for d in OURS.values() for f in d["fields"] if f["fieldtype"] == "Table"}
used_tables |= {cf["options"] for fl in CUSTOM.values() for cf in fl if cf.get("fieldtype") == "Table"}
for name, d in OURS.items():
	if d.get("istable") and name not in used_tables:
		err(f"{name}: child table is not used by any doctype")

# ------------------------------------------------------------------ 2. custom fields
for dt, fl in CUSTOM.items():
	if dt not in STD:
		err(f"custom fields: unknown doctype {dt}")
		continue
	existing = {x["fieldname"] for x in STD[dt]["fields"]}
	seen = set()
	for cf in fl:
		fn = cf["fieldname"]
		where = f"custom {dt}.{fn}"
		if not fn.startswith("muhick_"):
			err(f"{where}: missing muhick_ prefix")
		if fn in existing or fn in seen:
			err(f"{where}: duplicate fieldname")
		if cf.get("insert_after") not in existing | seen:
			err(f"{where}: insert_after {cf.get('insert_after')} does not exist")
		seen.add(fn)
		if cf["fieldtype"] not in VALID_TYPES:
			err(f"{where}: unknown fieldtype")
		if cf["fieldtype"] in ("Link", "Table") and cf.get("options") not in ALL:
			err(f"{where}: options {cf.get('options')} unknown")
		if cf["fieldtype"] not in ("Section Break", "Column Break", "Tab Break") and not cf.get("label"):
			err(f"{where}: no label")
		for key in ("depends_on", "mandatory_depends_on"):
			for ref in re.findall(r"doc\.([a-z_0-9]+)", cf.get(key) or ""):
				if ref not in existing | seen | {x["fieldname"] for x in fl}:
					err(f"{where}: {key} refers to missing field {ref}")

# ------------------------------------------------------------------ 3. controllers
DOC_ATTRS = {
	"name", "doctype", "docstatus", "owner", "creation", "modified", "modified_by", "idx", "flags", "meta", "parent",
	"get", "set", "append", "update", "save", "insert", "submit", "cancel", "delete", "reload", "db_set", "db_get",
	"is_new", "has_value_changed", "get_doc_before_save", "check_permission", "add_comment", "as_dict", "run_method",
	"db_insert", "db_update", "remove", "extend", "get_formatted", "notify_update", "has_permission", "precision",
}
# names defined by frappe's Document classes: a field with the same name would be rejected by frappe
frappe_doc_names = set()
for rel in ("frappe/frappe/model/document.py", "frappe/frappe/model/base_document.py"):
	tree = ast.parse(open(os.path.join(SRC, rel), encoding="utf-8").read())
	for node in ast.walk(tree):
		if isinstance(node, ast.ClassDef) and node.name in ("Document", "BaseDocument"):
			for item in node.body:
				if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
					frappe_doc_names.add(item.name)

for name, d in OURS.items():
	py = d["__path"][:-5] + ".py"
	if not os.path.exists(py):
		err(f"{name}: controller file missing")
		continue
	src = open(py, encoding="utf-8").read()
	tree = ast.parse(src)
	cls_name = name.replace(" ", "").replace("-", "")
	cls = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls_name), None)
	if not cls:
		err(f"{name}: class {cls_name} not found in controller")
		continue
	fields = fields_of(name)
	value_fields = {k for k, v in fields.items() if v["fieldtype"] not in NO_VALUE or v["fieldtype"] in ("Table", "Table MultiSelect")}
	methods = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
	for clash in (methods | frappe_doc_names) & set(fields):
		err(f"{name}: fieldname '{clash}' clashes with a controller / Document method")
	tables = {k: v["options"] for k, v in fields.items() if v["fieldtype"] == "Table"}
	for node in ast.walk(cls):
		if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
			a = node.attr
			if a not in value_fields and a not in methods and a not in DOC_ATTRS and not a.startswith("_"):
				err(f"{name}: self.{a} is not a field or method (line {node.lineno})")
		# self.get("x") / self.set("x", ...) / self.append("x", ...) / self.db_set("x", ...)
		if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "self":
			if node.func.attr in ("set", "append", "db_set") and node.args:
				a0 = node.args[0]
				keys = []
				if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
					keys = [a0.value]
				elif isinstance(a0, ast.Dict):
					keys = [k.value for k in a0.keys if isinstance(k, ast.Constant)]
				for k in keys:
					if k not in value_fields:
						err(f"{name}: self.{node.func.attr}('{k}') is not a field (line {node.lineno})")
				if node.func.attr == "append" and keys and keys[0] in tables and len(node.args) > 1 and isinstance(node.args[1], ast.Dict):
					child = fields_of(tables[keys[0]])
					for k in node.args[1].keys:
						if isinstance(k, ast.Constant) and k.value not in child:
							err(f"{name}: append('{keys[0]}') sets unknown child field {k.value} (line {node.lineno})")
		# for row in self.<table>: row.<attr>
		if isinstance(node, ast.For) and isinstance(node.target, ast.Name) and isinstance(node.iter, ast.Attribute):
			it = node.iter
			if isinstance(it.value, ast.Name) and it.value.id == "self" and it.attr in tables:
				child = fields_of(tables[it.attr])
				var = node.target.id
				for sub in ast.walk(node):
					if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) and sub.value.id == var:
						if sub.attr not in child and sub.attr not in DOC_ATTRS:
							err(f"{name}: {var}.{sub.attr} is not a field of {tables[it.attr]} (line {sub.lineno})")

# ------------------------------------------------------------------ 4. dotted paths in hooks
def resolve(path):
	mod, _, func = path.rpartition(".")
	file = os.path.join(APP, *mod.split(".")) + ".py"
	if not os.path.exists(file):
		return False
	tree = ast.parse(open(file, encoding="utf-8").read())
	return any(isinstance(n, (ast.FunctionDef, ast.Assign)) and (getattr(n, "name", None) == func or any(getattr(t, "id", None) == func for t in getattr(n, "targets", []))) for n in tree.body)


hooks_src = open(os.path.join(APP, PKG, "hooks.py"), encoding="utf-8").read()
ns = {}
exec(hooks_src, ns)  # noqa: S102
def _handlers(value):
	return list(value) if isinstance(value, (list, tuple)) else [value]


paths = set()
for dt, ev in ns["doc_events"].items():
	if dt not in ALL:
		err(f"hooks: doc_events for unknown doctype {dt}")
	for value in ev.values():
		paths |= set(_handlers(value))
for lst in ns["scheduler_events"].values():
	paths |= set(lst)
paths |= {ns["after_install"], ns["after_migrate"], *ns["override_doctype_dashboards"].values()}
for p in sorted(paths):
	if not resolve(p):
		err(f"hooks: {p} does not resolve to a function")
for dt, js in ns["doctype_js"].items():
	if not os.path.exists(os.path.join(APP, PKG, js)):
		err(f"hooks: doctype_js file missing for {dt}: {js}")
wf_dts = set(wf_mod.get_workflows())
TRACK = f"{PKG}.utils.approval.track"
for event in ("on_update", "on_submit", "on_cancel"):
	tracked = {dt for dt, ev in ns["doc_events"].items() if TRACK in _handlers(ev.get(event) or [])}
	if wf_dts != tracked:
		err(f"hooks: approval tracking on {event} differs from workflow doctypes: {sorted(wf_dts ^ tracked)}")

# patches listed in patches.txt are modules with an execute()
for line in open(os.path.join(APP, PKG, "patches.txt"), encoding="utf-8"):
	line = line.split("#")[0].strip()
	if line and not line.startswith("["):
		if not resolve(f"{line}.execute"):
			err(f"patches.txt: {line} has no execute()")

# ------------------------------------------------------------------ 5. workflows
for dt, (states, transitions) in wf_mod.get_workflows().items():
	flds = fields_of(dt)
	if dt in OURS and "workflow_state" not in flds:
		err(f"workflow {dt}: doctype has no workflow_state field")
	st = {}
	for s in states:
		st.setdefault(s["state"], s["doc_status"])
		if s["state"] not in wf_mod.STATE_STYLES:
			err(f"workflow {dt}: state {s['state']} not in STATE_STYLES")
		if s["allow_edit"] not in ROLES:
			err(f"workflow {dt}: unknown role {s['allow_edit']}")
	# document-level permissions only: a role may also have a separate field-level (permlevel) row
	perms = {p["role"]: p for p in ALL[dt].get("permissions", []) if not p.get("permlevel")}
	extra = roles_mod.STANDARD_DOCTYPE_PERMISSIONS.get(dt, {})
	for t in transitions:
		for key in ("state", "next_state"):
			if t[key] not in st:
				err(f"workflow {dt}: transition uses undefined state {t[key]}")
		if t["action"] not in wf_mod.ACTIONS:
			err(f"workflow {dt}: action {t['action']} not in ACTIONS")
		role = t["allowed"]
		if role not in ROLES:
			err(f"workflow {dt}: unknown role {role}")
		a, b = st.get(t["state"]), st.get(t["next_state"])
		if a == "1" and b == "0":
			err(f"workflow {dt}: submitted -> draft transition")
		if a == "0" and b == "2":
			err(f"workflow {dt}: draft -> cancelled transition")
		p = perms.get(role)
		ptypes = set(extra.get(role, ())) | ({k for k, v in p.items() if v == 1} if p else set())
		need = "write" if b == "0" else "submit" if (a == "0" and b == "1") else "cancel" if b == "2" else "write"
		if need not in ptypes:
			err(f"workflow {dt}: role {role} needs '{need}' permission for {t['state']} -> {t['next_state']}")
		for ref in re.findall(r"doc\.([a-z_0-9]+)", t.get("condition") or ""):
			if ref not in flds:
				err(f"workflow {dt}: condition refers to missing field {ref}")
	reachable = {t["next_state"] for t in transitions} | {states[0]["state"]}
	for s in st:
		if s not in reachable:
			err(f"workflow {dt}: state {s} is unreachable")
	for s in wf_mod.PENDING_STATES:
		pass
	for s, ds in st.items():
		if ds == "0" and s not in ("Draft",) and not any(t["state"] == s for t in transitions):
			err(f"workflow {dt}: no way out of state {s}")

# role profiles use known roles
for profile, rs in roles_mod.ROLE_PROFILES.items():
	for r in rs:
		if r not in ROLES:
			err(f"role profile {profile}: unknown role {r}")

# ------------------------------------------------------------------ 6. JS calls resolve
for js in glob.glob(os.path.join(APP, PKG, "**", "*.js"), recursive=True):
	src = open(js, encoding="utf-8").read()
	for p in set(re.findall(r"""["'](""" + PKG + r"""\.[A-Za-z0-9_.]+)["']""", src)):
		if not resolve(p):
			err(f"{os.path.relpath(js, APP)}: method {p} does not exist")
	if src.count("{") != src.count("}") or src.count("(") != src.count(")") or src.count("[") != src.count("]"):
		err(f"{os.path.relpath(js, APP)}: unbalanced brackets")

# ------------------------------------------------------------------ 7. database reads name real doctypes and fields
META_FIELDS = RESTRICTED | {"parent", "parenttype", "parentfield", "_assign", "_comments", "_liked_by", "_user_tags", "workflow_state"}
READERS = {"get_all": 0, "get_list": 0, "get_value": 0, "set_value": 0, "exists": 0, "count": 0, "get_cached_value": 0, "get_doc": 0, "get_cached_doc": 0, "new_doc": 0, "get_single_value": 0, "DocType": 0}
db_reads = unresolved = 0


def _const(node):
	return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _names(node):
	"""Fieldnames in a literal: 'a', ['a', 'b'], {'a': ...}, [['a', '=', 1]], [['Doctype', 'a', '=', 1]]."""
	if _const(node) is not None:
		return [_const(node)]
	if isinstance(node, ast.Dict):
		return [k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
	out = []
	if isinstance(node, (ast.List, ast.Tuple)):
		for el in node.elts:
			if _const(el) is not None:
				out.append(_const(el))
			elif isinstance(el, (ast.List, ast.Tuple)) and el.elts and _const(el.elts[0]) is not None:
				first = _const(el.elts[0])
				out.append(_const(el.elts[1]) if first in ALL and len(el.elts) > 3 and _const(el.elts[1]) else first)
	return out


def _column(node):
	"""Fieldname of a literal column dict."""
	if isinstance(node, ast.Dict):
		for k, v in zip(node.keys, node.values):
			if isinstance(k, ast.Constant) and k.value == "fieldname":
				return _const(v)
	return None


def _column_lists(tree):
	"""{variable: [(line, [fieldnames])]} for every `variable = [{"fieldname": ...}, ...]`."""
	out = {}
	for node in ast.walk(tree):
		if isinstance(node, ast.Assign) and isinstance(node.value, ast.List) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
			cols = [c for c in (_column(el) for el in node.value.elts) if c]
			if cols:
				out.setdefault(node.targets[0].id, []).append((node.lineno, cols))
	return out


def _from_columns(node, lists):
	"""Fieldnames of fields=[c["fieldname"] for c in columns if c["fieldname"] not in (...)]."""
	if not (isinstance(node, ast.ListComp) and len(node.generators) == 1 and isinstance(node.generators[0].iter, ast.Name)):
		return []
	gen = node.generators[0]
	earlier = [cols for line, cols in lists.get(gen.iter.id, []) if line < node.lineno]
	if not earlier:
		return []
	dropped = {c.value for cond in gen.ifs for c in ast.walk(cond) if isinstance(c, ast.Constant) and isinstance(c.value, str)}
	return [c for c in earlier[-1] if c not in dropped]


def _filter_variables(fn):
	"""{variable: keys} for filter dicts built up inside one function:
	x = {"a": 1}; x["b"] = 2; for f in ("c", "d"): x[f] = ..."""
	out = {}
	loops = {}
	for node in ast.walk(fn):
		if isinstance(node, ast.For) and isinstance(node.target, ast.Name) and isinstance(node.iter, (ast.Tuple, ast.List)):
			values = [_const(e) for e in node.iter.elts]
			if values and all(values):
				for sub in ast.walk(node):
					loops[id(sub)] = (node.target.id, values)
	for node in ast.walk(fn):
		if not isinstance(node, ast.Assign) or len(node.targets) != 1:
			continue
		target = node.targets[0]
		if isinstance(target, ast.Name) and isinstance(node.value, ast.Dict):
			out.setdefault(target.id, set()).update(_names(node.value))
		elif isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
			key = target.slice
			if _const(key) is not None:
				out.setdefault(target.value.id, set()).add(_const(key))
			elif isinstance(key, ast.Name) and id(node) in loops and loops[id(node)][0] == key.id:
				out.setdefault(target.value.id, set()).update(loops[id(node)][1])
	return out


def _plain(field):
	"""Strip an alias; skip expressions, joined columns and wildcards."""
	field = re.split(r"\s+as\s+", field.strip(), flags=re.I)[0].strip()
	return None if not field or re.search(r"[(`.*\s]", field) else field


def _check_fields(where, doctype, names):
	known = fields_of(doctype)
	for raw in names:
		f = _plain(raw)
		if f and f not in known and f not in META_FIELDS:
			err(f"{where}: {doctype} has no field '{f}'")


for py in glob.glob(os.path.join(APP, PKG, "**", "*.py"), recursive=True):
	rel = os.path.relpath(py, APP)
	tree = ast.parse(open(py, encoding="utf-8").read())
	column_lists = _column_lists(tree)
	filter_vars = {}
	for fn in ast.walk(tree):
		if isinstance(fn, ast.FunctionDef):
			keys = _filter_variables(fn)
			for sub in ast.walk(fn):
				filter_vars[id(sub)] = keys
	for node in ast.walk(tree):
		if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in READERS and node.args):
			continue
		base = node.func.value
		chain = []
		while isinstance(base, ast.Attribute):
			chain.append(base.attr)
			base = base.value
		if not (isinstance(base, ast.Name) and base.id == "frappe"):
			continue
		doctype = _const(node.args[0])
		if doctype is None:
			continue
		where = f"{rel}:{node.lineno}"
		if doctype not in ALL:
			err(f"{where}: unknown doctype '{doctype}'")
			continue
		db_reads += 1
		attr = node.func.attr
		kw = {k.arg: k.value for k in node.keywords if k.arg}
		if attr in ("get_all", "get_list"):
			for key in ("fields", "filters", "or_filters", "pluck"):
				if key in kw:
					_check_fields(where, doctype, _names(kw[key]) or _from_columns(kw[key], column_lists))
					unresolved += key == "fields" and not (_names(kw[key]) or _from_columns(kw[key], column_lists))
			for key in ("filters", "or_filters"):
				if isinstance(kw.get(key), ast.Name):
					_check_fields(where, doctype, sorted(filter_vars.get(id(node), {}).get(kw[key].id, ())))
			if "order_by" in kw and _const(kw["order_by"]):
				_check_fields(where, doctype, [re.sub(r"\s+(asc|desc)$", "", p.strip(), flags=re.I) for p in _const(kw["order_by"]).split(",")])
		elif attr in ("get_value", "get_cached_value", "set_value"):
			if len(node.args) > 1 and isinstance(node.args[1], ast.Dict):
				_check_fields(where, doctype, _names(node.args[1]))
			field_arg = node.args[2] if len(node.args) > 2 else kw.get("fieldname")
			if field_arg is not None:
				_check_fields(where, doctype, _names(field_arg))
		elif attr in ("exists", "count"):
			filt = node.args[1] if len(node.args) > 1 else kw.get("filters")
			if isinstance(filt, (ast.Dict, ast.List)):
				_check_fields(where, doctype, _names(filt))
		elif attr == "get_single_value":
			if not ALL[doctype].get("issingle"):
				err(f"{where}: {doctype} is not a single doctype")
			if len(node.args) > 1:
				_check_fields(where, doctype, _names(node.args[1]))

# ------------------------------------------------------------------ 8. reports
REPORTS = {}
for path in glob.glob(os.path.join(APP, PKG, "**", "report", "*", "*.json"), recursive=True):
	d = json.load(open(path, encoding="utf-8"))
	name, folder = d["name"], os.path.dirname(path)
	stem = os.path.basename(folder)
	REPORTS[name] = d
	if stem != name.lower().replace(" ", "_").replace("-", "_"):
		err(f"report {name}: folder {stem} does not match the report name")
	if d.get("ref_doctype") not in ALL:
		err(f"report {name}: unknown ref_doctype {d.get('ref_doctype')}")
	if d.get("report_type") != "Script Report" or d.get("is_standard") != "Yes":
		err(f"report {name}: expected a standard script report")
	module_dir = os.path.basename(os.path.dirname(os.path.dirname(folder)))
	if d.get("module", "").lower().replace(" ", "_") != module_dir:
		err(f"report {name}: module {d.get('module')} does not match folder {module_dir}")
	for r in d.get("roles", []):
		if r["role"] not in ROLES:
			err(f"report {name}: unknown role {r['role']}")
	py, js = os.path.join(folder, stem + ".py"), os.path.join(folder, stem + ".js")
	if not os.path.exists(py):
		err(f"report {name}: {stem}.py missing")
		continue
	tree = ast.parse(open(py, encoding="utf-8").read())
	if not any(isinstance(n, ast.FunctionDef) and n.name == "execute" for n in tree.body):
		err(f"report {name}: no execute()")
	for lst in ast.walk(tree):
		if isinstance(lst, ast.List):
			seen_cols = [c for c in (_column(el) for el in lst.elts) if c]
			for c in {c for c in seen_cols if seen_cols.count(c) > 1}:
				err(f"report {name}: column {c} is defined twice in one view")
	for node in ast.walk(tree):
		if isinstance(node, ast.Dict):
			item = {k.value: _const(v) for k, v in zip(node.keys, node.values) if isinstance(k, ast.Constant)}
			if "fieldname" in item and "fieldtype" in item:
				if item["fieldtype"] not in VALID_TYPES:
					err(f"report {name}: column {item['fieldname']} has unknown type {item['fieldtype']}")
				if item["fieldtype"] == "Link" and item.get("options") not in ALL:
					err(f"report {name}: column {item['fieldname']} links to unknown doctype {item.get('options')}")
	if os.path.exists(js):
		src = open(js, encoding="utf-8").read()
		if f'frappe.query_reports["{name}"]' not in src:
			err(f"report {name}: {stem}.js does not register frappe.query_reports[\"{name}\"]")
		for target in re.findall(r"""fieldtype:\s*["']Link["'],\s*options:\s*["']([^"']+)["']""", src):
			if target not in ALL:
				err(f"report {name}: filter links to unknown doctype {target}")

# ------------------------------------------------------------------ 9. desk: workspace, sidebar, number cards, charts, print formats
def _load(pattern):
	return [(p, json.load(open(p, encoding="utf-8"))) for p in glob.glob(os.path.join(APP, PKG, *pattern.split("/")), recursive=True)]


def _target_ok(kind, target):
	return target in (REPORTS if kind == "Report" else ALL)


CARDS = {d["name"]: d for _, d in _load("**/number_card/*/*.json")}
CHARTS = {d["name"]: d for _, d in _load("**/dashboard_chart/*/*.json")}
for name, d in CARDS.items():
	dt = d.get("document_type")
	if dt not in ALL:
		err(f"number card {name}: unknown doctype {dt}")
		continue
	for f in json.loads(d.get("filters_json") or "[]"):
		if f[0] != dt or (f[1] not in fields_of(dt) and f[1] not in META_FIELDS):
			err(f"number card {name}: filter on unknown field {f[0]}.{f[1]}")
		opts = (fields_of(dt).get(f[1]) or {}).get("options", "")
		if (fields_of(dt).get(f[1]) or {}).get("fieldtype") == "Select":
			for v in f[3] if isinstance(f[3], list) else [f[3]]:
				if v not in opts.split("\n"):
					err(f"number card {name}: '{v}' is not an option of {dt}.{f[1]}")
for name, d in CHARTS.items():
	dt = d.get("document_type")
	if dt not in ALL:
		err(f"chart {name}: unknown doctype {dt}")
		continue
	for key in ("based_on", "value_based_on", "group_by_based_on"):
		if d.get(key) and d[key] not in fields_of(dt) and d[key] not in META_FIELDS:
			err(f"chart {name}: {key} names unknown field {dt}.{d[key]}")
	for f in json.loads(d.get("filters_json") or "[]"):
		if f[1] not in fields_of(dt) and f[1] not in META_FIELDS:
			err(f"chart {name}: filter on unknown field {dt}.{f[1]}")
for path, d in _load("**/workspace/*/*.json"):
	ws = d["name"]
	labels = {"card": set(), "shortcut": {s["label"] for s in d.get("shortcuts", [])}}
	for l in d.get("links", []):
		if l["type"] == "Card Break":
			labels["card"].add(l["label"])
		elif not _target_ok(l["link_type"], l["link_to"]):
			err(f"workspace {ws}: link '{l['label']}' points to unknown {l['link_type']} {l['link_to']}")
		elif (l["link_type"] == "Report") != bool(l.get("is_query_report")):
			err(f"workspace {ws}: link '{l['label']}' has the wrong is_query_report flag")
	for s in d.get("shortcuts", []):
		if not _target_ok(s["type"], s["link_to"]):
			err(f"workspace {ws}: shortcut '{s['label']}' points to unknown {s['type']} {s['link_to']}")
	for c in d.get("number_cards", []):
		if c["number_card_name"] not in CARDS:
			err(f"workspace {ws}: unknown number card {c['number_card_name']}")
	for c in d.get("charts", []):
		if c["chart_name"] not in CHARTS:
			err(f"workspace {ws}: unknown chart {c['chart_name']}")
	for block in json.loads(d.get("content") or "[]"):
		data, kind = block.get("data", {}), block.get("type")
		if kind == "card" and data.get("card_name") not in labels["card"]:
			err(f"workspace {ws}: content shows card '{data.get('card_name')}' that has no links")
		if kind == "shortcut" and data.get("shortcut_name") not in labels["shortcut"]:
			err(f"workspace {ws}: content shows unknown shortcut '{data.get('shortcut_name')}'")
		if kind == "number_card" and data.get("number_card_name") not in {c["number_card_name"] for c in d.get("number_cards", [])}:
			err(f"workspace {ws}: content shows number card '{data.get('number_card_name')}' not listed on the workspace")
		if kind == "chart" and data.get("chart_name") not in {c["chart_name"] for c in d.get("charts", [])}:
			err(f"workspace {ws}: content shows chart '{data.get('chart_name')}' not listed on the workspace")
for path, d in _load("workspace_sidebar/*.json"):
	for item in d.get("items", []):
		if item["type"] == "Link" and item["link_type"] in ("DocType", "Report") and not _target_ok(item["link_type"], item["link_to"]):
			err(f"sidebar {d['name']}: '{item['label']}' points to unknown {item['link_type']} {item['link_to']}")
PRINT_FORMATS = _load("**/print_format/*/*.json")
for path, d in PRINT_FORMATS:
	if d.get("doc_type") not in ALL:
		err(f"print format {d['name']}: unknown doctype {d.get('doc_type')}")
	if d.get("module", "").lower().replace(" ", "_") != os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(path)))):
		err(f"print format {d['name']}: module does not match its folder")
	html = d.get("html") or ""
	for a, b in (("{%", "%}"), ("{{", "}}")):
		if html.count(a) != html.count(b):
			err(f"print format {d['name']}: unbalanced {a} {b}")
	for tag in ("if", "for", "macro"):
		if len(re.findall(r"{%-?\s*" + tag + r"\b", html)) != len(re.findall(r"{%-?\s*end" + tag + r"\b", html)):
			err(f"print format {d['name']}: unclosed {{% {tag} %}}")

# ------------------------------------------------------------------ 10. templates: tags nest, includes and imports resolve
BLOCKS = {"if": "endif", "for": "endfor", "macro": "endmacro", "call": "endcall", "filter": "endfilter", "block": "endblock"}
MIDDLE = {"elif": ("if",), "else": ("if", "for")}


def check_template(where, source):
	source = re.sub(r"{#.*?#}", "", source, flags=re.S)
	for a, b in (("{%", "%}"), ("{{", "}}")):
		if source.count(a) != source.count(b):
			err(f"{where}: unbalanced {a} {b}")
	stack = []
	for m in re.finditer(r"{%-?\s*(.*?)\s*-?%}", source, flags=re.S):
		body = m.group(1)
		word = body.split(None, 1)[0] if body else ""
		line = source.count("\n", 0, m.start()) + 1
		if word in BLOCKS or (word == "set" and "=" not in body):
			stack.append((word, line))
		elif word in MIDDLE:
			if not stack or stack[-1][0] not in MIDDLE[word]:
				err(f"{where}: {{% {word} %}} outside {' / '.join(MIDDLE[word])} (line {line})")
		elif word.startswith("end"):
			opener = "set" if word == "endset" else next((k for k, v in BLOCKS.items() if v == word), None)
			if not stack or stack[-1][0] != opener:
				err(f"{where}: {{% {word} %}} does not close the open block (line {line})")
			else:
				stack.pop()
		elif word in ("include", "from", "import", "extends"):
			target = re.search(r"""["']([^"']+)["']""", body)
			if not target:
				continue
			rel = target.group(1)
			app = rel.split("/")[0] if rel.split("/")[0] in (PKG, "frappe", "erpnext") else None
			candidates = (
				[os.path.join(APP, PKG, *rel.split("/")[1:])] if app == PKG
				else [os.path.join(SRC, app, app, *rel.split("/")[1:])] if app
				else [os.path.join(APP, PKG, *rel.split("/"))] + [os.path.join(SRC, a, a, *rel.split("/")) for a in ("frappe", "erpnext")]
			)
			found = next((c for c in candidates if os.path.exists(c)), None)
			if not found:
				err(f"{where}: {word} of missing template {rel} (line {line})")
			elif word == "from":
				other = open(found, encoding="utf-8").read()
				names = re.sub(r"\s+with(out)?\s+context\s*$", "", body.split(" import ", 1)[1])
				for macro in [n.strip().split(" as ")[0] for n in names.split(",")]:
					if not re.search(r"{%-?\s*macro\s+" + re.escape(macro) + r"\s*\(", other):
						err(f"{where}: {rel} has no macro {macro} (line {line})")
			elif word == "include" and app == PKG:
				check_template(rel, open(found, encoding="utf-8").read())
		elif word not in ("set", "do", "break", "continue", "raw", "endraw"):
			err(f"{where}: unknown tag {{% {word} %}} (line {line})")
	for word, line in stack:
		err(f"{where}: {{% {word} %}} opened on line {line} is never closed")
	# every macro called as {{ name(...) }} is defined or imported in the file
	defined = set(re.findall(r"{%-?\s*macro\s+(\w+)", source))
	for imp in re.findall(r"{%-?\s*from\s+\S+\s+import\s+(.*?)\s*-?%}", source, flags=re.S):
		defined |= {n.strip().split(" as ")[-1] for n in re.sub(r"\s+with(out)?\s+context\s*$", "", imp).split(",")}
	for call in set(re.findall(r"{{\s*(\w+)\(", source)) - defined - {"_"}:
		err(f"{where}: calls {call}() which is neither defined nor imported")


TEMPLATES = glob.glob(os.path.join(APP, PKG, "templates", "**", "*.html"), recursive=True)
for path in TEMPLATES:
	check_template(os.path.relpath(path, APP), open(path, encoding="utf-8").read())
for path, d in PRINT_FORMATS:
	check_template(f"print format {d['name']}", d.get("html") or "")
	if os.path.basename(os.path.dirname(path)) != d["name"].lower().replace(" ", "_").replace("-", "_"):
		err(f"print format {d['name']}: folder does not match the name")

# ------------------------------------------------------------------ 11. shipped records conform to their doctype
def conform(where, record, doctype=None):
	doctype = doctype or record.get("doctype")
	if doctype not in STD:
		err(f"{where}: record of unknown doctype {doctype}")
		return
	known = {f["fieldname"]: f for f in STD[doctype]["fields"]}
	for key, value in record.items():
		if key in META_FIELDS or key.startswith("__"):
			continue
		df = known.get(key)
		if df is None:
			err(f"{where}: {doctype} has no field '{key}'")
		elif df["fieldtype"] == "Select" and (df.get("options") or "").strip() and value not in ("", None) and str(value) not in (df.get("options") or "").split("\n"):
			err(f"{where}: '{value}' is not an option of {doctype}.{key}")
		elif df["fieldtype"] in ("Table", "Table MultiSelect") and isinstance(value, list):
			for row in value:
				conform(f"{where} > {key}", row, df["options"])
		elif df["fieldtype"] == "Check" and value not in (0, 1):
			err(f"{where}: {doctype}.{key} must be 0 or 1")
	for f in STD[doctype]["fields"]:
		if f.get("reqd") and f["fieldtype"] not in NO_VALUE and record.get(f["fieldname"]) in ("", None) and not f.get("default"):
			warn(f"{where}: mandatory {doctype}.{f['fieldname']} is empty")


RECORDS = (
	_load("**/number_card/*/*.json") + _load("**/dashboard_chart/*/*.json") + PRINT_FORMATS + _load("**/workspace/*/*.json")
	+ _load("workspace_sidebar/*.json") + _load("desktop_icon/*.json") + _load("**/report/*/*.json")
)
for path, d in RECORDS:
	conform(os.path.relpath(path, APP), d)

# ------------------------------------------------------------------ 12. imports resolve to real modules and names
_module_cache = {}


def _module_file(module):
	"""Path of the source file of a dotted module in this app or in frappe / erpnext / hrms."""
	parts = module.split(".")
	base = os.path.join(APP, *parts) if parts[0] == PKG else os.path.join(SRC, parts[0], *parts) if parts[0] in ("frappe", "erpnext", "hrms") else None
	if base is None:
		return None
	for candidate in (base + ".py", os.path.join(base, "__init__.py")):
		if os.path.exists(candidate):
			return candidate
	return ""


def _absolute(path, node):
	"""Dotted name of the module an ImportFrom in the file at `path` refers to."""
	module = node.module or ""
	if not node.level:
		return module
	root = APP if os.path.abspath(path).startswith(os.path.abspath(os.path.join(APP, PKG))) else None
	if root is None:
		for app in ("frappe", "erpnext", "hrms"):
			if os.path.abspath(path).startswith(os.path.abspath(os.path.join(SRC, app, app))):
				root = os.path.join(SRC, app)
	if root is None:
		return None
	package = os.path.relpath(os.path.dirname(path), root).replace(os.sep, ".").split(".")
	return ".".join([*package[: len(package) - node.level + 1], *([module] if module else [])])


def _module_names(path):
	"""(names defined at the top level, has a module __getattr__, star-imports something unknown)."""
	if path in _module_cache:
		return _module_cache[path]
	_module_cache[path] = (set(), False, False)  # guards against circular star imports
	names, dynamic, open_ended = set(), False, False

	def visit(body):
		nonlocal dynamic, open_ended
		for node in body:
			if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
				names.add(node.name)
				dynamic = dynamic or node.name == "__getattr__"
			elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
				for target in getattr(node, "targets", None) or [node.target]:
					for sub in ast.walk(target):
						if isinstance(sub, ast.Name):
							names.add(sub.id)
			elif isinstance(node, (ast.Import, ast.ImportFrom)):
				for alias in node.names:
					if alias.name == "*":
						# everything the other module defines comes along (not what its __getattr__ serves)
						source = _absolute(path, node)
						other = _module_file(source) if source else None
						if not other:
							open_ended = True
						else:
							inherited, _, other_open = _module_names(other)
							names.update(n for n in inherited if not n.startswith("_"))
							open_ended = open_ended or other_open
					names.add((alias.asname or alias.name).split(".")[0])
			elif isinstance(node, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
				for field in ("body", "orelse", "finalbody"):
					visit(getattr(node, field, []) or [])
				for handler in getattr(node, "handlers", []) or []:
					visit(handler.body)

	visit(ast.parse(open(path, encoding="utf-8").read()).body)
	_module_cache[path] = (names, dynamic, open_ended)
	return _module_cache[path]


def _top_level_names(path):
	"""Names importable from a module; None when that cannot be known."""
	names, dynamic, open_ended = _module_names(path)
	return None if dynamic or open_ended else names


imports_checked = 0
for py in glob.glob(os.path.join(APP, PKG, "**", "*.py"), recursive=True):
	rel = os.path.relpath(py, APP)
	package = os.path.relpath(os.path.dirname(py), APP).replace(os.sep, ".")
	for node in ast.walk(ast.parse(open(py, encoding="utf-8").read())):
		targets = []
		if isinstance(node, ast.Import):
			targets = [(alias.name, None) for alias in node.names]
		elif isinstance(node, ast.ImportFrom):
			module = node.module or ""
			if node.level:
				module = ".".join([*package.split(".")[: len(package.split(".")) - node.level + 1], *([module] if module else [])])
			targets = [(module, alias.name) for alias in node.names]
		for module, name in targets:
			path = _module_file(module)
			if path is None:
				continue  # standard library or a third-party package
			imports_checked += 1
			where = f"{rel}:{node.lineno}"
			if path == "":
				err(f"{where}: module {module} does not exist")
				continue
			if name in (None, "*"):
				continue
			if _module_file(f"{module}.{name}"):
				continue  # a submodule
			known = _top_level_names(path)
			if known is not None and name not in known:
				err(f"{where}: {module} has no name '{name}'")

# ------------------------------------------------------------------ report
print(f"{imports_checked} imports resolved")
print(f"{len(TEMPLATES)} templates, {len(RECORDS)} shipped records checked against their doctype")
print(f"{db_reads} database calls checked ({unresolved} with a field list built at run time), {len(REPORTS)} reports, {len(CARDS)} number cards, {len(CHARTS)} charts, {len(PRINT_FORMATS)} print formats")
print(f"{len(OURS)} app doctypes, {len(STD)} standard doctypes indexed, {sum(len(v) for v in CUSTOM.values())} custom fields, {len(wf_dts)} workflows")
for w in warnings:
	print("WARN ", w)
for e in errors:
	print("ERROR", e)
print(f"{len(errors)} errors, {len(warnings)} warnings")
sys.exit(1 if errors else 0)
