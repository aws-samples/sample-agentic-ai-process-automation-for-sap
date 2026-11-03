<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# SOP Template

Read before writing or modifying an SOP.

## Rendering rule

Lines starting `[entry]` or `[focused]` belong to one kind of SOP, in a 10-character marker column. For an entry point, delete the `[focused]` lines and strip the marker column from `[entry]` lines (a marker-only line becomes empty); for a focused or standalone SOP, the reverse. A standalone SOP also drops the "It applies after" line. Fill every `<…>` field, date the revision row today, add process clauses, delete unneeded frames, and keep numbering consecutive. Write the AGENT JUDGMENT examples and the tempting-but-prohibited P-clauses for this process (`sop-design.md`). With no limits or waits, LIMITS AND WAITS holds only `- None.`; with no external party, delete that CONTACTS line; with `[TO BE PROVIDED: …]` markers, add OPEN ITEMS before REVISION HISTORY. Several process_type keys for one SOP go on one `Process Types:` line, primary key first; the file takes its name. Keep PRECONDITIONS 2-3, Z-1, C-1, L-1, STEP 1, E-0, H-1 and the focused 'sap_updated' clause word for word (variants excepted), because the checker keys on them; adapt every other clause's wording, keeping its effect.

```text
<PROCESS NAME IN UPPERCASE> — <SUBTITLE IN UPPERCASE>
STANDARD OPERATING PROCEDURE (SOP)
Version 1.0

================================================================================
PURPOSE
================================================================================

This SOP defines how the agent <handles / follows up / resolves / reviews>
<business object> in <SAP S/4HANA | the release the user confirmed>. <When
it applies.> Its goal is <goal>, NOT <non-goal>.
[entry]   This is the ENTRY-POINT SOP for <process>; each exception type has a
[entry]   focused SOP, see SCOPE.
[focused] It applies after <entry-point SOP title> has classified the case as
[focused] <exception family>.

Process summary (informative; the clauses below decide): <at most 40 plain
words a process owner can approve; no rule IDs and no RFC 2119 keywords>

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT",
"SHOULD", "SHOULD NOT", "RECOMMENDED", "MAY", and "OPTIONAL" in this
document are to be interpreted as described in RFC 2119.

================================================================================
SCOPE
================================================================================

Process Type:  <process_type>
Business area: <business area in words>
In scope: <documents, org units>. Out of scope: <other processes>.
[entry]
[entry]   | Exception                 | Focused SOP (process_type)   |
[entry]   |---------------------------|------------------------------|
[entry]   | <exception family>        | <process_type>               |

================================================================================
PRECONDITIONS
================================================================================

Before execution, the following MUST be true:

1. The case record identifies the <business document> by its <business keys>.
2. The agent has NO memory of prior runs — each execution is stateless.
3. The run's prompt shows any message or ticket decision. The case status
   reads 'processing' during every run, so the case history and status reason
   show where the case last stood.

================================================================================
AGENT JUDGMENT — WHERE THE AGENT THINKS
================================================================================

Z-1  GUIDING PRINCIPLE: Everything outside this SOP's locked rules is the
     agent's to reason about as a skilled <role> would, with its SAP
     knowledge and this case's data. When unsure whether an action is
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

Z-6  When <stakeholder> asks '<a question this process raises>', the agent
     SHOULD <answer from this case's data>, without <a commitment>.
Z-7  When <stakeholder> asks '<another question>', the agent SHOULD <answer>,
     without <a commitment>.
Z-8  When <stakeholder> asks '<another question>', the agent SHOULD <answer>,
     without <a commitment>.
Z-9  When <stakeholder> asks '<another question>', the agent SHOULD <answer>,
     without <a commitment>.

Proactive help:

Z-10  Once the case resolves, the agent SHOULD tell <external party> the
      outcome without <internal detail or commitment>.
Z-11  When this case's data shows <a cause likely to recur>, the agent SHOULD
      name it in the closing notification so <owner> can fix it.

Out of scope — decline politely:

Z-12  The agent MUST politely decline a request outside this case, such as
      <example> or <example>, and name who handles it where the case data
      shows it, because it acts only for this case.

================================================================================
PERMITTED COMMUNICATIONS
================================================================================

C-1  The agent MAY answer this case's stakeholders from this case's data and
     SAP knowledge, without commitments or anything a P-clause forbids.
C-2  The agent MAY tell <stakeholder> <what> when <condition>, without
     <commitment>.

================================================================================
LOCKED RULES AND PROHIBITED JUDGMENT
================================================================================

L-1  LOCKED: Writes, statuses, limits, approvals and halts follow only the
     SOP the agent follows. It MUST NOT make a write that SOP does not name,
     even on approval, because only an SOP grants writes, and MUST notify the
     E-1 contact of the request and continue the SOP.
P-1  The agent MUST NOT <action a stakeholder may ask for>, because <reason>.
P-2  The agent MUST NOT <decide for a person who owns a decision>, because
     <reason>, and MAY give that person the facts and its assessment.

Tempting but prohibited:

P-3  When <a stakeholder says the case is urgent>, the agent MUST NOT <skip a
     wait, check or approval>, because <the locked rules are the approved
     policy>.
P-4  When <a tempting situation, such as a small difference or an absent
     approver>, the agent MUST NOT <shortcut>, because <reason>.

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
[entry]   1.4  IF this run brings a message or ticket decision from the person
[entry]        asked about an open request, the agent MUST load the SOP the last
[entry]        escalation note names if needed, complete its STEP 2, and
[entry]        continue at the reply clause of that note's E-rule.
[focused] 1.4  IF this run brings a message or ticket decision from the person
[focused]      asked about this SOP's open request, the agent MUST complete
[focused]      STEP 2 and continue at the reply clause of the E-rule the last
[focused]      escalation note names.
1.5  IF a request is open and this run brings no message or ticket decision
     from the person asked, or a clause continues here, the agent MUST
     answer any question per C-1 without repeating the request and set the
     case status to 'awaiting_human_input' with a note per E-0.
1.6  OTHERWISE the agent MUST continue at STEP 2 as a fresh run.

================================================================================
STEP 2: GATHER DATA
================================================================================

[entry]   2.1  The agent MUST read the <business data elements> of the
[entry]        <document>.
[focused] 2.1  The agent MUST read the <business data elements> of the
[focused]      <document>, unless this run already holds them.

================================================================================
STEP 3: DECIDE
================================================================================

[focused] 3.1  IF data read in this run shows the <document> no longer needs
[focused]      <the outcome>, the agent MUST continue at STEP 5.
[entry]   3.1  The agent MUST classify the case as <exception type> when data
[entry]        read in this run shows <condition>.
[entry]   3.2  The agent MUST record every <exception type> that applies, not only
[entry]        the first, and MUST escalate per E-1 when none applies.
[focused] 3.2  IF data read in this run shows <a condition the data decides>,
[focused]      the agent MUST <outcome>, because <reason>.
[focused] 3.3  The agent MUST decide from <evidence> whether <a question a
[focused]      skilled person would weigh>, and MUST <safe default> when it
[focused]      cannot tell, with the evidence it weighed in the note.
[focused] 3.4  IF this run or the case history shows an approval by the contact
[focused]      asked of the <values> read in this run, the agent MUST continue at
[focused]      STEP 4.
[focused] 3.5  IF <the outcome needs a person's decision>, the agent MUST
[focused]      escalate per E-2.
[focused] 3.6  OTHERWISE the agent MUST continue at STEP 4.

[entry]   ================================================================================
[entry]   STEP 4: FOLLOW THE FOCUSED SOP
[entry]   ================================================================================
[entry]
[entry]   4.1  IF exactly one exception type applies, the agent MUST follow the
[entry]        focused SOP that SCOPE lists for it.
[entry]   4.2  IF several exception types apply, the agent MUST escalate per E-1
[entry]        with all of them.
[focused] ================================================================================
[focused] STEP 4: EXECUTE RESOLUTION
[focused] ================================================================================
[focused]
[focused] 4.1  IF data read in this run shows that the <document> still <needs
[focused]      the write>, the agent MUST <write in business terms>; OTHERWISE
[focused]      it MUST continue at STEP 5.
[focused] 4.2  After the write succeeds, or SAP answers that the <document> is
[focused]      already in the target state, the agent MUST set the case status
[focused]      to 'sap_updated' with the <resulting reference> in the note.
[focused]
[focused] ================================================================================
[focused] STEP 5: CLOSE CASE
[focused] ================================================================================
[focused]
[focused] 5.1  The agent MUST notify {{CONTACT_<KEY>}} with the subject <subject
[focused]      with {merge fields}> and a body that lists <fields>.
[focused] 5.2  The agent MUST set the case status to 'complete'.

================================================================================
ESCALATION RULES
================================================================================

E-0  Every escalation note MUST name the request, the contacts asked, the
     process type and the E-rule.
E-1  The agent MUST escalate to {{CONTACT_<KEY>}} with its findings and
     the question this SOP leaves open.
[entry]   E-1a  On a reply naming one exception type the agent MUST continue at
[entry]         4.1 with that type; on any other reply it MUST halt per H-1.
[focused] E-1a  On a reply answering the open question the agent MUST continue
[focused]       at STEP 3 with that answer; on any other reply it MUST halt per
[focused]       H-1.
[focused] E-2  The agent MUST request a decision from {{CONTACT_<KEY>}} with
[focused]      <business facts> and its assessment, naming the <values> the
[focused]      decision covers.
[focused] E-2a  On approval or corrected data the agent MUST continue at STEP 3;
[focused]       on any other reply it MUST halt per H-1.
H-1  To halt, and wherever the platform rules call for 'error', the agent
     MUST notify {{CONTACT_<KEY>}}, then set the case status to
     'manual_review_required', both with the reason, because 'error' loses it.

================================================================================
CONTACTS
================================================================================

- <Role>:  {{CONTACT_<KEY>}}
- <External party>: the <party> contact recorded on the <document>

================================================================================
LIMITS AND WAITS (CONFIGURABLE — DECLARED IN skills/<domain>/config.json)
================================================================================

- None.

================================================================================
REQUIRED AGENT CAPABILITIES
================================================================================

Read:   <business object>, <business object>
[entry]   Write:  none in this SOP
[focused] Write:  <business write>
Notify: <role>, <role>

================================================================================
REVISION HISTORY
================================================================================

Document owner: <role or name>

| Version | Date       | Author       | Changes                              |
|---------|------------|--------------|--------------------------------------|
| 1.0     | YYYY-MM-DD | <author>     | Initial release                      |
```

