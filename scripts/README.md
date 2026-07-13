<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Scripts

Most scripts are also available as Makefile targets — run `make` to see all available targets.

## Getting Started

The fastest way to get started is the guided setup:

```bash
make setup
```

This walks you through bootstrap, SAP credentials, and knowledge base sync interactively.

Or run the setup wizard directly for a guided first-time setup:

```bash
python scripts/setup.py
```

After deployment, sync SAP credentials:

```bash
make sync-sap-secret
# or: ./scripts/sync-sap-secret.sh
```

And sync knowledge base content (SOPs + API docs):

```bash
make sync-kb
# or: ./scripts/sync-knowledge-base.sh
```

## Directory Layout

```
scripts/
├── setup.py                  # First-time guided setup wizard (config → deploy → frontend)
├── sync-sap-secret.sh        # Sync SAP credentials from config.yaml to Secrets Manager
├── sync-knowledge-base.sh    # Sync SOPs + API docs to S3 and trigger KB re-ingestion
├── utils.py                  # Shared Python utilities
├── requirements.txt          # Python deps for scripts
│
├── deploy/                   # Deployment scripts
│   ├── deploy-frontend.py    # Build + deploy frontend to Amplify
│   └── deploy-with-codebuild.py  # Full stack deploy via ephemeral CodeBuild project
│
├── dev/                      # Local development
│   ├── generate-types.sh     # Generate TS + Python types from JSON Schema
│   ├── local-dev.sh          # Start agent container + frontend dev server (or `config` to just write aws-exports.json)
│   ├── pre-commit.sh         # Git pre-commit hook (installed via `make install-hooks`)
│   └── setup-container-runtime.sh  # Detect Docker/Finch (only needed for deployment_type: docker)
│
├── ops/                      # Operational scripts
│   ├── autonomy.sh           # Flip trigger-mode without redeployment
│   └── setup-ses-domain.sh   # SES domain identity setup (DKIM, MX, config.yaml)
│
└── data/                     # Sample data and evaluation setup
    └── setup_evaluations.py   # Configure online evaluation settings
```

## Common Tasks

| Task | Make target | Script |
|------|-------------|--------|
| First-time setup | `make setup` | `python scripts/setup.py` |
| Full redeploy | `make deploy-all` | CDK deploy + refresh Lambdas + frontend |
| Deploy CDK only | `make deploy` | `cd cdk && cdk deploy --all` |
| Deploy frontend only | `make deploy-frontend` | `python scripts/deploy/deploy-frontend.py` |
| Refresh Lambdas | `make refresh-lambdas` | — |
| Sync SAP credentials | `make sync-sap-secret` | `./scripts/sync-sap-secret.sh` |
| Sync knowledge base | `make sync-kb` | `./scripts/sync-knowledge-base.sh` |
| Check/set autonomy | `make autonomy` | `./scripts/ops/autonomy.sh get` |
| Local frontend dev | `make local-config` | `./scripts/dev/local-dev.sh config` |
| Local agent + frontend | `make local-dev` | `./scripts/dev/local-dev.sh` |
| Deploy via CodeBuild | — | `python scripts/deploy/deploy-with-codebuild.py` |
| Set up SES domain | — | `./scripts/ops/setup-ses-domain.sh <domain>` |
