<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# SOP Design

Read before composing the Agent Fit Summary, and for SOP-set, split or locked-vs-open questions. The method is the same for every SAP process.

## SOP kinds

- Standalone: one process type, one exception family.
- Entry point plus focused SOPs: the entry point classifies, each focused SOP resolves one exception family.
- No-write: high risk, or no write granted (V4).

Entry-point rules:
- Switch by naming the focused SOP for the type in SCOPE, never a tool.
- Read and calculate once in the entry point; the focused 2.1 and STEP 3 calculation reuse it ("unless this run already holds them / it").
- A missing reference document is an exception type, never a halt.
- Where one type makes another's calculation meaningless (a missing document), state the precedence with a because; independent types found together escalate unless the user sets one.
- With limits (V1), a measure is a type only when ABOVE the limit; a case with only measures WITHIN the limit routes to the first such measure's SOP. Every focused limit clause appears word for word in the entry point, and each entry type is at least as broad as its focused SOP's STEP 3.

## Split rules

Propose a split in the Fit Summary only for separate exception families (different data or a different write), a high-risk family mixed with routine ones, or a path so long (many reads, messages and escalations in one run) that the agent may hit its step limit; several contacts in one family are E-rules. The word estimate is a sanity check, never a trigger or trim target: a filled SOP is about 1,800 words (the example 2,300), plus about 50 per added clause, ±300. A declined split stands; re-raise it only when the draft exceeds the confirmed estimate's upper end or a new split reason appears (L3).

## Agent judgment: open by default

The agent is a skilled professional: everything the SOP does not lock is open. Lock only writes and their preconditions, status changes, limits and waits with their approvers, segregation of duties, the prohibited list and halts. Write the open zone for this process, from what its stakeholders really ask and do:
- Questions: 4-6 questions the requester, approver, business partner or process owner asks, each with how the agent answers from the case's data and what it never promises.
- Proactive help: 2-4 things a skilled colleague does unprompted, such as telling the outcome or naming a recurring cause.
- Declines: nearby requests outside the case, and who handles them.
- Tempting but prohibited: 2-3 situations where a shortcut looks reasonable (urgency, a small difference, an absent approver), each with MUST NOT and its reason. Prohibit deciding for a decision owner, never informing one: the agent gives facts and its assessment.

In STEP 3, write a judgment clause wherever a skilled person would weigh evidence (free-text replies, attachments, mixed signals), not only where data is missing: the evidence, the allowed outcomes, a safe default (usually an escalation) when the agent cannot tell, and the evidence weighed for the note.

## Agent Fit Summary

Show it in chat in plain business words, with no rule, gate or checklist IDs and no runtime internals; process types, save paths and wiring go to the hand-off. Bracketed lines appear only when they apply.

```text
Agent Fit Summary — <process>
1. SAP and runtime: <release>, <runtime> (default — correct me if not | as you told me)
2. When it starts and ends: <trigger> → <end state>; not covered: <list>
3. Fit: <verdict>; SOPs: <names in plain words>[; I suggest splitting because …]
4. What the agent does: <3-7 short steps>
5. What it reads and changes in SAP: <business terms>
6. Who decides: <decision> → <role>; exceptions: <exception> → <role>
7. Limits and waits: <value, unit, what it triggers, who approved it> | none
8. Where the agent thinks for itself: <open areas>; for example it answers <2-3 questions>
9. What stays locked: <changes, approvals and prohibitions in plain words>
10. If SAP rejects a change: <…>; if a person says no: <…>
11. Author <author>; document owner <owner>; still open: <items | none>
[12. Please check: <a rule I added for an edge case | a source conflict>]
Confirm and I'll write the SOP(s), or tell me what to change.
```
