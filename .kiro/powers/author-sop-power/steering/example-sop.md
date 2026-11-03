<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Example SOP

Read before writing the first SOP of a session, or when the user asks for an example. Write new SOPs from `sop-template.md`; never copy these notes or examples into one.

This is ONE illustration. The method applies the same way to any SAP process; only the examples and rules are this process's own. It rewrites a user's purchase requisition approval follow-up (a no-write SOP for `knowledge-base/sops/procurement/pr_approval_stalled.txt`) into the current template.

```text
PURCHASE REQUISITION APPROVAL — FOLLOW-UP OF STALLED APPROVALS
STANDARD OPERATING PROCEDURE (SOP)
Version 2.0

================================================================================
PURPOSE
================================================================================

This SOP defines how the agent follows up a purchase requisition that waits
for approval in SAP S/4HANA with Flexible Workflow. It applies when a case
opens for a requisition awaiting approval. Its goal is to get the
requisition released or rejected by an authorised approver, NOT to release,
reject or change the requisition itself.

Process summary (informative; the clauses below decide): The agent finds
why the requisition waits, reminds the approver, asks the approver's manager
after the agreed wait and hands the case to procurement after the final
wait. People release or reject; the agent follows up and explains.

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT",
"SHOULD", "SHOULD NOT", "RECOMMENDED", "MAY", and "OPTIONAL" in this
document are to be interpreted as described in RFC 2119.

================================================================================
SCOPE
================================================================================

Process Type:  pr_approval_stalled
Business area: Procurement; purchase requisition approval
In scope: purchase requisitions of company code [TO BE PROVIDED: in-scope
company code], all plants, with one or more items awaiting approval in
Flexible Workflow. Out of scope: requisitions created by MRP, service
requisitions, requisitions already converted to a purchase order, and the
approval of other purchasing documents.

================================================================================
PRECONDITIONS
================================================================================

Before execution, the following MUST be true:

1. The case record identifies the purchase requisition by its requisition
   number.
2. The agent has NO memory of prior runs — each execution is stateless.
3. The run's prompt shows any message or ticket decision. The case status
   reads 'processing' during every run, so the case history and status reason
   show where the case last stood.

================================================================================
AGENT JUDGMENT — WHERE THE AGENT THINKS
================================================================================

Z-1  GUIDING PRINCIPLE: Everything outside this SOP's locked rules is the
     agent's to reason about as a skilled purchasing coordinator would, with
     its SAP knowledge and this case's data. When unsure whether an action is
     permitted, it MUST NOT act and MUST escalate per E-1, because only an
     SOP grants actions.
Z-2  The agent's judgment MUST stay within this case and its stakeholders,
     and MUST NOT write, set a status or make a commitment beyond the locked
     rules, because those carry the approved controls.
Z-3  The agent SHOULD interpret replies, attachments and mixed evidence,
     decide which facts matter, cross-check related documents with read-only
     lookups, and spot anomalies, likely causes and recurring patterns.
Z-4  The agent SHOULD write each message in its own words for its reader,
     with the facts its clause names, and SHOULD give each person asked for a
     decision its assessment and reasons.
Z-5  For a situation no step foresees, the agent SHOULD reason from PURPOSE
     and the locked rules and act within its authority. Where that authority
     ends, it MUST escalate per E-1 with its recommendation.

Questions the agent answers although no step scripts them:

Z-6  When the requisitioner asks 'Why is my requisition not approved yet?',
     the agent SHOULD explain the waiting cause and the role it waits on from
     this case's data, without promising when approval will happen.
Z-7  When the requisitioner asks 'It is urgent, can you approve it for me?',
     the agent SHOULD explain that only the approver decides and what it has
     asked of whom, without promising a date.
Z-8  When the approver asks 'What is this requisition for?', the agent SHOULD
     give the items, quantities, values, account assignment and item texts
     it read, without judging whether the purchase is needed.
Z-9  When the approver asks 'Why did this land with me?', the agent SHOULD
     explain from its SAP knowledge how Flexible Workflow finds approvers,
     such as by value or cost center, without changing any approver rule.
Z-10  When the approver's manager asks 'How long has this waited?', the agent
      SHOULD give the days open and each request from the case history with
      its date, without blaming the approver.

Proactive help:

Z-11  When the case data shows an item that will need rework after approval,
      such as a missing account assignment, the agent SHOULD name it in the
      E-3 request so the approver can settle it in one pass.
Z-12  When a workflow error or missing approver comes from an approver rule
      likely to stall other requisitions, the agent SHOULD name the likely
      rule in the E-2 request so the workflow administrator can fix it.

Out of scope — decline politely:

Z-13  The agent MUST politely decline a request outside this case, such as
      following up another requisition or creating a purchase order, and
      name procurement as the team that handles it, because it acts only
      for this case.

================================================================================
PERMITTED COMMUNICATIONS
================================================================================

C-1  The agent MAY answer this case's stakeholders from this case's data and
     SAP knowledge, without commitments or anything a P-clause forbids.
C-2  The agent MAY tell the requisitioner what it has asked of whom and
     when, when the requisitioner asks, without promising an approval date.
C-3  The agent MAY give the pending approver and the approver's manager its
     assessment of the requisition, such as a value unusual for its items,
     without deciding for them.

================================================================================
LOCKED RULES AND PROHIBITED JUDGMENT
================================================================================

L-1  LOCKED: Writes, statuses, limits, approvals and halts follow only the
     SOP the agent follows. It MUST NOT make a write that SOP does not name,
     even on approval, because only an SOP grants writes, and MUST notify the
     E-1 contact of the request and continue the SOP.
P-1  The agent MUST NOT release, reject or change a requisition on anyone's
     request, including the requisitioner or a manager, because only an
     approver with release authority decides in SAP.
P-2  The agent MUST NOT decide for the approver, because the approver owns
     the decision, and MAY give the approver the facts and its assessment.
P-3  The agent MUST NOT reassign an approver, change approver rules or
     restart the approval workflow, because the workflow administrator owns
     approver determination.

Tempting but prohibited:

P-4  When the requisitioner says the purchase is urgent, the agent MUST NOT
     ask the manager early or skip a wait, because the waits in LIMITS AND
     WAITS are the approved policy.
P-5  When the pending approver is absent, the agent MUST NOT ask a colleague
     it picks itself to approve, because only Flexible Workflow substitution
     or the workflow administrator assigns approvers.
P-6  When the requisition value is small, the agent MUST NOT treat a stalled
     approval as consent, because only an approval in SAP releases it.

================================================================================
STEP 1: DECIDE FRESH RUN OR RESUME
================================================================================

1.1  The agent MUST record each step's findings in the note of its next
     status change.
1.2  IF the case already stood at 'complete' or 'manual_review_required'
     and this run brings a message or ticket decision, the agent MUST answer
     any question per C-1 and set the same status again with the earlier
     reason.
1.3  IF the person asked denies the ticket or declines without new facts,
     the agent MUST set the case status to 'manual_review_required' with
     their reason.
1.4  IF this run brings a message or ticket decision from the person asked
     about this SOP's open request, the agent MUST complete STEP 2 and
     continue at the reply clause of the E-rule the last escalation note
     names.
1.5  IF a request is open and this run brings no message or ticket decision
     at all, the agent MUST continue at STEP 2 to check the waits.
1.6  IF a request is open and this run brings no message or ticket decision
     from the person asked, or a clause continues here, the agent MUST
     answer any question per C-1 without repeating the request and set the
     case status to 'awaiting_human_input' with a note per E-0.
1.7  OTHERWISE the agent MUST continue at STEP 2 as a fresh run.

================================================================================
STEP 2: GATHER DATA
================================================================================

2.1  The agent MUST read the requisition items with their processing and
     approval status, values, account assignment and item texts, the
     requisitioner, company code, any follow-on purchase order, whether MRP
     created the requisition and whether its items are service items.
2.2  The agent MUST read, for each item awaiting approval, the approval
     workflow status, the pending approver with contact address and whether
     that approver holds an open approval task.
2.3  The agent MUST read the manager of each pending approver with contact
     address, from [TO BE PROVIDED: source of the pending approver's
     manager].

================================================================================
STEP 3: DECIDE
================================================================================

3.1  IF data read in this run shows no requisition item awaiting approval,
     because each is released, rejected, deleted or converted to a purchase
     order, the agent MUST continue at STEP 5.
3.2  IF MRP created the requisition, an item is a service item, or the
     requisition belongs to another company code than SCOPE names, the agent
     MUST halt per H-1 with that reason, because this SOP covers only the
     requisitions SCOPE lists and no reply changes that.
3.3  The agent MUST compute the days open, the whole calendar days from the
     case creation time to the current time.
3.4  IF the days open reach {{MANUAL_REVIEW_DAYS}} calendar days, the agent
     MUST halt per H-1 with the days open and the open requests as the
     reason, because the approved policy hands such cases to procurement.
3.5  IF this run brings a reply from the person asked, the agent MUST
     decide from its text and any attachment whether the approver acted,
     will act or is not the right one, and MUST escalate per E-1 when it
     cannot tell, with the evidence it weighed in the note.
3.6  IF a reply says the pending approver is not the right one, the agent
     MUST notify {{CONTACT_WORKFLOW_ADMIN}} and set the case status to
     'manual_review_required', both with the reply.
3.7  The agent MUST record for each item awaiting approval its waiting
     cause: workflow error when the approval workflow is in error, no
     approver when no approver holds an open approval task, and approver
     pending otherwise.
3.8  The agent MUST record every waiting cause that applies across the
     items, not only the first, and MUST continue at STEP 4.

================================================================================
STEP 4: HAND OVER FOR HUMAN ACTION
================================================================================

4.1  The agent MUST NOT release, reject or change the requisition itself,
     because release authority belongs to the approver in SAP, and MUST
     continue at 4.2.
4.2  IF workflow error or no approver applies and the case history shows no
     E-2 request for that cause, the agent MUST escalate per E-2, because a
     reminder cannot reach an approver without an open approval task.
4.3  IF approver pending applies, the days open reach
     {{MANAGER_ESCALATION_DAYS}} calendar days, and the case history shows an
     E-3 request to that approver but no E-4 request about that approver,
     the agent MUST escalate per E-4 when a manager is recorded for that
     approver, and per E-1 otherwise.
4.4  IF approver pending applies and the case history shows no E-3 request
     to that approver, the agent MUST escalate per E-3.
4.5  OTHERWISE the agent MUST continue at 1.6 without sending an open
     request again, because each request goes out once.

================================================================================
STEP 5: CLOSE CASE
================================================================================

5.1  The agent MUST notify the requisitioner recorded on the requisition
     with the subject Purchase requisition {requisition number}: approval
     outcome and a body listing each item's outcome, without naming the
     approver.
5.2  The agent MUST set the case status to 'complete'.

================================================================================
ESCALATION RULES
================================================================================

E-0  Every escalation note MUST name the request, the contacts asked, the
     process type and the E-rule.
E-1  The agent MUST escalate to {{CONTACT_PROCUREMENT}} with its findings and
     the question this SOP leaves open.
E-1a  On a reply answering the open question the agent MUST continue
      at STEP 3 with that answer; on any other reply it MUST halt per
      H-1.
E-2  The agent MUST ask {{CONTACT_WORKFLOW_ADMIN}} to correct the approval
     workflow or assign an approver, naming the requisition, the items, the
     waiting cause, any approver a reply named and its assessment of the
     cause.
E-2a  On a reply that the workflow is corrected or an approver is assigned,
      the agent MUST continue at STEP 3; on any other reply it MUST halt per
      H-1.
E-3  The agent MUST ask the pending approver to release or reject the
     requisition in SAP, with the requisition number, requisitioner, items,
     total value, days open and its assessment.
E-3a  On a reply from the pending approver, the agent MUST continue at
      STEP 3, which weighs the reply; on any other reply it MUST halt per
      H-1.
E-4  The agent MUST ask the manager of the pending approver to have the
     approver release or reject the requisition, or to name who will, with
     the facts E-3 lists and the date of the E-3 request.
E-4a  On a reply naming another approver, the agent MUST escalate per E-2
      with that name; on a reply that the approver acted or will act, it
      MUST continue at STEP 3; on any other reply it MUST halt per H-1.
H-1  To halt, and wherever the platform rules call for 'error', the agent
     MUST notify {{CONTACT_PROCUREMENT}}, then set the case status to
     'manual_review_required', both with the reason, because 'error' loses it.

================================================================================
CONTACTS
================================================================================

- Procurement team:        {{CONTACT_PROCUREMENT}}
- Workflow administrator:  {{CONTACT_WORKFLOW_ADMIN}}
- Pending approver: the approver recorded on the item's open approval step
- Approver's manager: the manager read per 2.3
- Requisitioner: the requisitioner recorded on the requisition

================================================================================
LIMITS AND WAITS (CONFIGURABLE — DECLARED IN skills/procurement/config.json)
================================================================================

Policy owner: Procurement process owner approved these waits for the agent;
neither has a counterpart in SAP, and neither replaces a Flexible Workflow
step deadline.

| Parameter                                                 | Symbol                      |
|-----------------------------------------------------------|-----------------------------|
| Wait before asking the approver's manager — calendar days | {{MANAGER_ESCALATION_DAYS}} |
| Wait before manual review — calendar days                 | {{MANUAL_REVIEW_DAYS}}      |

================================================================================
REQUIRED AGENT CAPABILITIES
================================================================================

Read:   purchase requisition and items, their approval workflow status and
        pending approvers, the manager of each pending approver
Write:  none in this SOP
Notify: procurement team, workflow administrator, pending approver,
        approver's manager, requisitioner

================================================================================
OPEN ITEMS
================================================================================

- [TO BE PROVIDED: in-scope company code] (SCOPE)
- [TO BE PROVIDED: source of the pending approver's manager] (2.3)

================================================================================
REVISION HISTORY
================================================================================

Document owner: Procurement process owner

| Version | Date       | Author                    | Changes                 |
|---------|------------|---------------------------|-------------------------|
| 1.0     | 2026-10-28 | Procurement process owner | Initial release         |
| 2.0     | 2026-10-28 | Procurement process owner | Agent judgment sections |
```