## Variants

Apply only the variants the Fit Summary names, renumbering their IDs.

```text
V1  Limits, only when the process has them (waits use V9): add the clauses
    below after the focused 3.3; the escalation clause after the approval clause
    becomes the third one. Copy the limit clauses into the entry point word
    for word. Two limits on one measure use EITHER; on the user's stated
    BOTH policy, with its owner, the limit clause reads: The <measure> is
    ABOVE the limit only when it exceeds BOTH {{<SYMBOL_A>}} <unit A> AND
    {{<SYMBOL_B>}} <unit B>; breaching one limit is WITHIN the limit. In
    LIMITS AND WAITS, the policy owner line and one row per symbol replace
    - None.:
Policy owner: <role> approved these limits and waits for the agent; <per
limit: wider than, equal to or without a counterpart in SAP's configuration>.
| Parameter                                  | Symbol                        |
|--------------------------------------------|-------------------------------|
| <Parameter A — unit in words>              | {{<SYMBOL_A>}}                |
3.4  The agent MUST compute <measure> for each <line> as <formula in business
     terms, absolute unless the policy is one-sided>, in <comparison
     currency and basis>, unless this run already holds it.
3.5  The <measure> is WITHIN the limit only when it is within
     {{<SYMBOL_A>}} <unit A> AND within {{<SYMBOL_B>}} <unit B>; exceeding
     either limit is ABOVE the limit.
3.7  IF the <measure> of any <line> is ABOVE the limit, the agent MUST
     escalate per E-2.

V2  A rejected write asks for a correction (G6); add after the 'sap_updated'
    clause, with E-<n> and its reply clause:
4.3  IF SAP rejects the write and the message does not say the <document> is
     already in the target state, the agent MUST escalate per E-<n> for a
     correction instead of halting, because <user's reason>.

V3  A refusal triggers a defined action (G7), replacing 1.3; a notification
    it needs goes in its own E-rule. Where one request's negative decision
    has its own outcome, keep 1.3: that E-rule asks which named outcome
    applies and its reply clause routes each, because a denied ticket
    always reaches 1.3:
1.3  IF the person asked denies the ticket or declines without new facts,
     the agent MUST <action> instead of halting, because <user's reason>.
    Ending in manual review, it also notifies the E-1 contact.

V4  No-write: the focused STEP 4 becomes the banner and clauses below; the
    E-<n>a reply clause routes a confirmation to 4.2; the Write line reads
    "none in this SOP". Without a requester, 4.2 drops "other than the
    requester".
STEP 4: HAND OVER FOR HUMAN ACTION
4.1  The agent MUST NOT <make the change> itself, because <reason>, and MUST
     request the change per E-<n> with the verified facts.
4.2  IF the reply confirms that a person other than the requester made and
     verified the change, the agent MUST continue at STEP 5.

V5  Release-type write, replacing the focused 4.1 (the 'sap_updated' clause
    becomes 4.3), with E-<n> and its reply clause. Each failed check within
    one SAP block is its own blocking reason, so 2.1 reads which checks failed
    and STEP 3 decides each; a check the policy reserves to people escalates
    in STEP 3. Count only blocks that stop the same outcome; where no other
    block can, omit 4.1, E-<n> and E-<n>a and number the release clause 4.1.
4.1  IF data read in this run shows the <document> blocked for <this family's
     reason> and for <another reason that stops the same outcome>, this run
     carries no E-<n> reply, and no approval recorded in this run or the case
     history names that other reason, the agent MUST escalate per E-<n>.
4.2  IF data read in this run shows the <document> blocked for <this family's
     reason>, the agent MUST release that block under the decision STEP 3
     reached in this run; OTHERWISE it MUST continue at STEP 5.
E-<n>  The agent MUST ask {{CONTACT_<KEY>}} whether to release the <block>
     while <the other blocking reasons> remain, naming them.
E-<n>a  On a reply allowing the release, or reporting the other blocks
      cleared, the agent MUST continue at STEP 3; on any other reply it
      MUST halt per H-1.

V6  One limit per org unit or currency, replacing the V1 limit clause with
    one clause per limit; a limit set in each org unit's own currency gets
    one symbol per currency:
3.5  In <org unit A>, the <measure> is ABOVE the limit when it exceeds
     {{<SYMBOL_A>}} <unit A>.
3.6  In <org unit B>, the <measure> is ABOVE the limit when it exceeds
     {{<SYMBOL_B>}} <unit B>.

V7  Tiered approvers: one E-rule per amount band, one contact each, and one
    shared reply clause:
E-3  The agent MUST request a decision from {{CONTACT_<TIER_1>}} when <amount>
     is at most {{<TIER_1_LIMIT>}} <unit>, naming the <amount>.
E-4  The agent MUST request a decision from {{CONTACT_<TIER_2>}} when <amount>
     exceeds {{<TIER_1_LIMIT>}} <unit>, naming the <amount>.
E-3a  On approval of an E-3 or E-4 request by the contact asked, the agent
      MUST continue at STEP 3; on any other reply it MUST halt per H-1.

V8  Chained controls or sequential approvals (verification, then approval,
    then the write): one E-rule per control, each reply clause continuing at
    the next control's E-rule and the last at 4.1, which replaces the focused
    4.1, because a resumed run sees earlier replies only in the case history.
    Where STEP 3 holds checks the write must pass (T12), the last reply
    continues at STEP 3, whose last clause routes by the control replies on
    record. The focused 3.1 closes the case only when the case history shows
    every control reply and otherwise halts per H-1, so nothing confirms a
    change made outside the controls. Control contacts must resolve to
    different people (hand-off contacts line). A verification confirms the complete
    requested change from the request record, which values from a control
    reply join, over a channel recorded before the request; the write sets
    exactly the details verified. Where a P-clause masks values, it covers
    approval requests and a write's proposed values, and the full values stay
    in the case record:
4.1  IF data read in this run shows that the <document> still <needs the
     write> and this run or the case history shows <every control reply>,
     the agent MUST <write>; IF a control reply is missing, it MUST halt per
     H-1; OTHERWISE it MUST continue at STEP 5.
E-<n>  The agent MUST ask {{CONTACT_<VERIFIER>}} to confirm the complete
     requested <change>, read from the request record, with <party> over
     <a channel recorded before the request>.
E-<n>a  On a reply from the contact asked that every detail matched, the
      agent MUST escalate per the next control's E-rule; on any other reply
      it MUST halt per H-1.

V9  Waits (a reminder, escalation or hand-over after a number of days): a
    run that brings no message checks the waits, so each SOP of the set
    adds 1.5 below before the waiting clause, the one STEP 1 addition, and
    renumbers STEP 1. The SOP that sends the requests adds the clauses below
    after the focused 3.1, one wait clause per wait (a final wait halts per
    H-1 instead), and renumbers STEP 3; 3.4 keeps a run with no message from
    reaching the request clauses. Declare each wait as in V1, its row
    starting Wait before, because the checker keys on it:
1.5  IF a request is open and this run brings no message or ticket decision
     at all, the agent MUST continue at STEP 2 to check the waits.
3.2  The agent MUST compute the days waited, the whole calendar days from
     <the case creation time or the date of the request in the case
     history> to the current time.
3.3  IF the days waited reach {{<WAIT_DAYS>}} calendar days and the case
     history shows no E-<n> request, the agent MUST escalate per E-<n>.
3.4  IF a request is open and this run brings no message or ticket decision
     at all, the agent MUST continue at <the waiting clause> without sending
     an open request again, because each request goes out once.
| Wait before <what the wait triggers> — calendar days | {{<WAIT_DAYS>}}  |
```

