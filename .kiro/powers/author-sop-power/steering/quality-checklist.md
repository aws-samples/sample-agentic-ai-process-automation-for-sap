<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Quality Checklist

Read after drafting and before saving, and for any review, contract check or migration.

## Run the checker

Save the script below as `"$TMPDIR/check_sop.py"` and run it once on all SOPs of a set, `python3 "$TMPDIR/check_sop.py" [--config skills/<domain>/config.json] <entry.txt> <focused.txt> …`, so cross-file items compare them. Without `python3`, apply the script's rules by eye and say "checked manually".

```python
import re, sys, unicodedata
EQ = "=" * 80
ORDER = ["PURPOSE", "SCOPE", "PRECONDITIONS", "AGENT JUDGMENT", "PERMITTED COMMUNICATIONS", "LOCKED RULES AND PROHIBITED JUDGMENT",
         "STEP 1:", "STEP 2:", "STEP 3:", "STEP 4:", "ESCALATION RULES", "CONTACTS", ("LIMITS AND WAITS", "TOLERANCES"),
         "REQUIRED AGENT CAPABILITIES", "REVISION HISTORY"]
LIMITS = "(?:LIMITS AND WAITS|TOLERANCES)"
PARTS = (("Questions the agent answers", 4), ("Proactive help", 2), ("Out of scope", 1))
ENUM = {"detected", "processing", "awaiting_human_input", "sap_updated", "complete", "manual_review_required", "error"}
WAIT, HALT, NOTE = "without repeating the request", "To halt, and wherever the platform rules call for 'error'", "note of its next status change"
E0, REUSE = "Every escalation note MUST name the request, the contacts asked, the process type and the E-rule", re.compile(r"unless this run already holds (it|them)")
GUARD = ("IF the case already stood at 'complete' or 'manual_review_required'",
         "set the same status again", "set the same status again with the earlier reason")
NOMSG = ("this run brings no message or ticket decision at all", "MUST continue at STEP 2")
FRESH, PRE3 = "OTHERWISE the agent MUST continue at STEP 2 as a fresh run.", "the case status reads 'processing' during every run, so the case history and status reason show where the case last stood"
FIXED = {"L-1": ["It MUST NOT make a write that SOP does not name, even on approval, because only an SOP grants writes"], "C-1": ["from this case's data and SAP knowledge, without commitments or anything a P-clause forbids"],
         "Z-1": ["GUIDING PRINCIPLE: Everything outside this SOP's locked rules is the agent's to reason about", "When unsure whether an action is permitted, it MUST NOT act and MUST escalate per E-1"]}
RFC = re.compile(r"The key words \"MUST\".*?RFC 2119\.", re.S)
SYM = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")
CLAUSE = re.compile(r"^(\d{1,2}\.\d{1,2}|[A-Z]-\d{1,2}[a-z]?)\s{2,}(\S.*)$")
STATUS = re.compile(r"status\s+to\s+'([a-z_]+)'")
PAIR = re.compile(r"\{\{\w*VARIANCE_PCT\}\}(?:.|\n){0,200}?\{\{\w*(?:VARIANCE_UNITS|VARIANCE_ABS_USD)\}\}")
LETTER_IDS = r"MIRO|MIGO|MRBR|BSEG|BKPF|EKKO|EKPO|EKBE|RBKP|RSEG|LFBK|KNKK|VBAK|VBAP|MSEG|MKPF|ACDOCA|MATDOC"
BANNED = [("Q-R12", r"(?i)whichever is"), ("Q-R5", r"(?i)\bpoll|re-?read|reads? (it )?back"),
          ("Q-R15", r"(?i)timestamp|action_log|updated_at|inquiry_sent_at"),
          ("Q-R2", r"status to 'processing'|already (being )?processed|back off|\block\b"),
          ("Q-R10", r"(?i)\b(odata_\w+|load_sop|search_sap_\w+|\w+_case_state|send_notification|demo_\w+|get_precedent|check_vendor_risk|calculator)\b"),
          ("Q-R10", r"(?i)\b(create|raise|open)s?\s+(a\s+|the\s+)?ticket|ticket\s+(status|id)|quot(e|ing) the|try an alternative"),
          ("Q-R10", r"\bSTOP\b"), ("Q-B1", rf"\bA_[A-Z]\w+|\b\w+_SRV\b|\bAPI_[A-Z]\w*|\bBAPI|\bOData\b|\b[A-Z]{{2,4}}\d{{1,3}}[A-Z]?\b|\b({LETTER_IDS})\b"),
          ("Q-C2", r"\[ASSUMPTION"), ("Q-Z10", r"\b(CRITICAL|NEVER)\b"), ("Q-S6", r"<[^<>\s=][^<>]*>|\[(entry|focused)\]|YYYY")]
FOLD = str.maketrans({"\u201c": '"', "\u201d": '"', "\u2019": "'", "\u2014": "-", "\u00a0": " "})
norm = lambda t: " ".join(unicodedata.normalize("NFKC", t).translate(FOLD).casefold().split())
runtime = lambda t: SYM.sub("999999", re.sub(r"\{\{CONTACT_\w+\}\}", "x" * 40, t))
quotable = lambda n: len(n.split()) >= 6 and len(n) <= 320 and len(re.findall(r"[.!?](?:\s|$)", n)) <= 2
RUN = re.compile(r"Q-S2|Q-R1 |Q-R5|Q-R11 (\S+ undeclared|malformed)|Q-R12 (line|repo pair)|Q-R13 \S+ (no quotable|double)|Q-R6 \S+ sends|Q-R16|Q-R24")
section = lambda text, name: (re.search(rf"^{name}[^\n]*\n=+\n(.*?)(?=\n=+\n|\Z)", text, re.S | re.M) or re.match("()", "")).group(1)

ARGS = sys.argv[1:]; CONFIG = ARGS[ARGS.index("--config") + 1] if "--config" in ARGS else None
FILES = [a for i, a in enumerate(ARGS) if a not in ("--config", "--plain") and (i == 0 or ARGS[i - 1] != "--config")]
PLAIN = "--plain" in ARGS  # plain-procedure.md: plain fixed text, runtime-contract checks skipped, runtime literals fail
if PLAIN:
    HALT, PRE3 = "To halt, the agent MUST notify", "the agent can read the case history and any message or decision that started this run. a run starts on a new request or a reply on the case, and every reply and note is kept in the case history"
    E0, OUTCOME = "Every escalation note MUST name the request, the contacts asked and the E-rule. After sending an escalation, the agent MUST set the case to waiting for a reply with that note and end this run.", "IF SAP rejects the change, or the object in SAP does not then show the values written, the agent MUST halt per H-1"
    GUARD, RUN, NOTE = ("IF the case is already complete or in manual review", "leave the case in the same state", "leave the case in the same state with the earlier reason"), re.compile("(?!)"), "note of its next case state change"
    BANNED = BANNED + [("Q-P1", r"(?i)awaiting_human_input|manual_review_required|sap_updated|'(processing|error)'|status\s+(to\s+|reads\s+)?(processing|error)\b|\{\{|\}\}|process[_ ]type|config\.json|sync-kb|\bcdk\b")]
SKIP = re.compile(r"Q-R1 |Q-R3/R10|Q-R6 |Q-R11 (\S+ (undeclared|unused)|malformed)|Q-R16")
SERVICES = (__import__("json").load(open(CONFIG)).get("sap_service") or {}).get("services", []) if CONFIG else []
IMPORTS = [f.lower() for s in SERVICES for f in s.get("function_imports", {})]
OWNER = {e.get("name"): s.get("service") for s in SERVICES for e in s.get("entities", {}).values()} | {s.get("service"): s.get("service") for s in SERVICES}

def clauses(lines):
    out, cur, sec = [], None, ""
    for i, ln in enumerate(lines):
        if 0 < i < len(lines) - 1 and lines[i - 1] == lines[i + 1] == EQ: sec = ln
        m = CLAUSE.match(ln)
        if m: cur = [m.group(1), m.group(2), sec]; out.append(cur)
        elif cur and re.match(r"\s{2,}\S", ln): cur[1] += " " + ln.strip()
        else: cur = None
    return out

def check(path):
    text = open(path, encoding="utf-8").read(); lines = text.splitlines(); bad = []
    if lines[1:2] != ["STANDARD OPERATING PROCEDURE (SOP)"] or not re.match(r"^Version\s+\d+\.\d+$", (lines + ["", "", ""])[2]): bad.append("Q-S2 header lines 2-3")
    heads = [lines[i] for i in range(1, len(lines) - 1) if lines[i - 1] == lines[i + 1] == EQ]
    pos = [next((k for k, h in enumerate(heads) if h.startswith(o)), -1) for o in ORDER]
    if -1 in pos or pos != sorted(pos): bad.append("Q-S3 sections missing or out of order")
    summary = re.search(r"^Process summary \(informative; the clauses below decide\): (.*?)(?=\n\n)", section(text, "PURPOSE"), re.S | re.M)
    if not summary or len(summary.group(1).split()) > 40 or re.search(r"\b[A-Z]-\d|\b\d\.\d", summary.group(1)): bad.append("Q-S8 Process summary missing, over 40 words or citing IDs")
    if "[TO BE PROVIDED:" in text and "OPEN ITEMS" not in heads: bad.append("Q-C2 OPEN ITEMS section missing")
    rows = re.findall(r"(?m)^\|\s*(\d+\.\d+)\s*\|", section(text, "REVISION HISTORY"))
    if "Document owner:" not in text or not rows or rows[-1] != (lines + ["", "", ""])[2].split()[-1]: bad.append("Q-C3 Document owner or newest revision row version")
    if "@" in text: bad.append("Q-B2 '@' in the SOP")
    bad += [f"Q-Z1 {p} missing" for p in ("P-1", "P-2", "P-3") if not re.search(rf"(?m)^{p}\s", text)]
    if sum(bool(re.search(r"STEP \d+:", ln)) for ln in lines) != sum(h.startswith("STEP ") for h in heads): bad.append("Q-S4 'STEP N:' outside a banner")
    if re.search(r"(?m)^\d{1,2}\.\d{1,2}[a-z]\s", text): bad.append("Q-S4 letter-suffixed locator")
    if "are to be interpreted as described in RFC 2119." not in text: bad.append("Q-S5 RFC 2119 sentence")
    bad += [f"Q-S7 lowercase RFC 2119 keyword '{m.group(0)}'" for m in re.finditer(r"\b(must|shall|should|may)\b", RFC.sub("", text))]
    scope = re.search(r"^SCOPE\n=+\n(.*?)(?=\n=+\n)", text, re.S | re.M); sc = scope.span(1) if scope else (0, 0)
    if "ECC" in section(text, "PURPOSE") and "Business Partner" in text: bad.append("Q-G3 S/4HANA-only concept in an ECC SOP")
    writes = re.search(r"^Write:\s+(.*?)(?=\n\S)", section(text, "REQUIRED AGENT CAPABILITIES"), re.S | re.M)
    verbs = re.findall(r"\bMUST (release|post|cancel|reject|park|reverse|unblock)\b", text) if IMPORTS else []
    for w in (" ".join(writes.group(1).split()).split(";") if writes and IMPORTS else []) + [v + " (in a clause)" for v in dict.fromkeys(verbs)]:
        v = w.split()[0].lower() if w.split() else "none"
        if v not in ("none", "change", "update", "create", "add", "maintain") and not any(f.startswith(v[:4]) for f in IMPORTS): bad.append(f"Q-R16 Write '{w.strip()}' has no matching function import in sap_service")
    bad += [f"Q-R16 '{w}' " + (f"belongs to {OWNER[w]}, which this SOP does not name" if w in OWNER else "is not in sap_service")
            for w in dict.fromkeys(re.findall(r"\bA_[A-Z]\w+|\b\w+_SRV\b|\bAPI_[A-Z]\w*", text)) if SERVICES and OWNER.get(w, "?") not in text]
    for cid, p in BANNED:
        hits = [m for m in re.finditer(p, text) if not (cid == "Q-B1" and sc[0] <= m.start() < sc[1] and re.fullmatch(r"[A-Z]{2,4}\d{1,3}[A-Z]?", m.group(0)))]
        bad += [f"{cid} line {text.count(chr(10), 0, m.start()) + 1}: banned '{m.group(0)}'" for m in hits[:10]] + [f"{cid} {len(hits) - 10} more hits"] * (len(hits) > 10)
    if not all(x in norm(section(text, "PRECONDITIONS")) for x in (PRE3, "the agent has no memory of prior runs")): bad.append("Q-R17 PRECONDITIONS 2 or 3 missing or changed")
    cl = clauses(lines); ids = [c[0] for c in cl]
    bad += [f"Q-S4 {i} defined twice" for i in set(ids) if ids.count(i) > 1]
    for cid, b, sec in cl:
        n = norm(runtime(b))
        if not quotable(n): bad.append(f"Q-R13 {cid} " + ("too short to quote" if len(n.split()) < 6 else "long clause, a sentence is quotable" if any(map(quotable, re.split(r"(?<=[.;])\s", n))) else "no quotable sentence") + f" ({len(n)} chars)")
        if '"' in b: bad.append(f"Q-R13 {cid} double quote")
        if re.search(r"\b(e\.g|i\.e|etc|approx|vs)\.", b): bad.append(f"Q-R13 {cid} abbreviation")
        if re.search(r"\b(MUST|SHOULD) NOT\b", b) and not re.search(r"\b(because|since|to avoid)\b", b): bad.append(f"Q-Z12 {cid} prohibition without because")
        for s in STATUS.findall(b):
            if s not in {"sap_updated", "complete", "manual_review_required"} and not (s == "awaiting_human_input" and WAIT in b): bad.append(f"Q-R1 {cid} sets {s}")
        if re.search(r"'([a-z_]+)'", b) and not set(re.findall(r"'([a-z_]+)'", b)) <= ENUM: bad.append(f"Q-R1 {cid} unknown status literal")
        if "awaiting_human_input" in b and WAIT not in b or "'error'" in b and not b.startswith(HALT): bad.append(f"Q-R3/R10 {cid} names a platform-owned status")
        if "'error'" in b and not b.startswith(HALT) and re.search(r"(?i)write|post|release|reject|fail", b): bad.append(f"Q-R6 {cid} sends a failed write to 'error' (follows _platform_prompt.txt; fix: H-1, since the invoker replaces the reason)")
        if any(re.search(r"status to|halt per|escalate per", s) and re.search(r"\b(SHOULD|MAY)\b", s) for s in re.split(r"(?<=[.;])\s", b)): bad.append(f"Q-Z13 {cid} SHOULD/MAY on a status, halt or escalation")
        if re.search(r"(?i)\b\d+(\.\d+)?\s*(%|percent\b|days?\b|EUR\b|USD\b|units?\b)", b): bad.append(f"Q-Z6 {cid} literal value")
        if sec.startswith("STEP ") and re.search(r"_|\b[A-Za-z][a-z]+[A-Z]\w*\b", re.sub(r"'[a-z_]+'", "", SYM.sub("", b))): bad.append(f"Q-B3 {cid} field name in a step")
        s = [m for m in SYM.finditer(b) if not m.group(1).startswith("CONTACT_")]
        bad += [f"Q-R12 {cid} limits without AND/BOTH" for x, y in zip(s, s[1:]) if x.group(1) != y.group(1) and not re.search(r"\b(AND|BOTH)\b", b[x.end():y.start()])]
        if "'sap_updated'" in b and "already in the target state" not in b: bad.append(f"Q-R6 {cid} misses the target-state answer")
    s1 = [c for c in cl if c[2].startswith("STEP 1:")]; guards = [c for c in cl if GUARD[1] in c[1]]
    if len(guards) != 1 or len(s1) < 2 or s1[1] is not guards[0] or not guards[0][1].startswith(GUARD[0]) or GUARD[2] not in guards[0][1]: bad.append("Q-R22 closed-case clause missing, changed or not first after 1.1")
    if not s1 or s1[-1][1] != FRESH: bad.append("Q-R22 fresh-run clause missing or not last in STEP 1")
    bad += [f"Q-Z1 {c} fixed text changed" for c, t in FIXED.items() if not all(x in next((b for i, b, _ in cl if i == c), "") for x in t)]
    waits = [c for c in cl if WAIT in c[1]]; e0 = next((b for c, b, _ in cl if c == "E-0"), "")
    if len(waits) != 1 or not waits[0][1].endswith("a note per E-0.") or not e0.startswith(E0): bad.append("Q-R21 waiting clause / E-0")
    bad += [f"Q-R4 {c} has no 'on any other reply' branch" for c, b, _ in cl if re.fullmatch(r"E-\d+a", c) and "on any other reply" not in b]
    if not any(b.startswith(HALT) for _, b, _ in cl) or not any(NOTE in b for _, b, _ in cl): bad.append("Q-R3/R15 H-1 or note rule missing")
    bad += ["Q-R12 repo pair test" for m in PAIR.finditer(text) if "|" not in m.group(0) and not re.search(r"\b(AND|BOTH)\b", m.group(0))]
    tol, con, syms = section(text, LIMITS), section(text, "CONTACTS"), set(SYM.findall(text))
    if "- None." not in tol and "Policy owner:" not in tol: bad.append("Q-R11 LIMITS AND WAITS names no policy owner")
    wsyms = re.findall(r"(?m)^\|\s*Wait before[^|]*\|\s*\{\{(\w+)\}\}", tol)
    nm, wt = ([k for k, c in enumerate(s1) if f(c[1])] for f in (lambda b: all(x in b for x in NOMSG), lambda b: WAIT in b))
    if any(s.startswith("STEP ") and "{{%s}}" % w in b for w in wsyms for _, b, s in cl) and not (nm and wt and nm[0] < wt[0]):
        bad.append("Q-R24 a wait without the no-message STEP 1 clause before the waiting clause (V9)")
    bad += [f"Q-R11 {s} undeclared" for s in syms if "{{%s}}" % s not in (con if s.startswith("CONTACT_") else tol)]
    bad += [f"Q-R11 {s} unused" for s in set(SYM.findall(tol)) if text.count("{{%s}}" % s) < 2]
    if re.search(r"\{\{(?![A-Z][A-Z0-9_]*\}\})", text): bad.append("Q-R11 malformed placeholder")
    judg, lock = section(text, "AGENT JUDGMENT"), section(text, "LOCKED RULES"); parts = re.split(r"(?m)^(?=\S[^\n]*:$)", judg)
    for head, need in PARTS:
        got = sum(len(re.findall(r"(?m)^Z-\d+\s{2,}", s)) for s in parts if s.startswith(head))
        if got < need: bad.append(f"Q-Z22 AGENT JUDGMENT '{head}' has {got} examples, needs {need}")
    if len(re.findall(r"(?m)^P-\d+\s{2,}When ", lock.split("Tempting but prohibited:")[-1] if "Tempting but prohibited:" in lock else "")) < 2: bad.append("Q-Z22 fewer than 2 tempting-but-prohibited P-clauses")
    if PLAIN:  # plain-procedure.md: write outcome, escalation guards, SCOPE clause
        st = [c for c in cl if c[2].startswith("STEP ")]
        if any("changed in SAP" in b for _, b, _ in st) and not any(b.startswith(OUTCOME) for _, b, _ in st): bad.append("Q-P2 write-outcome clause missing")
        bad += [f"Q-P2 {c} sets changed in SAP early" for c, b, _ in st if "case to changed in SAP" in b and "shows the values written" not in b]
        bad += [f"Q-P3 {c} escalates per E-{n} without 'shows no E-{n} request'" for c, b, _ in st if "escalate per" in b for n in dict.fromkeys(re.findall(r"\bper E-(\d+)\b", b)) if n != "0" and f"no E-{n} request" not in b]
        if "In scope" in section(text, "SCOPE") and not any("SCOPE" in b and "halt per H-1" in b for _, b, s in st if s.startswith("STEP 3:")): bad.append("Q-P4 no STEP 3 clause cites SCOPE and halts per H-1")
    bad = [x for x in bad if not (PLAIN and SKIP.match(x))]
    print(f"{path}: {len(text.split())} words, {len(bad)} findings", *[f"\n  - {'[runtime] ' * bool(RUN.match(x))}{x}" for x in bad])
    return text, cl, bad

results = [check(p) for p in FILES]
entry = {" ".join(b.split()) for t, cl, _ in results if "ENTRY-POINT SOP" in t for _, b, _ in cl}
pair = [f"Q-Z15 {p} {c} not word for word in the entry point" for p, (t, cl, _) in zip(FILES, results) if entry and "ENTRY-POINT SOP" not in t
        for c, b, s in cl if s.startswith("STEP ") and SYM.search(b) and re.search(r"(ABOVE|WITHIN) (tolerance|the limit)", b) and " ".join(b.split()) not in entry]
pair += [f"Q-R20 {p} {c} recomputes without 'unless this run already holds it'" for p, (t, cl, _) in zip(FILES, results) if entry and "ENTRY-POINT SOP" not in t
         for c, b, s in cl if (c == "2.1" or s.startswith("STEP 3:") and "MUST compute" in b) and not REUSE.search(b)]
print(*[f"  - {x}\n" for x in pair], end="")
sys.exit(1 if pair or any(r[2] for r in results) else 0)
```

