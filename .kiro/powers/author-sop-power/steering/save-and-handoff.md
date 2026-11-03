<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Save and Hand-off

Read before saving, and when asked to draft config.json or base_prompt.txt.

## Save path

1. Root: the only workspace folder; with several, the one that contains `knowledge-base/sops/`; otherwise ask "Which workspace folder should hold the SOP?".
2. If `<root>/knowledge-base/sops/` is a directory, save to `knowledge-base/sops/<domain>/<process_type>.txt`; otherwise to `sops/<domain>/<process_type>.txt`.
3. Names match `^[a-z][a-z0-9_]*$`: convert hyphens and capitals (`Block-Release` → `block_release`) and say so in one line; ask again for a value that cannot be converted.
4. If a `skills/*/config.json` already maps the process_type to another file, ask: replace that SOP (modification flow) or choose a new key.
5. If the file exists, ask: overwrite as a new version (bump Version, add a REVISION HISTORY row), save under a new process_type, or cancel.
6. Create missing folders and write UTF-8 with LF endings. On an error, report the path and the error and offer the SOP in chat.
7. Report the path(s), Version, checklist result and open-items count in plain words, then say: "Keep it as .txt, not PDF. Please read it and tell me what to change."

## Repo tests

If the workspace contains `tests/unit/test_sop_vocabulary.py`, offer once to run `pytest tests/unit/test_sop_vocabulary.py tests/unit/test_skill_router.py` (needs pytest, pyyaml, boto3), and run it only on a yes. Fix a failure the new SOP causes in the SOP. A test that pins the version of an SOP you changed fails by design after a bump: offer to update that one assertion. Report a failure that already existed, without fixing it.

## Hand-off note

Give it in chat, never in the SOP: at most 10 lines, only the lines that apply, no runtime investigation behind them.

```text
Integrator hand-off — <process>
1. File: <path> (Version <x.y>); copy it to knowledge-base/sops/<domain>/ if saved elsewhere.
2. Routing: skills/<domain>/config.json → process_type_to_sop "<process_type>": "<domain>/<process_type>.txt"[; a new domain also needs its config.json and base_prompt.txt, see docs/extending/ADDING_USE_CASES.md].
3. Constants: <SYMBOL> = <value | not yet provided> (new | existing), in that config.json → constants[; the waits in LIMITS AND WAITS need the case to run again while it waits].
4. Contacts: <key> = <address | not yet provided> in cdk/config.yaml and config.yaml.example[; <keys> must be different people].
5. SAP access: confirm your SAP service exposes each read and write: <business terms>.
6. [Configuration values: <name in business words> = <value | not yet provided>; pin each in config.json → sap_service or base_prompt.txt, because the SOP names them only in business words.]
7. [Open items: <TO BE PROVIDED markers>; do not deploy until each is filled in.]
8. Next: run the repo's SOP tests, then python3 launch.py sync-kb --only sops (and cdk deploy --all for new keys or contacts).
Want me to draft the skill's config.json or base_prompt.txt?
```

L7 applies because sync-kb, cdk deploy and AWS commands change shared AWS resources, and a bucket sync can delete objects.

## Drafting skill files (only when asked)

- `config.json` follows `docs/extending/ADDING_SKILLS.md` with the hand-off's values and `"max_turns": 15`; draft `sap_service` from SAP knowledge, marked "verify every service, entity, field and function import against your system", and pin each hand-off configuration value there or in `base_prompt.txt`.
- `base_prompt.txt` holds the persona for the confirmed release, `{PLATFORM_MECHANICS}`, domain pitfalls, the SOP banner and `{SOP_CONTENT}`, never platform text; a configuration value not pinned in `sap_service` goes under domain pitfalls.