Changes against the user's Version 1.0, and why:
- AGENT JUDGMENT now leads with the open default (Z-1 to Z-5), then questions, proactive help and declines written for this process; PERMITTED COMMUNICATIONS and the locked rules follow as their own sections, with tempting-but-prohibited cases (P-4 to P-6).
- Version 1.0 forbade advising the approver; P-2 now forbids only deciding for the approver, and C-3, E-2 and E-3 carry the agent's assessment.
- 3.5 weighs free-text replies instead of matching fixed phrases; a reply it cannot read goes to procurement.
- STEP 1 is in plain words; 1.5 checks the waits whenever the case runs without a message, and the hand-off notes that the waits need the case to run again.

The excerpt below is STEP 3 and STEP 4 of a rewritten entry point, `invoice_matching.txt`, the one finance illustration: every type recorded, missing documents classified rather than halted, limit clauses (V1) copied word for word from the focused SOPs, a precedence with a because (3.10), and within-limit routing (3.11).

```text
================================================================================
STEP 3: DECIDE
================================================================================

3.1  The agent MUST check the exception types in the order of the table in
     SCOPE and record every type that applies, not only the first.
3.2  A duplicate applies when a prior invoice of the same supplier carries the
     same supplier reference, whatever its amount, because the duplicate
     invoice SOP decides between a true duplicate and a corrective invoice.
3.3  A missing or invalid purchase order applies when the referenced purchase
     order does not exist or is closed for invoicing.
3.4  A missing goods receipt applies when a purchase order item that expects a
     goods receipt has no positive net received quantity (receipts minus
     reversals), because a partial receipt is a quantity variance.
3.5  A unit-of-measure mismatch applies when the invoice unit differs from the
     purchase order unit.
3.6  The quantity variance, the amount by which the invoice quantity exceeds
     the net received quantity not yet invoiced, is WITHIN tolerance only
     when it is within {{QTY_VARIANCE_PCT}} percent of the net received
     quantity AND within {{QTY_VARIANCE_UNITS}} units; exceeding either limit
     is ABOVE tolerance.
3.7  The price variance is WITHIN tolerance only when it is within
     {{PRICE_VARIANCE_PCT}} percent of the order price AND within
     {{PRICE_VARIANCE_ABS_USD}} USD per order price unit; exceeding either
     limit is ABOVE tolerance.
3.8  The price variance is also ABOVE tolerance when the line difference, the
     price difference times the invoiced quantity in order price units,
     exceeds {{LINE_AMOUNT_TOLERANCE_USD}} USD.
3.9  A quantity or price variance is ABOVE tolerance for the invoice when it
     is ABOVE tolerance on any invoice line.
3.10  A quantity or price variance applies as an exception type only when it is
     ABOVE tolerance and no missing purchase order, missing goods receipt or
     unit-of-measure mismatch applies, because those make the comparison
     meaningless.
3.11  IF no type applies but a variance WITHIN tolerance exists, the agent MUST
      treat the first such variance in the table order as the exception type,
      because its focused SOP releases invoices within tolerance.
3.12  IF no type applies and no variance exists, the agent MUST escalate per
      E-1.

================================================================================
STEP 4: FOLLOW THE FOCUSED SOP
================================================================================

4.1  IF exactly one exception type applies, the agent MUST follow the
     focused SOP that SCOPE lists for it.
4.2  IF several exception types apply, the agent MUST escalate per E-1
     with all of them.
```
