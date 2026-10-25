# Project Management Muhick

An ERPNext 16 add-on for an engineering contractor that runs its business project by project:
budgets and commitments, procurement with approvals, site stores, labour, subcontracts, claims
and certificates, retention, payments and the controls around them.

## What it adds

**Projects**

- Sales-to-project handover with a mandatory handover pack the Project Manager accepts or returns.
- The bid's BOQ is the opportunity's item table, each line an item with its stage (milestone), and
  the bid price is its total. The stage goes with the lines to the quotation and the sales order;
  the project's BOQ is created from the sales order's lines, and the activity plan can take its
  milestones, and the items each one needs, from the BOQ's stages.
- Bill of Quantities as a list of items from the Item master (stock or non-stock), each with its
  milestone and the quantities requested, purchased and consumed so far in the item's stock unit,
  kept current as requests, orders and issues are submitted. Variation order lines are items too.
- A project budget built by phase and cost code from Item-master items,
  taken from the activity plan's items or typed in.
- Commitments: approved purchase orders, subcontracts, requisitions and labour reduce the available
  budget at once, before anything is paid. Original Budget, Approved Variations, Current Budget and
  Forecast Final Cost are kept separately; an approved budget is changed only by a revision.
- Activity plan: each phase with its activities and the items it needs, a baseline, and revisions
  that state why the schedule moved. Phases and activities are standard ERPNext Tasks (a phase is a
  group task, its activities are child tasks), loaded from a Project Template or entered on the plan.
- Cash requisitions with accountability, weekly labour schedules and casual sheets.
- Subcontract RFQ and evaluation, agreement, and a service receipt note that gates the invoice.
- Claims that mirror the BOQ, the client's certificate, the invoice, retention and its release,
  variations, practical and full completion, the defects liability period and defects.
- Site reports, site meetings, a document register, equipment allocation and logs, warranties.

**Procurement and stores**

- Material Request raised per milestone ("Get Items from Milestone" loads what the plan still needs for it),
  routed by budget status and by type of request, with a stock check.
- Supplier selection approval, Procurement Requisition, Purchase Order and goods received note
  approvals, supplier onboarding, specification change requests, consignment tracking for imports.
- A site store per project; approvals for returns from site, disposals, deliveries and customer returns.

**Finance and controls**

- Weekly or monthly payment plan from which supplier payments are raised; expense claims refunded
  by journal entry.
- Bank facilities and the guarantees, bonds and letters of credit drawn on them, with expiry and
  quarterly fee reminders; funds lent between projects with approval.
- Three-way match (order, receipt, supplier invoice), segregation of duties on the purchase cycle,
  quarantine stock, approval limits by value, turnaround time per approval step with alerts, and a
  role and permission matrix.

**Sales and bids**

- A lead screen laid out for the business, where every lead is an organisation: the organisation,
  lead type (client, main contractor or consultant), sector, type of work, source and the sales
  engineer who runs it come first, then the client's requirements and the bid's financial
  requirements (bid security, bid documents, site visit and the like) as lines, the contact person
  and the go / no-go
  decision: the submission deadline, any site visit and the money needed, then Qualified or Not
  Pursued with the reason. Only the Head of Sales decides, and the lead records who decided and when.
- Only a qualified lead becomes an opportunity. The opportunity reads the same way and takes over the
  lead's details; its type of work and stages are the business's own (Qualified, In Preparation,
  Submitted, Under Evaluation, Awarded) in place of ERPNext's sample lists.
- The opportunity is the bid, built on the standard Opportunity: its Bid tab holds the tender, the
  client's requirements with a compliance answer for each (the technical bid check), the financial
  requirements, the three parts of the bid with their documents (each part ready once every document
  listed under it has its file), the submission record (date and time, mode, copies, who delivered it,
  who received it and the acknowledgement, which marks the bid Submitted and is flagged if late), the
  bid security and the outcome. The
  technical bid is ready only when every requirement is answered, and a bid is submitted only when
  all three parts are ready. Financial requirement types are a list sales can add to; each type's
  kind decides where its lines go: costs fill in the sales requisition (with the date the money is
  needed by), whether it is started from the opportunity or the opportunity is picked on it, the bid security line sets the bid security, and contract securities go to the
  handover; the project handover takes the requirements with
  any agreed deviations, the type of work and the securities the tender asks for. Follow-ups are the opportunity's own activities and comments; a lost
  bid is recorded with ERPNext's lost reasons and competitors, and Finance is asked to cancel its bid
  security. Create > Sales Requisition raises the funds for the bid. The Bid Register reports every
  bid with what was spent on it and why it was won or lost, and deadlines are reminded ahead of time.
  ERPNext's CRM menu lists the sales requisitions and the bid register.
