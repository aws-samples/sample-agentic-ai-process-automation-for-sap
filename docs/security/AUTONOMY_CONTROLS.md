<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Autonomy Controls Security

## Overview

The agent's autonomy is governed by a single SSM Parameter Store value — `trigger-mode` — that operators can flip without redeployment. `trigger-mode` controls whether the OData poller auto-enqueues detected cases for processing (`auto`) or waits for a human to trigger them from the UI/CLI (`manual`). Because flipping it to `auto` lets the agent begin processing without human initiation, unauthorized changes warrant the same integrity controls as any high-impact setting.

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

The autonomy Lambda is fronted by API Gateway with Cognito authorization — only authenticated operators can call it.

### 2. CloudTrail Logging

A CloudTrail trail captures all write management events (including `ssm:PutParameter`) and delivers them to:
- **S3 bucket** — `{stack}-cloudtrail-{account_id}`, 90-day lifecycle, SSL-enforced
- **CloudWatch Logs** — `/{stack}/cloudtrail`, 3-month retention

This provides an immutable audit trail of every autonomy parameter change, including who made the change, when, and from what IP.

### 3. CloudWatch Alarm

A metric filter on the CloudTrail log group matches `PutParameter` calls targeting `/{stack}/autonomy/*` parameters. When any match occurs, the `{stack}-autonomy-change` alarm fires and notifies the operator SNS topic.

The alarm fires on **any** change — even authorized ones. This is intentional: autonomy changes are rare and high-impact, so every change warrants operator awareness.

## Key Files

| File | Role |
|------|------|
| `cdk/lib/backend-stack.ts` (autonomy SSM param) | `trigger-mode` SSM parameter creation |
| `cdk/lib/backend-stack.ts` (autonomy Lambda) | Autonomy Lambda IAM policy |
| `cdk/lib/constructs/observability.ts` | CloudTrail trail, metric filter, alarm |
| `lambdas/autonomy_api/index.py` | Autonomy API handler (GET/PUT) |
| `scripts/ops/autonomy.sh` | CLI for operators (`make autonomy`) |
