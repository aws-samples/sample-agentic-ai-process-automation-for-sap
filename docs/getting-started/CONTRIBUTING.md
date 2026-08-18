<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Contributing

## First-Time Setup

See the [Deployment Guide](DEPLOYMENT.md) for full prerequisites and deployment instructions. The fastest path:

```bash
python3 launch.py
```

This walks you through prerequisites, config, deploy, frontend, and the optional SAP and knowledge base steps.

After setup, install the pre-commit hook:

```bash
make install-hooks
```

This auto-generates types, lints, and formats before every commit.

## Two entry points

| | Use it for | Needs |
|---|---|---|
| `python3 launch.py` | Deploying and operating the sample | Python only |
| `make` | Lint, tests, type generation, packaging | GNU make |

Make's deploy and operate targets delegate to the launcher, so they are aliases rather than a second implementation. Use whichever you prefer.

## Day-to-Day Development

Run `make` to see every target, or `python3 launch.py --help` for the deploy and operate side. Common ones:

| Task | Command | Make alias |
|------|---------|------------|
| Full redeploy | `python3 launch.py deploy` | `make deploy-all` |
| Deploy CDK only | `python3 launch.py infra` | `make deploy` |
| Deploy frontend only | `python3 launch.py frontend` | `make deploy-frontend` |
| Refresh Lambdas (after CDK deploy) | `python3 launch.py refresh` | `make refresh-lambdas` |
| What is deployed right now | `python3 launch.py status` | `make status` |
| Continue an interrupted deploy | `python3 launch.py resume` | — |
| Sync SOPs / API docs | `python3 launch.py sync-kb` | `make sync-kb` |
| Sync SAP credentials | `python3 launch.py sync-sap` | `make sync-sap-secret` |
| Check autonomy controls | `python3 launch.py autonomy` | `make autonomy` |
| Set autonomy | `python3 launch.py autonomy set auto` | `make autonomy CMD="set auto"` |

Deploy commands confirm the target account and Region before writing anything. Pass `--yes` to skip that for unattended runs, or `make deploy-all LAUNCH_ARGS=--yes` through Make.

### Local Frontend

See [Local Development](LOCAL_DEVELOPMENT.md) for Docker Compose setup. For quick frontend-only dev:

```bash
make local-config   # pull Cognito/backend values from deployed stacks
cd frontend && npm install && npm run dev
```

Re-run `make local-config` after any infrastructure redeployment.

### Updating SOPs or API Docs

Edit files in `knowledge-base/sops/` or `knowledge-base/sap-api-docs/`, then sync:

```bash
make sync-kb
```

### Updating SAP Credentials

```bash
make sync-sap-secret
```

### Autonomy Controls

```bash
make autonomy                                         # show current settings
make autonomy CMD="set auto"             # auto | manual
```

## Before Submitting

Run the full pre-commit check:

```bash
make pre-commit
```

This runs type generation, ruff (lint + format), ESLint, and Prettier. For a heavier check that includes CDK synth:

```bash
make validate
```

## Coding Conventions

- Run `make install-hooks` after cloning (auto-generates types, lints, formats before every commit)
- Add docstrings to every function
- Use explicit types in method signatures
- Follow conventions in `.kiro/steering/coding-conventions.md`

## Project Layout