- Sales requisitions for the cost of preparing a bid, paid through the payment plan: Issue Funds on the
  plan line (or on the requisition) records the money issued on both, with the date it must be
  accounted for by. As for project requisitions, a new one is refused only while an earlier one of
  the same person is past that date and still not accounted for.
- Bid security requests, raised from the opportunity with their securities and the expenses of
  obtaining them (one-off or recurring) as lines: the Finance Manager approves one (the General
  Manager is told) or rejects it with the reason, after which it is amended and sent again or left
  closed while the bid goes on. The Finance Manager chooses the bank facility the securities are drawn
  on and cannot approve them if they do not fit in what it has left (its limit, less the securities
  running on it and those approved but not yet issued). Once it is approved, Finance issues the funds
  from the payment plan or the request itself (the one-off
  expenses and the first payment of the recurring ones), then each security once the bank or insurer
  has issued it, with the recurring expenses as its quarterly fee. All of a lost bid's securities are
  put up for cancellation.
- Sale type on the Sales Order (Stock, Project, Additions): project and additions orders notify the
  Project Manager and start the handover.

**Administration**

- Fuel requisitions with odometer readings and consumption per vehicle, vehicle service requests,
  stationery issues, service contracts and a facility maintenance schedule with reminders.

**Reports, dashboard and printing**

- Twenty-two reports: budget position, portfolio, material consumption, procurement status, phase
  plan, proposed against certified valuations, retention, pending approvals, price trends,
  equipment history, subcontractor and freight forwarder performance, bid register, bank facility
  utilisation, resource envelope, payment plan execution, withholding tax register, fuel
  consumption and vehicle maintenance.
- A workspace with six number cards and two charts.
- An "Approval Form" print format for each of the 23 documents that are submitted: the document,
  the record of who approved it and when, and signature boxes. Pick it in the print view, or make
  it the default for a document in Customize Form.

## Verification status

**This app has not yet been installed or run on a bench.** It was written on a machine with no
bench, so what has been checked is:

- every Python file compiles;
- the unit tests of the business rules pass (`python project_management_muhick/tests/test_calc.py`);
- a static checker (`tools/static_check.py`) validates every doctype, controller, custom field,
  hook path, import, workflow, form script, report, database call, workspace link, number card,
  chart and print format against the ERPNext, Frappe and HRMS 16 source and reports no errors. The checker
  was itself tested by planting known mistakes.

That does not prove that install and migrate complete, that the forms behave as intended, or that
the reports return the right figures on real data. The print template has been checked for
structure only: it has never been rendered. Expect to fix issues on first install, then test
each process end to end.

## Requirements

- Frappe 16 and ERPNext 16 (Python 3.14, as Frappe 16 requires).
- HRMS is not required.

## Install

```bash
bench get-app /path/to/this/repository
```

```bash
bench --site your-site install-app project_management_muhick
```

```bash
bench --site your-site migrate
```

```bash
bench build --app project_management_muhick
```

Install creates the roles, role profiles, custom fields, approval workflows, starter cost codes,
labour trades, the handover checklist and the supplier onboarding requirements. It is safe to run
again: it only creates what is missing.

## Set up after install

1. **Muhick Settings**
   - Projects: parent warehouse for site stores (a group), central store, goods-in-transit warehouse.
   - Billing: the item used on certificate invoices, the item used on subcontract invoices, and the
     retention invoicing method (confirm with Finance).
   - Approvals: thresholds by value, allowed hours per approval step, escalation role.
   - Controls and Procurement and Payments: each control is Off, Warn or Block. They start on Warn.
   - "Project Managers Can Open Purchase Orders" is off at the start, so Project Managers do not
     see purchase prices on orders. It works on the whole document, not field by field.
   - Reminders: days of notice for bids, warranties and site reports. "Also Send Approval Alerts by
     SMS" needs an SMS gateway in SMS Settings and a mobile number on each user.
