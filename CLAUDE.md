<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Agent Instructions

Imperative instructions for AI coding agents (Claude Code, Kiro, Codex, etc.) deploying or working on this project.

## Deploy (golden path)

```bash
# 1. Prerequisites — must be done first
# - Node.js 20+, Python 3.10+, AWS CLI configured, git
#   (no global CDK install needed — the pinned version comes from cdk/package.json)
# - Bedrock model access enabled for Claude models in your target region
#   (most common first-deploy failure — request at console.aws.amazon.com/bedrock → Model access)

# 2. Check readiness first — read-only, changes nothing
python3 launch.py doctor

# 3. First-time deploy (~20-30 min, mostly waiting on CDK)
python3 launch.py
# Interactive — requires two values:
#   stack_name_base: a short kebab-case name (max 35 chars)
#   admin_user_email: the email for the first Cognito user
# Nothing is written to AWS until it shows the target account/Region and you confirm.

# 4. Verify success
# The launcher prints the application URL at the end.
# Open it, log in with the admin email (check inbox for temp password), and send a message to the agent.
# If you see the chat UI and get a response, deploy succeeded.
# `python3 launch.py status` reports the same thing later.

# 5. Redeploy after code changes
python3 launch.py deploy        # --yes goes before the command: launch.py --yes deploy

# 6. If a deploy is interrupted
python3 launch.py resume
```

## Verify deployment

```bash
# CDK stacks deployed successfully:
aws cloudformation describe-stacks --query "Stacks[?contains(StackName,'erp')].{Name:StackName,Status:StackStatus}" --output table

# Agent runtime is healthy:
# Open the application URL (printed by the launcher, or run `python3 launch.py status`)
# Send any message — if you get a response, the agent is running.
```

## Common failures and fixes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ResourceNotFoundException` or model not found during agent invocation | Bedrock model access not enabled | Request Claude model access in the AWS Console → Bedrock → Model access |
| `CDKToolkit stack not found` or bootstrap error | CDK not bootstrapped in this account/region | `python3 launch.py deploy` bootstraps first, or run `cd cdk && npx cdk bootstrap` |
| `npm ERR!` during CDK deploy | Missing Node dependencies | `cd cdk && npm ci` |
| Frontend deploy fails with "no bucket" | CDK backend stack not yet deployed | Run `python3 launch.py infra` first, then `python3 launch.py frontend` |
| Agent responds but can't reach SAP | SAP is optional; not configured | See `docs/sap/SAP_SETUP.md` — only needed for real SAP data |
| `ExpiredTokenException` | AWS session expired | Re-authenticate (`aws sso login` or refresh credentials) |

## Project conventions

- **IaC:** CDK is the primary path. Terraform exists but only supports `cognito-basic` auth.
- **Lambdas:** Every Lambda handler is `index.py` in its own `lambdas/<name>/` directory.
- **Skills:** Auto-discovered from `skills/<domain>/config.json`. Add a new domain by adding a directory — no agent code changes.
- **Config:** `cdk/config.yaml` is the single deployment config file. Copy from `cdk/config.yaml.example`.
- **Entry points:** `python3 launch.py` deploys and operates the sample; `make` is contributor tooling (lint, tests, types, packaging). Make's deploy targets delegate to the launcher — never a second implementation.
- **Types:** Shared types live in `types/` and are auto-generated (`make generate-types`).
- **Tests:** `pytest` in `tests/`. Run with `make test`.
- **Lint:** `make pre-commit` runs ruff + ESLint + Prettier.
- **Build validation:** `make validate` runs lint + CDK synth.
- **Security scan:** Every dependency and static-analysis finding is classified before it is dismissed. Fix the real ones; a suppression names the control that makes the finding safe, is scoped to the file it was read in, and carries an expiry. Never blanket-suppress a rule.
- **Finishing a branch:** Before merging or opening a PR, a branch clears the same gates every time: the work it set out to do is actually finished, it has been deployed and exercised live, the docs match the diff, the security scan is clean, and any new threat surface is written down.

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
