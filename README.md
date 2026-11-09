# Project Management Muhick

An ERPNext 16 add-on for an engineering contractor that runs its business project by project:
budgets and commitments, procurement with approvals, site stores, labour, subcontracts, claims
and certificates, retention, payments and the controls around them.

## What it adds

**Projects**

- Sales-to-project handover with a mandatory handover pack the Project Manager accepts or returns.
- The bid's BOQ is the opportunity's item table, each line an item with its stage (milestone), and
  the bid price is its total. Its lines are picked one by one, or loaded from the estimate's tabs with
  Get Lines from the Estimate on the BOQ tab: a line per item in each stage, the quantities of its
  estimate lines added up, ready for Set Bid Price. Lines with no item yet, and lines priced as a share
  of the contract value, stay out. The stage goes with the lines to the quotation and the sales order;
  the project's BOQ is created from the sales order's lines, and the activity plan can take its
  milestones, and the items each one needs, from the BOQ's stages.
- Bill of Quantities as a list of items from the Item master (stock or non-stock), each with its
  milestone and the quantities requested, purchased and consumed so far in the item's stock unit,
  kept current as requests, orders and issues are submitted. Variation order lines are items too.
- A bid's cost estimate on the opportunity, laid out sheet by sheet as the business's budget
  workbook, each sheet a tab: Equipment, Installation Materials, Taxes and Freight, Labour, Tools and
  Equipment, Preliminaries and Administrative, Budget Summary and Profitability (the tabs named as the
  workbook's sheets: Taxes, Tools & Equipment, Administrative). Each table has the
  columns of its sheet (system, description, brand, unit, people, qty, rate, amount as quoted,
  amount without VAT, supplier) and its sub totals by system under it. Every line's item or service
  (equipment, materials, labour, transport, commissions...) is picked from the item master and brings
  its name, unit, brand, default cost code and price (the bid's lowest supplier quotation, else the
  last purchase price). A cost code is optional on the estimate and suggested from the item, the
  description or the tab; on the project budget every line needs one. Its lines are those
  of the project budget: a stage from the shared milestone list (the system or phase it is for), its
  supplier, brand and cost code, its amount as quoted in its currency and its amount
  in the company's currency without VAT (people x qty x rate at the line's exchange rate, a rate
  quoted with VAT taken without it, or a share of the contract value).
- The tax computation of the imported goods, as the Taxes sheet: each good's total, insurance,
  customs value (C.I), import duty (ID), VAT, infrastructure levy (IL) and total tax, at its own
  rates (goods from the East African Community pay VAT only), with the freight and clearing lines,
  the total with freight (CFR) and what the imports cost the budget (insurance, duty, levy and
  freight; the VAT is claimed back). A good starts at the usual rates in Muhick Settings, or at those
  of the Item Tax Template on its item or item group, the one valid that day: a template line gives
  its own rate or marks the tax Not Applicable, and the settings name the account of each tax. A rate
  can still be changed on the row, and Apply Current Rates puts today's on an open bid. A line quoted
  with VAT keeps the VAT rate it was worked out at, so a later change of the rate leaves old bids as
  they are.
- Pricing the bid: Set Bid Price (under Cost Estimate) takes a target margin and works out the price as
  the cost divided by one less the margin, counting lines priced as a share of the contract value. It
  sets the BOQ's rates without VAT so the BOQ comes to that price, each line by its own cost in the
  estimate, the costs on no BOQ line and the margin spread in proportion; a line with no cost keeps
  its rate. With no BOQ it sets the Bid Price. Rates can still be changed by hand.
- The quotation goes out from the opportunity (Create > Quotation), once the BOQ has its rates: the
  client's copy prints as Muhick Quotation, its lines under their stages with VAT, the terms and the
  signatures, and Email to Client sends it with the print attached. The lead form no longer offers its
  own quotation, so every quote carries its bid's costs and margin.
- The Budget Summary tab (equipment and materials system by system with their suppliers, the origin,
  shipment and taxes of the imported ones, then taxes and freight, installation costs and overheads,
  the grand total, contract value, project cost and profit) and the Profitability tab (the contract
  value less each part without VAT, the margin and its percentage). The actions are under Cost
  Estimate at the top: lines from the BOQ, prices from the bid's supplier quotations, the imported
  goods into the tax computation, and Excel.
