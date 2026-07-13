<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Agent Instructions

Imperative instructions for AI coding agents (Claude Code, Kiro, Codex, etc.) deploying or working on this project.

## Deploy (golden path)

```bash
# 1. Prerequisites — must be done first
# - Node.js 20+, Python 3.12+, AWS CLI configured, AWS CDK CLI installed
# - Bedrock model access enabled for Claude models in your target region
#   (most common first-deploy failure — request at console.aws.amazon.com/bedrock → Model access)

# 2. First-time deploy (~20-30 min, mostly waiting on CDK)
make setup
# Interactive — requires two values:
#   stack_name_base: a short kebab-case name (max 35 chars)
#   admin_user_email: the email for the first Cognito user

# 3. Verify success
# The setup script prints a CloudFront URL at the end.
# Open it, log in with the admin email (check inbox for temp password), and send a message to the agent.
# If you see the chat UI and get a response, deploy succeeded.

# 4. Redeploy after code changes
make deploy-all
```

## Verify deployment

```bash
# CDK stacks deployed successfully:
aws cloudformation describe-stacks --query "Stacks[?contains(StackName,'erp')].{Name:StackName,Status:StackStatus}" --output table

# Agent runtime is healthy:
# Open the CloudFront URL (printed by setup, or find via `aws cloudformation describe-stacks`)
# Send any message — if you get a response, the agent is running.
```

## Common failures and fixes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ResourceNotFoundException` or model not found during agent invocation | Bedrock model access not enabled | Request Claude model access in the AWS Console → Bedrock → Model access |
| `CDKToolkit stack not found` or bootstrap error | CDK not bootstrapped in this account/region | `cdk bootstrap aws://ACCOUNT/REGION` |
| `npm ERR!` during CDK deploy | Missing Node dependencies | `cd cdk && npm install` |
| Frontend deploy fails with "no bucket" | CDK backend stack not yet deployed | Run `make deploy` first, then `make deploy-frontend` |
| Agent responds but can't reach SAP | SAP is optional; not configured | See `docs/sap/SAP_SETUP.md` — only needed for real SAP data |
| `ExpiredTokenException` | AWS session expired | Re-authenticate (`aws sso login` or refresh credentials) |

## Project conventions

- **IaC:** CDK is the primary path. Terraform exists but only supports `cognito-basic` auth.
- **Lambdas:** Every Lambda handler is `index.py` in its own `lambdas/<name>/` directory.
- **Skills:** Auto-discovered from `skills/<domain>/config.json`. Add a new domain by adding a directory — no agent code changes.
- **Config:** `cdk/config.yaml` is the single deployment config file. Copy from `cdk/config.yaml.example`.
- **Types:** Shared types live in `types/` and are auto-generated (`make generate-types`).
- **Tests:** `pytest` in `tests/`. Run with `make test`.
- **Lint:** `make pre-commit` runs ruff + ESLint + Prettier.
- **Build validation:** `make validate` runs lint + CDK synth.

## Key files for common tasks

| Task | Start here |
|------|-----------|
| Change agent behavior | `agentcore/agent/basic_agent.py`, `skills/*/config.json` |
| Add a new use case (domain) | `docs/extending/ADDING_USE_CASES.md` — end-to-end: poller + skill + schema + frontend |
| Add a skill (new process type) | `docs/extending/ADDING_SKILLS.md` — config.json + base_prompt + SOPs only |
| Add a Gateway tool | `agentcore/gateway/tools/<new-tool>/` — handler.py + tool_spec.json |
| Change infrastructure | `cdk/lib/` — `main-stack.ts` orchestrates |
| Change frontend | `frontend/src/routes/` |
| Deployment config | `cdk/config.yaml` |
| SAP connection | `docs/sap/SAP_SETUP.md` |
| Auth profiles | `auth-profiles.yaml` + `docs/sap/AUTH_PROFILE_SELECTION.md` |

## Do not modify

- `docs/design-decisions/` — ADRs are append-only records; don't edit existing ones
- `knowledge-base/sops/` — SOPs are authored deliberately (RFC 2119 language); don't rewrite casually
