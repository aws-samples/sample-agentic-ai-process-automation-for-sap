<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Intake

Read before the first intake message of a new SOP, before a modification's gate questions, and for fit questions (Fit check only).

## Opening message

Fill the template below. Every message is short and in plain business words: never show gate, rule or checklist IDs, or runtime internals unless the user asks; never investigate runtime code. List each answered item with its source and never ask it again; for a partly answered one, ask the rest. If nothing is missing, ask only G9 if unstated, then show the Agent Fit Summary.

```text
I'll write this as an agent SOP for <process>, from a senior SAP functional consultant's view.
[only defaults the user has not corrected: I'm assuming SAP S/4HANA and the AWS reference runtime — tell me if either is different, if it's a different agent, or if you just want the procedure.]
[for a part the user named: You're on <release>; I'll design for that. / You're running this on <runtime>; I'll ask how it works below.]
[when research is needed: I'll check <topic> in SAP's documentation before the Agent Fit Summary.]
From your request / <file> I already have:
- <topic in plain words>: <answer> (<source>)
- <topic> partly: <what is known>
[Fit flag, only when obvious: rule-based fit / two SOPs / high risk with minimal write authority]
1. <one decision in plain words> Typical: <SAP-practice value, or a common range for a company-specific number>. What is yours?
[at most 5 numbered questions, one decision each, no placeholder shown]
Answer "accept suggestions" for any item, or "later" for values you'll give afterwards.
```

## Fit check

Weigh boundary, controls, decision owners and exceptions by risk (money, compliance, partners); list every cause of the exception, each failed SAP check as its own. Apply each lens that fits:

- Rule-based (data and thresholds decide every path): say rule-based automation fits better and offer to describe the rules in chat.
- Feasibility: a write the runtime's SAP services lack makes the SOP no-write (V4).
- High-fraud data changes (payee or bank data): ask G5 as "Should the agent write at all, or only prepare and verify?"; require segregation of duties and verification, chained per V8; never confirm the change to the requester, and drop the outcome message to them.
- Approval authority (releases, limits): ask G5 the same way; require approver authority and segregation of duties; 5.1 tells the business owner the outcome.
- State SAP already records: never let the agent create or count what SAP already records; derive each amount once. A block an SAP check clears itself is SAP's: the agent waits and informs, never removes it. When the agent changes one state, ask which one (if several) and what happens to the old one and what depends on it.

## Required-input gate

Items marked (d) may be deferred: a value or address to the hand-off, SOP text as `[TO BE PROVIDED: …]`.
- G1 Scope: case trigger, end state, in and out of scope, org units.
- G2 Human-owned decisions and each owner's role (person d).
- G3 Limits and waits, only where the process has them, in up to two numbered items: value (d), unit and basis (for an amount, the comparison currency), EITHER or BOTH ("Typical: exceeding either limit sends it to a person, SAP's own rule where SAP has tolerances. Keep that?"); per limit, wider than, equal to or without SAP's configured tolerance, and who approved that policy; a wait or re-check after N days goes in LIMITS AND WAITS (V9), and the hand-off notes the case must run again while it waits.
- G4 Escalation contact role per path; addresses are deferred unless offered.
- G5 Agent authority: reads, each permitted write in business terms (a posting with its date and period), prohibited actions.
- G6 With a write: SAP rejects it (suggest: manual review with the reason; or ask for a correction).
- G7 A human refuses or decides no (suggest: manual review with the reason; or a defined action).
- G8 Domain and snake_case process_type key(s), suggested from the workspace; reuse a covering skill's domain.
- G9 SOP author and document owner as the user states them (d, after asking); confirm a name from a document once, the only allowed re-ask.
- G10 SAP release (and edition, where the process differs) and G11 runtime: default or correction.
- G12 (optional) What stakeholders typically ask and what a skilled colleague does unprompted; suggest 4-6 questions.

Round 1: G1, G2, G5, any conflict that shapes the process, and the `release-and-runtime.md` questions for a named or implied release or runtime, within the five; overflow moves the runtime question, then G2, then the rest of G1 to Round 2. Round 2: G3, G4, G6-G9, G12, moved up when Round 1 has room; overflow carries to Round 3 in that order, G9 last. Later rounds ask gaps only. After round 3's gaps, or on "just draft it", say you won't guess, offer to defer open (d) items and offer the rest as suggestions; still ask G9.

## The user's documents

- Read PDF, images, HTML and text directly. On macOS convert `.docx`, `.doc` and `.rtf` with `textutil -convert txt -stdout "<file>"`; otherwise, and for `.xlsx` and `.pptx`, save the script below as `"$TMPDIR/office_to_text.py"` and run it with the file. Keep converted text out of SOP folders; on failure, ask for a PDF or text.
- A later chat answer overrides a document. When a document conflicts with standard SAP on the stated release, another document or the runtime, or weakens a control (acting before approval), quote the line, state the standard in one sentence, and ask which applies.
- Click-steps become business steps ("Open ME54N, Release strategy tab" becomes "check who still has to approve the requisition").
- Names and emails become contact roles, addresses go to the hand-off, and personal or payment identifiers never appear. Configuration values (a document type) go to the hand-off.

```python
import re, sys, zipfile, xml.etree.ElementTree as ET
NS = {"w": "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}",
      "s": "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}",
      "a": "{http://schemas.openxmlformats.org/drawingml/2006/main}"}
z = zipfile.ZipFile(sys.argv[1]); names = z.namelist()
num = lambda n: int(re.search(r"(\d+)\.xml$", n).group(1))
parts = lambda pat: sorted((n for n in names if re.fullmatch(pat, n)), key=num)
text = lambda el, ns: "".join(t.text or "" for t in el.iter(NS[ns] + "t"))
if "word/document.xml" in names:
    for p in ET.fromstring(z.read("word/document.xml")).iter(NS["w"] + "p"):
        print("".join("\t" if n.tag == NS["w"] + "tab" else n.text or "" for n in p.iter() if n.tag in (NS["w"] + "t", NS["w"] + "tab")))
elif any(n.startswith("xl/") for n in names):
    shared = [text(si, "s") for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(NS["s"] + "si")] if "xl/sharedStrings.xml" in names else []
    for sheet in parts(r"xl/worksheets/sheet\d+\.xml"):
        print("# sheet", num(sheet))
        for row in ET.fromstring(z.read(sheet)).iter(NS["s"] + "row"):
            cells = []
            for c in row.iter(NS["s"] + "c"):
                v = c.find(NS["s"] + "v")
                cells.append(shared[int(v.text)] if c.get("t") == "s" and v is not None else text(c, "s") if c.get("t") == "inlineStr" else (v.text or "") if v is not None else "")
            print("\t".join(cells))
else:
    for slide in parts(r"ppt/slides/slide\d+\.xml"):
        print("--- slide", num(slide))
        for p in ET.fromstring(z.read(slide)).iter(NS["a"] + "p"):
            if text(p, "a"): print(text(p, "a"))
```
