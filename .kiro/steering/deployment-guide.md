---
inclusion: always
---

<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->
# Deployment Quick Reference

## First-Time Deploy

```bash
make setup
```

This walks you through: bootstrap (prereqs → config → CDK deploy → frontend) → SAP credentials → knowledge base sync → sample data (optional).

Or run each step individually:

```bash
cp cdk/config.yaml.example cdk/config.yaml   # edit: stack_name_base, admin_user_email
python scripts/setup.py                       # guided: prereqs → config → cdk deploy → frontend
make sync-sap-secret                          # sync SAP credentials to Secrets Manager
make sync-kb                                  # sync SOPs + API docs to S3
```

## Redeploy After Code Changes

```bash
make deploy-all
```

This runs CDK deploy, refreshes all Lambdas (so they pick up new SSM values), and redeploys the frontend.

## Credential Rotation

```bash
make sync-sap-secret                          # re-prompts for username/password
```

## Autonomy Controls (no redeploy needed)

```bash
make autonomy                                          # show current
make autonomy CMD="set trigger-mode auto"              # auto | manual
make autonomy CMD="set action-mode full-auto"          # full-auto | supervised | read-only
```

## Knowledge Base Updates

After editing files in `knowledge-base/sops/` or `knowledge-base/sap-api-docs/`:

```bash
make sync-kb                                  # sync all
./scripts/sync-knowledge-base.sh --sops-only  # SOPs only
./scripts/sync-knowledge-base.sh --docs-only  # API docs only
```

## Local Frontend Dev

```bash
make local-config                             # pull Cognito/backend values
cd frontend && npm install && npm run dev
```

## Available Make Targets

Run `make` to see all available targets grouped by category (Getting Started, Operations, Development, Code Quality).

## Key Config Values (cdk/config.yaml)

| Setting | What it controls |
|---------|-----------------|
| `stack_name_base` | Names all AWS resources, SSM paths, secrets |
| `sap.base_url` | SAP OData endpoint URL (poller service-account target) |
| `notification.channel` | `ses` / `slack` / `jira` / `servicenow` |
| `cedar_enforcement_mode` | `LOG_ONLY` / `ENFORCE` |
| `demo.enabled` | Opt-in test infrastructure (DDB tables, seeder, test data) |