2. **Warehouses**: set Store Type on the central store, the transit warehouse and any quarantine store.
3. **Users**: assign each user one of the "Muhick ..." role profiles.
4. **Bank facilities**: enter each facility and its limit before recording instruments against it.
5. **Cost Codes**: review the starter list against the company's budget structure.
6. **Running projects at go-live**: enter the position before go-live on the project, its BOQ
   lines and its budget cost codes.

## Things to know

- **One projects icon.** The app's icon carries everything from ERPNext's own Projects workspace
  (timesheets, activity types and costs, project types, project updates, settings and the standard
  project reports), so ERPNext's Projects icon is hidden while the app is installed. It comes back
  if the app is uninstalled; the standard workspace is still at /desk/projects.

- **Milestones come from one shared list**, ERPNext's Task Type ("Milestones (Master List)" in the
  menu). BOQ lines and the activity plan pick from it; Get Milestones adds names it does not know.
- **Milestones (phases) are standard Tasks.** A milestone is a group task of the project and its
  activities are its child tasks, so the Task tree, Gantt chart and timesheets work as usual. Every
  project task must belong to a milestone (the Task field "Milestone / Phase"). A milestone's form
  shows its activities, the items the plan needs for it against what has been requested, its budget,
  and (under Connections) its material requests, stock entries, labour, requisitions and claims. Keep standard phase lists
  in Project Templates; "Get Milestones" on a new activity plan loads one. The plan sets each task's
  name, dates and weight (change them through a plan revision); progress on the activities rolls up
  to the phase and then to the project. Give items a Default Cost Code so budget lines fill it in.

- **Workflows belong to the site once created.** Change steps or roles in the Workflow screen;
  a later migrate will not overwrite them. To recreate them from code:
  `bench --site your-site execute project_management_muhick.setup.workflows.setup_workflows --kwargs "{'force': True}"`.
- **Standard documents get approval workflows**: Material Request, Supplier Quotation, Purchase
  Order, Purchase Receipt, Delivery Note and Stock Entry. A stock entry is submitted directly unless
  it is a return from a site store or a disposal. Documents that ERPNext submits by itself (for
  example automatic reorder requests) skip the approval steps.
- **Workflow emails are off** because they need an outgoing email account. Approvers get in-system
  notifications. Switch "Send Email Alert" on in each Workflow once email is configured.
- **Nobody can approve a document they raised.** The Administrator can, for support.
- **How the budget figures are defined**
  - Committed: approved purchase order lines at full value (a closed order counts what was received
    or billed), supplier invoices raised without an order, approved subcontracts, requisitions,
    casual sheets, expense claims, company equipment held by the project at its daily hire rate,
    and stock charged to the project from the company's own stores.
  - Actual: supplier invoices, accounted requisitions, casual sheets, expense claims and stock
    charged from the stores.
  - Available: Current Budget less Committed.
  - Forecast Final Cost: Committed plus the estimate to complete.
- **Material bought on a project's own purchase order** is committed by that order. Receive it into
  the project's site store, or send it on with "Delivery to Site" on the order, so the transfer is
  not charged to the budget a second time.

## Layout

```
project_management_muhick/
  hooks.py                 document events, scheduled jobs, form scripts
  install.py               after_install / after_migrate
  setup/                   roles, custom fields, workflows, starting data
  overrides/               hooks on standard ERPNext documents
  utils/calc.py            business rules with no framework dependency (unit tested)
  utils/approval.py        approval alerts, turnaround log, approval routes
  muhick_projects/         project documents, budget_engine.py, reports
  muhick_procurement/      requisition, shipments, specification changes, reports
  muhick_finance/          payment plan, expense claims, bank facilities, funds between projects
  muhick_sales/            bids, sales requisitions
  muhick_admin/            fuel, vehicle servicing, stationery, contracts, facility maintenance
  muhick_controls/         three-way match, segregation of duties, reports
  templates/print_formats/ the shared approval form layout
tools/static_check.py      development check; not loaded by the app
tools/build_desk.py        writes the workspace, sidebar, icons, number cards and charts
```

## Development checks

```bash
python project_management_muhick/tests/test_calc.py
```

```bash
python tools/static_check.py . /path/to/folder/containing/frappe-erpnext-hrms
```

The second argument is a folder holding source checkouts named `frappe`, `erpnext` and `hrms`.

## License

Proprietary. See `license.txt`.