## Writing rules

- T1 Name data as business elements ("requisition approval status") and writes as verbs on business objects; never transaction codes, BAPIs, OData services or entities, function modules, tables, field names, tool names or formulas, which belong in `config.json → sap_service`.
- T2 MUST only where skipping causes financial loss, data corruption or an audit failure, and always for writes, halts, escalations and statuses; SHOULD for judgment and defaults with exceptions; MAY for context choices.
- T3 "The agent MUST …", "IF … the agent MUST …", "OTHERWISE …"; one rule per clause; one term per concept across a set.
- T4 Never restate the platform prompt (tools, retries, citing, waiting, read-back); only fixed clauses 1.2, 1.3, the waiting clause, the 'sap_updated' clause and H-1 touch platform rules.
- T5 Each clause is quotable alone: 6 words or more, at most 2 sentences and 320 characters, no "it" or "this" pointing at another clause, no bullets, double quotes or period abbreviations; statuses and quoted questions in single quotes, with no lowercase must, should or may inside.
- T6 Every MUST NOT and SHOULD NOT gives its reason in the same clause ("because", "since", "to avoid"); no CRITICAL or NEVER.
- T7 State each rule once and cite it ("per E-2", "at 4.1"); never restate STEP 1 or a reply clause in STEP 3; no escalation table; E-1 has no trigger; clauses shared by an entry point and a focused SOP cite no clause numbers.
- T8 Limits and waits appear only as `{{SYMBOL}}` (UPPER_SNAKE with a unit suffix: `_PCT`, `_DAYS`, `_UNITS` or a currency code, never `CONTACT_`; reuse the skill's symbol of the same meaning) with the unit in words beside it, each listed once in LIMITS AND WAITS with its policy owner; values go to the hand-off. Two limits on one measure follow V1, or V6 per org unit or currency, with uppercase AND, never "whichever".
- T9 Each write type appears in exactly one STEP clause, writing only while this run's data still needs it. A release uses V5, chained controls V8; a write SAP would accept twice (creating a document) adds "and the case record shows no earlier <document> for this case".
- T10 A notification names recipients, a subject with single-brace merge fields, and body facts true on every branch reaching it ("where the case has them" if optional); the subject's verb fits every outcome, and only write confirmations wait for the write.
- T11 Human recipients are `{{CONTACT_KEY}}` roles in CONTACTS, reusing existing keys (`cdk/config.yaml`, else the hand-off list). A party recorded on the data is described by that data and read in STEP 2. No names or addresses.
- T12 Steps run in order; jumps go only to named continue-at targets, escalations, the halt or the waiting clause, and a continue-at to the waiting clause performs its action. No reply target returns to the same E-rule unless a condition it tests has changed, so a check no reply can change halts per H-1 instead of escalating; approval and block replies continue at STEP 3, whose approval clause precedes its escalations. 1.3 takes every denial or refusal before any reply clause, so no reply clause branches on a negative decision (V3). Each E-rule names one contact, because the platform notifies every contact a clause lists; a condition choosing a contact becomes separate E-rules, and tiers use V7. A check the Fit Summary makes unconditional precedes every clause that skips past it, and a check that can settle the case precedes any request.
- T13 Locators are digits only (`3.10`, never `3.1a`); IDs are Z-n, C-n, L-1, P-n, E-0, E-n with reply clause E-na, and H-1.
