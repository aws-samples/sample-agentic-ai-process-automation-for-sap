<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Autonomy Controls Security

## Overview

The agent's autonomy is governed by a single SSM Parameter Store value — `trigger-mode` — that operators can flip without redeployment. `trigger-mode` controls whether cases are auto-enqueued for processing (`auto`) or wait for a human to trigger them from the UI/CLI (`manual`). It gates *every* unattended enqueue path, not only the OData poller: a `mode: batch` profile also provisions a scheduled sweeper (`lambdas/batch_runner/`) that reads the same parameter and is a no-op under `manual`. Because flipping it to `auto` lets the agent begin processing without human initiation, unauthorized changes warrant the same integrity controls as any high-impact setting.

> **Write enforcement (sample code).** `trigger-mode` governs *initiation*, not SAP writes. This sample does not ship a runtime `action-mode` write kill-switch — an earlier build enforced one via a Gateway request interceptor, which was removed along with the `action-mode` SSM parameter. SAP write gating now lives in the Cedar policies at the Gateway (role-based permits; `odata_delete` forbidden) and in the external AWS-for-SAP MCP server (`MCP_SERVER_WRITE_ENABLED` + per-op knobs). See threats T6/T15 for the accepted-risk rationale and production guidance.

## Threat Model Reference

This implementation addresses the SSM autonomy-parameter mitigation from the threat model (threat T7):

> Restrict SSM Parameter Store write access for autonomy controls to authorized operator roles only. Enable CloudTrail logging for all SSM PutParameter calls. Implement CloudWatch alarm on autonomy parameter changes.

Mitigates threat **T7** (flipping `trigger-mode` to `auto` to start autonomous processing without authorization).

## Controls

### 1. SSM Write Restriction (IAM)

Only the dedicated autonomy Lambda has `ssm:PutParameter` on the autonomy parameters. All other Lambdas and the agent runtime have `ssm:GetParameter` only.

| Component | SSM Actions | Scope |
|-----------|-------------|-------|
| Autonomy Lambda | GetParameter + PutParameter | `/{stack}/autonomy/*` |
| All other Lambdas | GetParameter | `/{stack}/*` |
| Agent Runtime role | GetParameter | `/{stack}/*` |

The autonomy Lambda is fronted by API Gateway with Cognito authorization — only authenticated operators can call it. Note the scope of that check: any authenticated user can flip the mode. The UI's typed-`AUTO` confirmation guards against accident, not against an unauthorized operator, and must not be read as an authorization control.

`PUT /autonomy` is mounted only on deployments whose auth profile declares `autonomous`. The `trigger-mode` parameter is seeded regardless, so `auto` can be stored on a deployment with no poller to honour it; `GET /autonomy` returns `autonomous-capable` in the same payload as the mode so a caller cannot report a stored `auto` as live unattended processing. The flag derives from the same condition that mounts the PUT, so the two cannot disagree.

### 2. CloudTrail Logging

> **Opt-in.** Set `security.audit_trail_enabled: true` in `cdk/config.yaml`. It defaults to **off**, alongside `waf_enabled` and `guardrail_enabled`, because CloudTrail allows only **5 trails per Region** and that is a hard AWS limit, not a raisable quota. Creating one per deployment caps how many copies of this sample can coexist in a Region and fails the backend stack outright once the account is at the limit. Turn it on in the environment you actually audit; leave it off for sample and test deployments.

When enabled, a CloudTrail trail captures all write management events (including `ssm:PutParameter`) and delivers them to:
- **S3 bucket** — `{stack}-cloudtrail-{account_id}`, 90-day lifecycle, SSL-enforced
- **CloudWatch Logs** — `/{stack}/cloudtrail`, 3-month retention

This provides an immutable audit trail of every autonomy parameter change, including who made the change, when, and from what IP.

If your account already has an organization-wide trail — a Control Tower landing zone provides one — that trail already captures these events, and the alarm below is the only thing this adds.

### 3. CloudWatch Alarm

A metric filter on the CloudTrail log group matches `PutParameter` calls targeting `/{stack}/autonomy/*` parameters. When any match occurs, the `{stack}-autonomy-change` alarm fires and notifies the operator SNS topic. It is created only when `security.audit_trail_enabled` is on, since it has no data source without the trail.

The alarm fires on **any** change — even authorized ones. This is intentional: autonomy changes are rare and high-impact, so every change warrants operator awareness.

## Key Files

| File | Role |
|------|------|
| `cdk/lib/backend-stack.ts` (autonomy SSM param) | `trigger-mode` SSM parameter creation |
| `cdk/lib/backend-stack.ts` (autonomy Lambda) | Autonomy Lambda IAM policy |
| `cdk/lib/constructs/observability.ts` | CloudTrail trail, metric filter, alarm (gated on `security.audit_trail_enabled`) |
| `cdk/test/observability-audit-trail.test.ts` | Pins the trail's opt-in behaviour in both states |
| `lambdas/autonomy_api/index.py` | Autonomy API handler (GET/PUT), including `autonomous-capable` |
| `frontend/src/components/AutonomyGovernor.tsx` | Operator control and outcome readout (Settings) |
| `python3 launch.py autonomy` | CLI for operators (also `make autonomy`) |