## Script items

The checker covers Q-S2 to Q-S8, Q-R1 to Q-R6, Q-R10 to Q-R13, Q-R15, Q-R17, Q-R20 to Q-R22, Q-R24, Q-B1 to Q-B3, Q-C2, Q-C3, Q-Z1, Q-Z6, Q-Z10, Q-Z12, Q-Z13, Q-Z15 and Q-Z22.

## Grep items

- Q-S1 the path follows `save-and-handoff.md`.
- Q-R8 a G6 correction is V2 with "instead of halting, because"; otherwise no rejection clause.
- Q-R11 with `skills/<domain>/config.json`, each symbol is in its constants or marked new in the hand-off.
- Q-Z1 Question and proactive clauses end "without …" or name who fixes the cause.
- Q-Z5 each Write verb matches exactly one STEP clause.
- Q-C3 the newest REVISION HISTORY row has today's date and the author.
- Q-G3 PURPOSE names the release.

## Enum items (yes or no per element)

- Q-R4 Per branch: does it end in continue-at, escalate, halt, a success status or the waiting clause, with no reply loop, no unconditional check skipped and no branch on a reply 1.3 takes first (T12), and do no-message runs reach the waits (V9)?
- Q-R7 Per write: does T9 hold, does a chained-control write test every control reply (V8) and an approved write the values approved (STEP 3)?
- Q-R9 Is 1.3 fixed, or V3 with "instead of halting, because", and does a refusal reach its status change with no SAP read, switch or notification (V3 excepted)?
- Q-R16 Per Read and Write: does `sap_service` match it, or does the hand-off carry the SAP access line?
- Q-R19 Per E-rule: one contact (T12), and does each citing branch end?
- Q-R23 Per STEP 2 read: does a rule, note or notification use it? Per rule: is its data read?
- Q-B1/B2 Per Q-B3 hit: a field name? Per capitalised two-word name outside REVISION HISTORY: a person?
- Q-S8 Could the document owner approve the Process summary and STEP 3 without help?
- Q-Z2 Per clause that notifies or tells: is it 5.x, H-1, an E-rule, 1.2, the waiting clause, a V3 1.3, L-1, a C-n or a Z-n clause?
- Q-Z4 Per branch reaching 'complete' or 'sap_updated': is every request this SOP made answered?
- Q-Z7 Per non-contact symbol in a clause: is its unit within 4 words (T8)?
- Q-Z8 Per notification: does T10 hold?
- Q-Z11 Per P-n: does no STEP or Z clause repeat it (T7)?
- Q-Z16 (entry point) Per focused STEP 3 branch: would the entry point classify it as its type? Per type pair where one can force the other: is there a precedence with a because?
- Q-Z18 Per MUST outside writes, halts, escalations and statuses: does T2 hold?
- Q-Z19 Per computed measure: is it defined on every case reaching it (zero base, partial document, sign, several lines), and derived once, never subtracting a value twice or counting what SAP already records? Per amount asked of a person: is its basis stated (to date or one period, as of when) fitting how the write reverses?
- Q-Z20 Per cause listed in the fit check, including each failed SAP check: does a STEP 3 clause decide it?
- Q-Z21 Per judgment clause: are evidence, outcomes, safe default and noted evidence named? Is there one wherever a person would weigh evidence?
- Q-Z23 Would a reader see room to think: are the AGENT JUDGMENT examples this process's own, SAP-realistic and answerable from case data, with only controls locked?
- Q-L1 Does the SOP keep the split rules of `sop-design.md`?
- Q-C1 Do the Write and Notify lines match the STEP clauses both ways?
- Q-G1 (this session) Does every value, rule and zone clause trace to an answer, document, accepted suggestion, default or listed derived rule, and was every conflict asked?

## Contract-check and review report

Run the checker once per domain, with `--config` where it exists; a runtime-only check without `--config` adds Q-R16 by hand, a review every enum item; offer the repo tests if present. Report one line per finding (file, ID, line, text, fix, severity: HIGH for a wrong money or master data outcome or a failed run, MEDIUM where the agent must guess or a citation fails, LOW for wording) in two groups:
- Breaks runtime: each `[runtime]` finding, with its note.
- Quality improvement: every other finding (missing template clauses are migration work).
One counted line per ID repeated across files.

Add per domain: "Set consistency: entry point in template style yes/no; focused SOPs n/m." Edit only when asked.
