<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Contributing

## First-Time Setup

See the [Deployment Guide](DEPLOYMENT.md) for full prerequisites and deployment instructions. The fastest path:

```bash
make setup
```

This walks you through bootstrap, SAP credentials, and knowledge base sync interactively.

After setup, install the pre-commit hook:

```bash
make install-hooks
```

This auto-generates types, lints, and formats before every commit.

## Day-to-Day Development

Run `make` to see all available targets. Common ones:

| Task | Command |
|------|---------|
| Full redeploy | `make deploy-all` |
| Deploy CDK only | `make deploy` |
| Deploy frontend only | `make deploy-frontend` |
| Refresh Lambdas (after CDK deploy) | `make refresh-lambdas` |
| Sync SOPs / API docs | `make sync-kb` |
| Sync SAP credentials | `make sync-sap-secret` |
| Check autonomy controls | `make autonomy` |
| Set autonomy | `make autonomy CMD="set trigger-mode auto"` |

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
make autonomy CMD="set trigger-mode auto"             # auto | manual
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
│   ├── webhook_processor/           # Unified inbound (SES/Slack/Jira/ServiceNow)
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
│   └── src/routes/                  # WorkspacePage, AnalyticsDashboard,
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
├── scripts/                          # Deployment and operational scripts
│   ├── setup.py                      # First-time guided setup wizard
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
