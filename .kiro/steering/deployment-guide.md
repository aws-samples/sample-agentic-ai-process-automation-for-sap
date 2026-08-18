---
inclusion: always
---

<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->
# Deployment Quick Reference

Two entry points, with distinct jobs:

- **`python3 launch.py`** — deploy and operate the sample. Standard library only, so it runs on a clean clone before anything is installed.
- **`make`** — contributor tooling: lint, tests, type generation, packaging. Its deploy and operate targets delegate to the launcher, so they are aliases and never a second implementation.

## First-Time Deploy

```bash
python3 launch.py doctor                      # check prerequisites and AWS access; changes nothing
python3 launch.py                             # guided launch
```

The guided flow is: environment check → config → confirm the target account/Region → CDK deploy → Lambda refresh → frontend → optional SAP credentials → optional knowledge base. Nothing is written to AWS before the confirmation, which defaults to no.

Or run each step individually:

```bash
python3 launch.py configure                   # generate cdk/config.yaml
python3 launch.py infra                       # CDK bootstrap + deploy
python3 launch.py frontend                    # build and deploy the frontend
python3 launch.py sync-sap                    # sync SAP credentials to Secrets Manager
python3 launch.py sync-kb                     # publish SOPs + API docs, start ingestion
```

## Redeploy After Code Changes

```bash
python3 launch.py deploy                      # add --yes for unattended runs
```

This deploys the CDK stacks, refreshes all Lambdas (so they pick up new SSM values), and redeploys the frontend. It confirms the target account and Region first.

## Status and Recovery

```bash
python3 launch.py status                      # deployed stacks, endpoints, failure causes
python3 launch.py resume                      # continue an interrupted launch
python3 launch.py diff                        # pending CDK changes, including IAM
```

`resume` re-queries CloudFormation before skipping anything, so a stale `.launcher/state.json` cannot cause a wrong skip.

## Credential Rotation

```bash
python3 launch.py sync-sap --force            # re-prompts for username/password
python3 launch.py sync-channel --force        # webhook signing secret
```

Passwords are read without echo and never reach a config file, the state file, a log, or a process argument list.

## Autonomy Controls (no redeploy needed)

```bash
python3 launch.py autonomy                    # show current
python3 launch.py autonomy set auto           # auto | manual
```

`trigger-mode` is the only runtime toggle — it gates poller auto-enqueue, not SAP writes.

## Knowledge Base Updates

After editing files in `knowledge-base/sops/` or `knowledge-base/sap-api-docs/`:

```bash
python3 launch.py sync-kb                     # both corpora
python3 launch.py sync-kb --only sops         # SOPs only
python3 launch.py sync-kb --only api-docs     # API docs only
```

The sync shows exactly which bucket objects have no local counterpart and requires a separate confirmation before deleting them. `--yes` cannot satisfy that confirmation.

## Local Frontend Dev

```bash
make local-config                             # pull Cognito/backend values
cd frontend && npm install && npm run dev
```

## Command Reference

- `python3 launch.py --help` — every deploy and operate command
- `make` — every contributor target, grouped by category

## Key Config Values (cdk/config.yaml)

| Setting | What it controls |
|---------|-----------------|
| `stack_name_base` | Names all AWS resources, SSM paths, secrets |
| `sap.base_url` | SAP OData endpoint URL (poller service-account target) |
| `notification.channel` | `ses` / `jira` / `servicenow` |
| `cedar_enforcement_mode` | `LOG_ONLY` / `ENFORCE` |
| `demo.enabled` | Opt-in test infrastructure (DDB tables, seeder, test data) |