- Estimates and budgets prepared in Excel: Download Excel gives a sheet per section and the Tax
  Computation sheet, with the amounts worked out and lists to pick stages, cost codes, currencies,
  procurement types, countries and shipment from. Upload from Excel (.xlsx, .xls or .csv) also reads
  the business's own budget workbooks: each line into its tab by the sheet or the heading above it,
  the stage from the system headings (a misspelt one still finds its milestone, a new one is added to
  the list) or from a phase's sheet, the number of people from a labour sheet's No column, the
  currency from columns such as "Amount (USD)", rows copied in another sheet's layout checked
  against their own amount, each line linked to the item its description names, and the Taxes sheet
  good by good with its rates. Every row is checked
  first: with any mistake nothing changes and each one is listed by sheet and row.
- A project budget laid out like the bid's estimate, tab for tab: Equipment, Installation Materials,
  Taxes (the tax computation with Freight and Clearing), Labour, Tools & Equipment and Administrative,
  each with its sub totals, then Budget Summary (with each section against the stages), Profitability
  and Budget Position (the cost codes and totals). A budget starts from all its bid has: the estimate's
  lines tab by tab and its tax computation (or, with no estimate, the BOQ's items at what they cost), the
  contract value and the project's BOQ. When the project is handed over this becomes its draft budget,
  assigned to the Project Manager to adjust before approval, and a budget started by hand fills itself
  as soon as its project is picked. Under Budget Lines at the top, lines can also be uploaded from Excel,
  taken from the activity plan's items or the bid again, and typed in on their tab. Every line has a
  cost code. What the tax computation
  costs (its insurance, duty and levy) counts under the import cost code, stage by stage. A line takes
  the project's milestone of its stage once the activity plan creates it. The budget also has the
  Budget Summary print (sections against the stages and their months, contract value, margin, cost
  codes and signatures) and a cash plan by month. A purchase request is checked against its milestone's
  budgeted quantities, and one for items the budget places only in another milestone needs a
  justification. A budget's stages need not be named as the schedule's milestones: a stage named as one joins it
  by itself, and any other is linked with Budget Lines > Link Stages to Milestones, even on an approved budget,
  which changes no figure. Until then its lines count for every milestone, and the budget and the plan name it. Quantity counts like money: an item past its budgeted quantity is over budget however
  much its cost code has left, on the request, the procurement requisition, an order or an invoice with
  no request or order behind it. What an approved request covers is not asked again. Quantities are
  compared in the item's stock unit, and a budget revision can change one (also in the stock unit)
  without touching the budget's own lines.
- Commitments: approved purchase orders, subcontracts, requisitions and labour reduce the available
  budget at once, before anything is paid. Original Budget, Approved Variations, Current Budget and
  Forecast Final Cost are kept separately; an approved budget is changed only by a revision.
- Activity plan laid out as the business's activity schedule, in one outline: ID, task name, type,
  duration in working days (Monday to Friday), start, finish and predecessors written as scheduling
  tools write them (25,28 or 6SS or 25FS+2 days), with a bar for each row. Dates work themselves out from
  the durations and predecessors, and IDs and links follow when a row is moved or added; a start is typed
  only where neither a row nor a group above it has predecessors. A row is a subtask of the row whose ID
  it names as its Group Task ID, a row with subtasks is a group task, and Type on each row says which it
  is. The top rows are the milestones, past a row that only wraps them such as the project's name. All
  are standard ERPNext Tasks in the same tree, loaded from a Project Template, uploaded from Excel (also
  a scheduling tool's export; Schedule > Download Template gives an empty sheet, with an example and how
  to fill it in) or entered on the plan. Each milestone is a card, with + Add Subtask under
  each group; milestones and group tasks fold, and each subtask has a responsibility to filter by. Once
  approved, each milestone shows its tasks
  done and where it stands, on the plan and on the project, with the client's sign-off requested by email
  and its date recorded. The Milestones tab holds weights, valuations and claims, and Items Required what
  each milestone needs. The first approved dates stay as a baseline, and revisions state why the schedule
  moved.
- Cash requisitions with accountability, weekly labour schedules and casual sheets, paid from the weekly payment
  plan. Cash goes on the person's account until they account for it; see Finance and controls.
- Subcontract RFQ and evaluation, emailed or printed for the subcontractors with no budget or other bidders on it;
  agreement; a requisition for its advance, signed off by Finance and the General Manager and paid from the payment
  plan; and a service receipt note that gates the invoice, once its milestone is complete. The payment plan pays that
  invoice less its retention, until a Retention Release frees it, and less the advance it recovers.
- Claims that mirror the BOQ, the client's certificate, the invoice, retention and its release,
  variations, practical and full completion, the defects liability period and defects.
- Site reports, site meetings, a document register, equipment allocation and logs, warranties.
- A site report brings each milestone with its group tasks and subtasks, as on the schedule, and progress is entered on
  each task. What sits above a task adds up. Submitting moves the tasks it changed, with their status and the date they
  finished, and what they sit under follows; each task's timeline names the report, and cancelling it moves back those
  that have not moved since. A task cannot be reported finished before those it follows.

**Procurement and stores**

- Material Request raised per milestone ("Get Items from Milestone" loads what the plan lists for it and what
  the budget places in it, less what other requests ask for),
  routed by budget status and by type of request, with a stock check. Local and international procurement are
  for projects: a request with no project, for the company's own needs, goes the administration way whoever raises
  it.
- Supplier Evaluation, Procurement Requisition, Purchase Order and goods received note
  approvals, supplier onboarding, specification change requests, consignment tracking for imports.
- A goods received note and a purchase invoice name their Location, from ERPNext's Location list, which whoever handles goods
  or invoices can add to from the field, and their Consignment, found from the order. Location can still be changed once they
  are submitted. The consignment's Current Location follows, and its timeline keeps the trail.
- Supplier Quotation Comparison compares the quotations of one request for quotation, approved or not, as the supplier is
  chosen from it: each line requested with each supplier's rate and amount in the company's currency, the lowest marked,
  then each quotation's totals and terms. It takes the place of ERPNext's report of that name (install.py points the
  report at this app's module), so its links stay. Create > Supplier Evaluation starts the evaluation from it.
- Supplier Evaluation, one per request for quotation (Create on the request, or on the comparison): the quotations side by
  side, a supplier picked for each line with the lowest valid price picked to start with, or none. A price whose quotation has
  expired cannot be picked. Each supplier chosen needs its reason. What a supplier quoted beyond the request, its transport
  say, comes with it while it supplies any line. The Procurement Officer sends it to the Procurement Manager, who approves
  every choice at once; for an administration purchase the Administration Manager sends it to the General Manager.
  Approval approves the chosen quotations and marks the lines chosen on them. Quotations no longer go for approval one
  by one and need no justification of their own; a quotation must answer a request for quotation to be chosen.
- Procurement Report, one per material request (View on the request, or made when an evaluation of its items is
  approved): every item on one page, with the supplier chosen, rate and amount in the company's currency, lead time,
  validity and where it stands: Not Sent for Quotation, Sent for Quotation, Quotations Received, Under Evaluation, No
  Supplier Selected, Supplier Selected, On Requisition or Ordered. Then each supplier chosen with the reason, and lines
  for the officer and the Procurement Manager to sign. It is read afresh whenever it is opened or printed.
- The budget is checked on items at each step of procurement: material request, request for quotation, supplier
  quotation, requisition, order, goods received note and invoice each carry a Budget Status and Budget Check. Over a cost code
  or an item's quantity stops the requisition and the order, as Muhick Settings says. An item the budget does not hold, or
  priced above what it allows for one, is flagged for people to weigh on the evaluation, where each supplier chosen has
  its reason, and it stops the requisition and order only if the setting Item Not in the Budget or Priced Above It says
  Stop. A price alone does not lengthen the approval route. The budget's cost of an item is all its lines with approved
  revisions, per stock unit; what an approved request has covered is not counted twice. None of it prints.
- A Procurement Requisition is raised from the Procurement Report (Create on the report), for the items with a
  supplier chosen, whichever suppliers they are. Get Items From > Procurement Report adds other material
  requests, and Get Items From > Supplier Quotation adds quotations. It takes only lines chosen on an approved
  Supplier Evaluation, with what their suppliers quoted beyond the request, and the reasons fill its Basis of
  Supplier Selection. Each line keeps its source, its currency and, where it has one, its material
  request; a quotation's line goes on one open requisition only. The payment terms and one required mode of payment are the requisition's, and it
  prints on the business's requisition form with the way of paying ticked on every line. It shows each line
  against what was requested and budgeted. Create > Purchase Order raises one order per supplier, carrying
  the terms. An order with no approved requisition cannot go for approval (Muhick Settings can relax this).
  Create > Cost Control Sheet opens the budget revision already filled with the project, items, cost codes
  and shortfall; approving the sheet raises the budget, and the requisition then passes its check.
- An approved order is emailed to the supplier with the order attached. With no address on the order's
  contact or the supplier, or no outgoing email, the officer is told to print it. Muhick Settings can make
  it print only.
- An administration purchase, where every request behind a document is the company's own need with no project
  (Request From Administration, or a department's request with no project; the request shows Administration
  Purchase), takes its own route. The Finance Manager approves the request and the General Manager is told. The
  Administration Manager issues the request for quotation, records the quotations and sends the Supplier
  Evaluation to the General Manager, who decides it. The Procurement Officer raises the requisition, which goes to the Finance
  Manager and then the General Manager whatever its value. The Administration Manager then issues the order,
  any payment request and the goods received note with no further approval, and Finance is told of each
  payment request, receipt and invoice.
- An order says whether it is local or international, from its requisition. A payment term of Letter of
  Credit tells Finance to apply to the bank; Create > Letter of Credit on the order records it with the
  bank's other instruments, and the consignment reads it from there. The consignment holds the commercial
  invoice and packing list, and attaching the invoice tells Finance to book the reserve invoice (Create >
  Reserve Invoice). Its charges open as a Landed Cost Voucher on the goods received (Create > Landed Cost
  Voucher), less VAT and withholding tax, which the company claims back. Where the voucher's charges carry a
  Supplier (stock_addon adds one, and on submit makes each supplier's invoice), each charge takes its Payee, else
  the consignment's freight forwarder for freight and its clearing agent for the agent's fees. Those invoices
  are on the consignment and are not matched against an order.
- A site store per project; approvals for returns from site, disposals, deliveries and customer returns.

**Finance and controls**

- Cash given to a person, on a project requisition or a sales requisition, goes on their account: the Company's Staff
  Advance Account, with them as its party. Each requisition line is mapped to an expense account, from its cost code or
  type. The plan's journal entry pays their account from the line's bank and opens the accountability, with a line for each
  line requisitioned. They enter what each cost, with its receipt and the reason for any difference; Finance's verifying
  posts it to the expense accounts out of their account. If they spent less they return the rest (Record Balance Returned
  posts it back to the bank), and if they spent more the refund goes on the next plan. Their account ends at nothing, Staff
  Cash Held shows who holds what, and the Accountability Form prints it all for signing.
- Weekly or monthly payment plan from which supplier payments are raised; casual sheets, bid security requests and the
  bank fees of guarantees and bonds falling due are
  paid from it only, with a draft journal entry from the line's account to the expense account on each of the
  document's own lines, which marks the document paid when it is submitted. A line's account fills in from its
  Financial Requirement Type; a bank fee's is on its instrument. Expense claims are refunded by journal entry.
- The plan names itself from its type and period, and has a bank account to pay from, which each line can
  change. Its amounts are in the company's currency; an account in that currency can pay anything, and one in
  another currency only what is owed in that currency. The position shows what each account pays under the
  plan and what that leaves, in the account's own currency. A supplier on an
  approved requisition can be scheduled with Get > Approved Requisitions: the advance, or the whole amount on
  delivery. Raise Payments makes a draft Payment Entry from the line's account, against the approved order
  or, until there is one, on account, for no more than is still owed; either way an advance stays on the supplier's own payable account. A line whose document was paid by other
  means is closed as not executed, and one that cannot be raised is reported without stopping the others; Get
  leaves out payment requests whose invoice or order is paid. Once submitted the payment is linked on the line and carried along: the
  requisition shows what was paid, its order counts it, and the invoice takes it up as an advance.
- Bank facilities and the guarantees, bonds and letters of credit drawn on them, with expiry and
  quarterly fee reminders; funds lent between projects with approval.
- Three-way match (order, what was accepted on the receipt, supplier invoice; rejected goods are not
  owed), segregation of duties across supplier creation, receipt, invoice, payment and bank details,
  quarantine stock, client-owned stock (received at no value and kept apart from the company's),
  turnaround time per approval step with alerts, and a role and permission matrix. An import's reserve
  invoice reads Awaiting Goods until they arrive; any invoice on an order is matched again when goods are
  received against it, or a receipt is cancelled, and a hold it no longer needs comes off. Prices are
  compared in the order's own currency, so a change in the exchange rate is not a higher price. The
  invoices a landed cost voucher makes for its charges are not matched: they bill goods already received.
- Approval limits by value and risk on the Procurement Requisition, the Purchase Order, the Project
  Requisition, fuel and vehicle service: the table in Muhick Settings says how far up each one goes. A
  requisition's risk is chosen, and is high whatever was chosen for a single quotation, an advance payment
  or international procurement (each can be switched off). High risk takes the full route unless the table
  has a row for it, and so does anything over budget. Orders go to the Finance Manager, then the General
  Manager. A quotation in another currency is read in the company's for the budget and the limits.
- Only the Finance Manager changes bank details, and the General Manager hears of each change. The
  Procurement Manager holds the supplier and item lists.

**Sales and bids**

- A lead screen laid out for the business, where every lead is an organisation: the organisation,
  lead type (client, main contractor or consultant), sector, type of work, source and the sales
  engineer who runs it come first, then the client's requirements and the bid's financial
  requirements (bid security, bid documents, site visit and the like) as lines, the contact person
  and the go / no-go
  decision: the submission deadline, any site visit and the money needed, then Qualified or Not
  Pursued with the reason. Only the Head of Sales decides, and the lead records who decided and when.
- Only a qualified lead becomes an opportunity. The opportunity reads the same way and takes over the
  lead's details; its type of work is the business's own in place of ERPNext's sample list.
- Two statuses, each moving by itself. The Opportunity Status (ERPNext's own status) is where the sale
  stands: Open while it is pursued, Won once its outcome report is approved, then Quotation and
  Converted as the quotation and the sales order follow, or Lost or Closed. It is the tag at the top of
  the opportunity and on the list ("Replied" is not used: it would close an opportunity by itself after
  a few days). The Bid Status (ERPNext's Sales Stage) is where the tender stands: Qualified, In
  Preparation (a sales requisition, a bid security request or a document), Submitted (the submission
  with its acknowledgement), Under Evaluation (its deadline has passed), Outcome Pending Approval, then
  Won, Lost, Not Pursued or Cancelled (closed before or after it was submitted); a bid's approved
  outcome stays whatever happens to the sale afterwards. It opens the Bid tab with the expected award
  date.
- Follow-up after submission: each contact with the procuring entity or client is logged on the Bid tab
  (date, who was contacted, by whom, what was learned, the next step and the next follow-up date). The
  next follow-up is due on the date the latest follow-up gives, else some days after the submission
  (Muhick Settings). The sales engineer is reminded when it is due and every three days after; a bid
  worth at least the Big Bid Value is followed up with management, its follow-up three days overdue
  going to the Head of Sales and a week overdue to the General Manager. The Bid Register shows each
  bid's next follow-up.
- The opportunity's milestones, on its first tab, from the lead to the project, each carrying a weight
  from the Opportunity Milestones list (in the CRM menu's Setup): lead qualified, bid funds issued,
  site visit done, bid security issued, the three parts of the bid ready, bid submitted, bid won,
  quotation sent, sales order confirmed, handed over to projects. The business defines its own list
  (it says when the weights in use do not add up to 100%), which every new opportunity starts from;
  the opportunity's milestones are then its own: lines are added (a sales engineer can create a new
  stage from the line), deleted, reweighted and reordered for the tender, and Reset to the List brings
  them back to the list. Each is reached as the record shows, with the date and who, or is
  ticked by hand when it is one the system cannot see; one that does not apply (no site visit, no bid
  security) counts for nothing. The Progress % is the weight reached out of the weight that applies,
  on the opportunity, its list and the Bid Register.
- The opportunity is the bid, built on the standard Opportunity: its Bid tab holds the tender (with the
  site visit's report and findings), the client's requirements each with the item proposed from the
  item master, its brand and the manufacturer's data sheet checked against it, the compliance answer
  and, for a deviation, the date it was reported to the manufacturer (the technical bid check), the financial
  requirements, the three parts of the bid, its document checklist, the submission record (date and
  time, mode, copies, who delivered it, who received it and the acknowledgement, which marks the bid
  Submitted and is flagged if late), the bid security and the outcome. A bid is submitted only when
  all three parts are ready.
- Bid documents are tracked on the opportunity's document checklist, a line each: the document, its
  status (Pending, In Progress, Ready), who prepares it (the sales engineer unless someone else is
  given it), when it is needed by (the submission deadline unless an earlier date is set), its file,
  how long a licence or certificate is valid, and remarks. The checklist starts with the document
  types marked for every bid (and the bid security when the bid has one) and can be changed for the
  tender, and Add the Usual Documents puts back those marked for every bid. A part ticks itself as
  ready once every document of that part is ready (the technical part also once every requirement is
  answered with the data sheet of its proposed item, its deviations reported to the manufacturer, and a
  required site visit has its report). The top of a bid being prepared shows the documents
  overdue, not started and in progress, and whoever prepares a document is reminded as its date comes
  up. A document is ready only with its file, and a licence or certificate only if it is still valid
  on the submission deadline. Financial requirement types are a list sales can add to; each type's
  kind decides where its lines go: costs fill in the sales requisition (with the date the money is
  needed by), whether it is started from the opportunity or the opportunity is picked on it, the bid security line sets the bid security, and contract securities go to the
  handover; the project handover takes the requirements with
  any agreed deviations, the type of work and the securities the tender asks for. Create > Sales
  Requisition raises the funds for the bid. The opportunity's list shows each bid's status,
  progress, deadline, price and margin, and the Bid Budget print gives its budget summary and
  profitability as the workbook lays them out, with the Sales, Finance and Management signatures. The
  Bid Register reports every bid with its status and
  how long it has been in it, its margin at bid and at award, what was spent on it, the project it
  became and why it was won or lost, and deadlines are reminded ahead of time. ERPNext's CRM menu
  lists the sales requisitions, bid security requests, outcome reports, the bid register and the bid
  margin comparison.
- Won and lost are reported with an outcome report (Outcome > Won or Lost on the opportunity), which
  the Head of Sales and then the General Manager approve; only then is the bid marked won or lost,
  and cancelling an approved outcome reopens it. A won bid's report reviews the margin: its BOQ priced
  at the suppliers' latest quotations for the bid (asked for from the opportunity with ERPNext's
  request for quotation), the lowest by default and any other on a line, less what was spent on the bid,
  set against the margin at bid. Not every line needs a supplier: one with no quotation takes what the bid's
  estimate has it costing, else the last purchase price, and Cost From says which; a line with no cost at
  all does not stop the report, and a banner says the margin counts it in full. The
  Bid Margin Comparison report puts every supplier's price for each BOQ line side by side. A lost bid's
  report gives ERPNext's lost reasons and competitors and who won it at what price, and Finance is
  asked to cancel its bid security.
- What winning a bid cost (its sales requisitions, the funds for its bid security and that security's
  later quarterly fees) goes to the cost of the project made from it: the project budget counts it
  under the cost code set in Muhick Settings (ADM-600, Cost of Winning the Bid), and the handover
  shows the amount.
- Sales requisitions for the cost of preparing a bid, paid through the weekly payment plan only: the
  journal entry raised from its approved plan line records the money issued, with the date it must be accounted for
  by, and the requisition shows the plan it is on. As for project requisitions, a new one is refused only while an earlier one,
  of the same person or given to them, for a project or a bid, is past that date and still not accounted for.
- Bid security requests, raised from the opportunity with their securities and the expenses of
  obtaining them (one-off or recurring) as lines: the Finance Manager approves one (the General
  Manager is told) or rejects it with the reason, after which it is amended and sent again or left
  closed while the bid goes on. The Finance Manager chooses the bank facility the securities are drawn
  on and cannot approve them if they do not fit in what it has left (its limit, less the securities
  running on it and those approved but not yet issued). Once it is approved, its funds (the one-off
  expenses and the first payment of the recurring ones) go on the weekly payment plan and are issued
  from there, and the request shows the plan it is on; Finance then records each security once the
  bank or insurer has issued it, with the recurring expenses as its quarterly fee, which the payment
  plan picks up as it falls due (Get > Bank Fees Due). A request with no expenses needs no
  funds: its securities are recorded straight after approval. All of a lost bid's securities are put
  up for cancellation.
- Sale type on the Sales Order (Stock, Project, Additions), compulsory and correctable after the order
  is submitted: project and additions orders notify the Project Manager and start the handover, from
  Create > Project Handover. The handover finds the bid through the order's quotation.

**Administration**

- Fuel requisitions with odometer readings and consumption per vehicle, vehicle service requests,
  stationery issues, service contracts and a facility maintenance schedule with reminders.

**Reports, dashboard and printing**

- Twenty-nine reports: staff cash held, budget position, budget cash plan, project accountability, portfolio, material consumption, procurement status, phase
  plan, proposed against certified valuations, retention, pending approvals, price trends,
  equipment history, subcontractor and freight forwarder performance, bid register, bid margin comparison, bank facility
  utilisation, resource envelope, funds needed by project, project funds statement, resource allocation register,
  payment plan execution, withholding tax register, fuel
  consumption and vehicle maintenance.
- Project Accountability takes one project requisition by requisition: what was budgeted and requisitioned, given and
  spent, the balance and who owes it, a purchase's LPO, delivery and invoice side by side, and where each stands.
- Funds are told project by project from the postings on the bank and cash accounts, so they add up to what the banks
  hold. Resource Envelope shows each project's money, by account if wanted, Funds Needed by Project what each needs
  month by month against what it has, Project Funds Statement every movement of one project's money, and Resource
  Allocation Register what has moved between projects and is still to refund. A Resource Allocation is prepared by
  Finance or the department in need and approved by the General Manager; when the project that owes is paid, or its
  refund date passes, Finance is told.
- A Resource Allocation names the bank account the money is in and the one it goes to, and shows what each project holds
  in each bank. It cannot go for approval for more than the project holds in that bank. Its amount is in that bank's
  currency, with a rate where one is needed, and project figures stay in the company's currency. In the same bank the
  money only changes hands between the projects and nothing posts; to another bank, approval raises a draft internal
  transfer for Finance to complete, and the allocation reads Awaiting Transfer until they do. A refund works the same
  way back. Allocations made before this count in the projects' totals only, as their bank is not known.
- A project's Connections tab lists every document of the project in the order the work goes, from the bid to
  completion, and its Lifecycle section links the bid, quotation, handover, BOQ, budget and activity plan.
- Every table in the desk with more columns than the page has room for scrolls sideways, with a bar always in sight
  and each column wide enough to read an amount in full.
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
   - Approvals: limits by value and risk, allowed hours per approval step, escalation role.
   - Controls and Procurement and Payments: each control is Off, Warn or Block. They start on Warn.
   - On the Company, set Staff Advance Account. Give each person who takes cash an Employee record, with their user on it.
   - Procurement and Payments: Approved Purchase Order to the Supplier is Email or Print Only. Email goes
     to real addresses as soon as outgoing email is set up, so use Print Only while testing with real
     suppliers.
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
- **No notes from other apps.** Descriptions that other apps on the site put on their fields about
  things the business does not use (such as the Sales Pro mobile app) are blanked on every migrate
  (`FOREIGN_DESCRIPTIONS` in `setup/custom_fields.py`).
- **One colour for the buttons.** On every document, standard ones included, the buttons a form adds
  to its header (Create, View and the other groups, Close, Raise Payments and so on) have the colour of
  its Save button (`public/js/muhick_common.bundle.js`).

- **Milestones come from one shared list**, ERPNext's Task Type ("Milestones (Master List)" in the
  menu). BOQ lines and the activity plan pick from it; Get Milestones adds names it does not know.
- **Milestones (phases) are standard Tasks.** A milestone is a top-level group task of the project, a
  section a group task under it and an activity a task under either, at any depth, so the Task tree,
  Gantt chart and timesheets work as usual. Every
  project task must belong to a milestone (the Task field "Milestone / Phase"). A milestone's form
  shows its activities, the items the plan needs for it against what has been requested, its budget,
  and (under Connections) its material requests, stock entries, labour, requisitions and claims. Keep standard phase lists
  in Project Templates; "Get Milestones" on a new activity plan loads one. The plan sets each task's
  name, dates and weight (change them through a plan revision); progress on the activities rolls up
  through their sections to the milestone and then to the project, a longer activity counting for more
  unless it is given a weight. Give items a Default Cost Code so budget lines fill it in.

- **Workflows belong to the site once created.** Change steps or roles in the Workflow screen;
  a later migrate will not overwrite them. To recreate them from code:
  `bench --site your-site execute project_management_muhick.setup.workflows.setup_workflows --kwargs "{'force': True}"`.
- **Standard documents get approval workflows**: Material Request, Purchase Order, Purchase
  Receipt, Delivery Note and Stock Entry. Supplier quotations are approved through the Supplier Evaluation. A stock entry is submitted directly unless
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
  muhick_finance/          payment plan, expense claims, bank facilities, resource allocation, funds.py
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
