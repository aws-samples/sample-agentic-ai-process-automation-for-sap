<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Plain Procedure

Read when the user names another agent or wants just the procedure: a standalone SOP any agent can follow.

## What stays

Intake, the Agent Fit Summary (runtime: "plain procedure (as you told me)"), AGENT JUDGMENT, locked rules and quality bar stay. Skip the runtime question and the process_type key; open with "I'm assuming SAP S/4HANA — tell me if it's different. You want a standalone procedure any agent can follow, so I'll write it that way." Intake also asks whether a request can name an effective date (typical: halt unless today) and how long a confirmation may take (typical: 5 business days).

## Write

Fill `sop-template.md` exactly, with these swaps:

| Template | Plain procedure |
|---|---|
| Status literals | In PURPOSE after the RFC 2119 sentence: "Case states: waiting for a reply, manual review, changed in SAP, complete. A request is open from its escalation until answered; a holding reply keeps it open and its wait running." |
| `{{SYMBOL}}` limits and waits | The value with its unit, in LIMITS AND WAITS, one row per limit named in words; clauses cite it by name ("ABOVE the <name> limit"). Unknown: `[TO BE PROVIDED: …]`. |
| `{{CONTACT_*}}` | Roles listed in CONTACTS; clauses name the role. |
| "status change", "message or ticket decision", "denies the ticket" | "case state change", "message or decision", "denies the request" |
| PRECONDITIONS 3, STEP 1 1.2, 1.3 and the waiting clause, the 'sap_updated' clause, E-0, H-1 | The text below, word for word; `<r>` goes just before `<w>`, `<n>` after `<s>`. |
| LIMITS AND WAITS banner | "LIMITS AND WAITS" alone. |
| Process Type line, config.json, platform, repo, sync and deploy references | Dropped; an entry point routes to focused SOPs by file name. |

Keep the title block and Version line, the RFC 2119 sentence, every rule ID, every MUST NOT with its because, Z-1, C-1 and L-1 word for word.

```text
3.   The agent can read the case history and any message or decision that
     started this run. A run starts on a new request or a reply on the case,
     and every reply and note is kept in the case history. While a case
     waits, a run also starts each business day.
1.2  IF the case is already complete or in manual review and this run
     brings a message or decision, the agent MUST answer any question per
     C-1 and leave the case in the same state with the earlier reason.
1.3  IF the person asked denies the request or declines without new facts,
     the agent MUST set the case to manual review with their reason.
<r>  IF a request is open and this run brings a message from the requester
     that changes what was requested, the agent MUST halt per H-1.
<w>  IF a request is open and this run brings no message or decision from
     the person asked, or a clause continues here, the agent MUST answer any
     question per C-1 without repeating the request and set the case to
     waiting for a reply with a note per E-0.
<s>  After the change succeeds and SAP shows the values written, or SAP
     answers that it is already in the target state, the agent MUST set the
     case to changed in SAP.
<n>  IF SAP rejects the change, or the object in SAP does not then show
     the values written, the agent MUST halt per H-1 with SAP's message and
     MUST NOT repeat the change, because a repeat can post twice or hide
     the cause.
E-0  Every escalation note MUST name the request, the contacts asked and
     the E-rule. After sending an escalation, the agent MUST set the case to
     waiting for a reply with that note and end this run.
H-1  To halt, the agent MUST notify <role> and hand the case to manual
     review with the reason.
```

The SOP also carries:

- Per SCOPE criterion SAP data can decide, an early STEP 3 clause citing SCOPE that halts per H-1.
- For central master data shared beyond SCOPE (a business partner's address or bank details), a STEP 2 read of its other roles and assignments and a STEP 3 halt naming each excluded role or assignment; an address gets bank-detail fraud care.
- For a write, a STEP 3 clause on a requested date other than today: halt, escalate, or change only from that date.
- On each STEP clause escalating per E-n, the guard "the case history shows no E-n request", halting per H-1 otherwise; its E-rule names who may answer (not the requester).
- A confirmation E-rule asking who confirmed, over which channel on record and when, for the change note; a holding reply continues at `<w>`; reply clauses precede any wait-limit halt.
- Before each write, a halt per H-1 if SAP's values differ from those the approver saw.
- Proactive help that adds what no STEP notification says.

## Check

Run the checker from `quality-checklist.md` with `--plain`, and the other checklist items except those on config.json, SAP services and repo tests; `<n>` is no Q-R8 rejection clause.

## Save and hand-off

Save to `sops/<domain>/<process-name>.txt` in the workspace folder (ask which with several); for an existing file and the report, follow `save-and-handoff.md` steps 5-7. No repo tests or skill files. Hand-off in chat, at most 6 lines, in business words:

```text
1. File: <path> (Version <x.y>) — <process>.
2. Limits and waits: <limit> = <value and unit | not yet provided>; re-run daily while cases wait.
3. Contacts: <role> = <person or mailbox | not yet provided>[; <roles> must be different people].
4. SAP access: read <business data>; change <business objects>.
5. [Configuration values: <business name> = <value | not yet provided>.]
6. [Open items: <TO BE PROVIDED markers>; fill each in before use.]
```