```
├── agentcore/                       # Everything that runs inside AgentCore
│   ├── agent/                       # Primary agent (Strands SDK)
│   │   ├── basic_agent.py           # Agent entry point + skill routing
│   │   ├── Dockerfile
│   │   └── utils/                   # Shared agent utilities
│   │       ├── skill_router.py      # Maps process_type → SOP + prompt
│   │       ├── specialist.py        # Sonnet specialist agent-as-tool
│   │       └── agent_metrics.py     # CloudWatch metrics emission
│   ├── gateway/                     # AgentCore Gateway
│   │   ├── tools/                   # Gateway Lambda tools (SAP OData served via the external SAP MCP target)
│   │   │   ├── case_management/     # DynamoDB case state
│   │   │   ├── notification/        # Multi-channel notifications
│   │   │   ├── knowledge_base/      # Bedrock KB search
│   │   │   └── demo_ticket_management/  # Demo ticket CRUD (gated on demo.ticketing.enabled)
│   ├── policies/                    # Cedar authorization policies (sap_agent_policies.cedar)
│   └── evals/                       # Regression evaluation suite
├── lambdas/                         # All Lambda functions (handler is index.py everywhere)
│   ├── layers/sap_auth/             # Shared SAP auth layer (service-account)
│   │                                # ── Event processors ──
│   ├── odata_poller/                # SAP polling (EventBridge) — only component that calls SAP directly
│   ├── webhook_processor/           # Unified inbound (SES/Jira/ServiceNow)
│   ├── agent_invoker/               # SQS consumer → AgentCore Runtime
│   ├── exemplar_builder/            # Evaluation exemplar generation
│   │                                # ── REST APIs (*_api) ──
│   ├── cases_api/                   # Cases dashboard API
│   ├── autonomy_api/                # Autonomy controls API
│   ├── feedback_api/                # Feedback API
│   ├── observability_api/           # Agent metrics API
│   │                                # ── CloudFormation custom resources (*_cr) ──
│   ├── policy_engine_cr/            # Cedar policy engine provisioning
│   ├── oauth2_provider_cr/          # OAuth2 credential provider provisioning
│   ├── zip_packager_cr/             # Agent code ZIP packaging
│   │                                # ── Demo (independent gates) ──
│   ├── demo_tickets/                # Demo tickets API (gated on demo.ticketing.enabled; incl. approve/deny→SQS action route)
│   └── demo_test_data/              # Demo test-data API (gated on demo.test_data.enabled)
├── skills/                          # Domain skill definitions
│   ├── example_finance_accruals/    # PO accruals, WBS accruals (example domain)
│   └── finance_ap/                  # AP invoice matching
├── knowledge-base/                  # Knowledge content (synced to S3)
│   ├── sops/                        # Standard Operating Procedures
│   ├── sap-api-docs/                # SAP API documentation
│   └── prompt-templates/            # SOP authoring prompts (RFC 2119)
├── frontend/                        # React app (Amplify Hosting)
│   └── src/routes/                  # WorkspacePage, AnalyticsDashboard, SettingsPage,
│                                     # TicketsDashboard, TestDataPage, SapAuthCallback
├── cdk/                              # CDK infrastructure (primary)
│   ├── config.yaml                  # Deployment configuration
│   ├── bin/app.ts                   # CDK app entry point
│   └── lib/
│       ├── main-stack.ts             # Orchestrator: wires the stacks together
│       ├── backend-stack.ts          # Gateway, Runtime, event pipeline
│       └── sap-mcp-stack.ts          # Adapter to the external SAP MCP server (ADR-012)
├── terraform/                        # Terraform alternative (cognito-basic only; auth profiles are CDK-only)
├── types/                            # Shared type definitions (Python + TypeScript generated)
├── tests/                            # Pytest unit/integration tests
├── test-scripts/                     # Manual integration test scripts
├── launch.py                         # Deploy and operate the sample (primary entry point)
├── launcher/                         # Launcher implementation: one module per subcommand
├── scripts/                          # Deployment and operational scripts
│   ├── setup.py                      # Superseded by `python3 launch.py`; kept until the launcher is validated in CI
│   ├── sync-sap-secret.sh           # Sync SAP credentials to Secrets Manager
│   ├── sync-knowledge-base.sh       # Sync SOPs + API docs to S3
│   ├── deploy/                       # deploy-frontend.py, deploy-with-codebuild.py
│   ├── dev/                          # generate-types.sh, local-dev.sh, pre-commit.sh
│   ├── ops/                          # autonomy.sh, setup-ses-domain.sh
│   └── data/                         # setup_evaluations.py
├── docker/                           # Docker compose for local dev
└── docs/                             # Project documentation (start at docs/README.md)
```

See [scripts/README.md](../../scripts/README.md) for all available scripts and their locations.

## Support

Open an issue in the [GitHub issue tracker](https://github.com/aws-samples/agentic-erp-automation-quick-start/issues).
