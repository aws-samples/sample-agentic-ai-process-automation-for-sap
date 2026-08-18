<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Changelog

All notable changes to the Agentic ERP Automation Quickstart will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.0.0] — 2026-08-18

### Changed

- **The queued path derives its AgentCore session id from the case.** `agent_invoker`
  minted a throwaway `sqs-{timestamp}-{uuid}`, making it the one caller that discarded
  the case identity the codec provides. It now calls `to_runtime_session_id(case_id)`,
  the same helper the agent's own fallback and the frontend's TypeScript twin use, and
  falls back to a disposable id only when the producer sent no usable `case_id`. Traces
  for a case now group under one `session.id` instead of one per invocation. This does
  not yet share a Memory session with interactive chat — Memory also keys on `actor_id`,
  which differs for a machine-authenticated run.

- **Live-only auth profiles no longer provision the autonomous path.** A profile whose
  mode axis omits `autonomous` (today `entra-obo`, where the outbound flow needs a live
  human to mint the SAP credential) used to fail CDK synth outright. It now deploys
  without the OData poller schedule, SQS FIFO queue, agent invoker, `/autonomy` PUT, or
  the SQS grants that only exist to feed them. Terraform cannot withhold that pipeline,
  so selecting such a profile there now fails at plan time with the reason, alongside
  the existing CDK-only axis checks.

- **BREAKING — the cases table is now keyed on `case_id` alone.** Case identity is a
  single canonical string, `{document_number}-{item_id}` (e.g. `5100001976-2026`), built
  and read only through the `case_key` codec (`lambdas/layers/shared_types/case_key.py`,
  mirrored at `agentcore/agent/utils/case_key.py`, TypeScript twin at
  `frontend/src/lib/caseKey.ts`). `document_number` and `item_id` remain attributes —
  SAP calls and the UI need them — but they are no longer identity.

  Previously the same case was encoded five different ways: the composite table key,
  `doc#item` on the wire, `doc-item` for the UI enqueue's FIFO group, `doc/item` in trace
  records, and `doc%23item` in a hand-built link. Restricting each segment to
  `[A-Za-z0-9_]` makes a single `-` split lossless and leaves the id legal, unescaped, in
  a URL, an SQS `MessageGroupId`, and an AgentCore Memory actor/session id.

  Related fixes: the enqueue integration no longer rewrites the separator for its FIFO
  group, so a UI-triggered run and a background run for the same case are finally
  serialized in the same message group; and session ids derived from a case now clear
  AgentCore Runtime's 33-character minimum.

  Also changed:
  - `GET /cases/{doc}/{item}` → `GET /cases/{case_id}` (likewise `/traces`, `/rating`).
  - `get_case_state` / `update_case_state` take `case_id`. `document_number` + `item_id`
    are still accepted so a copied skill keeps working.
  - `case_id` is required in `types/cases.schema.json`.
  - The `shared_types` layer is now attached to `agent_invoker`, `webhook_processor` and
    `observability_api`, which previously lacked it.

  **Migration.** The key schema change replaces the DynamoDB cases table, so its
  contents do not survive. In CDK the table is now deliberately *unnamed*: a custom
  physical name makes any future key change undeployable, because CloudFormation refuses
  to replace a custom-named resource at all — it creates the replacement before deleting
  the original, and the two would collide on the name. Deleting the old table first does
  not help; the refusal is based on the template diff, not on whether the table exists.
  Deploying this change therefore creates a fresh, generated-name table and leaves the
  old `{stack}-cases` table behind for you to delete once you no longer need it. Nothing
  read that literal name — consumers resolve it from
  `/{stack}/dynamodb/cases-table` in SSM or an injected `CASES_TABLE` env var.

  To carry data across, export before deploying and re-import after, adding `case_id`
  to each item; otherwise the poller re-detects open exceptions from SAP on its next
  run, which is the intended path for a demo deployment. Legacy `doc#item` and `doc/item`
  values are still accepted on *read* (stored tickets, replies to older notification
  emails), so correlation survives even where an old id is quoted back.

  API Gateway has the same create-before-delete constraint: `/cases/{case_id}` cannot be
  created while `/cases/{doc}` still exists, since a parent resource allows only one
  variable path part. Delete the old `{doc}` resource (it cascades to its children)
  before deploying, or deploy the route removal and the route addition as two updates.

### Fixed

- The SAP MCP Service target was dropped whenever the outbound axis was `basic` with
  `sap_mcp` enabled. `basic` describes only the external MCP server's own hop to SAP;
  the Gateway still reaches that server with OAuth2 client credentials and needs the
  target.

## [1.0.0] — 2026-06-30

First public release.

The Agentic ERP Automation Quickstart is production-grade starter code for autonomous AI agents
that automate ERP exception handling. It demonstrates one opinionated end-to-end path — supplier
invoice three-way-match exceptions (`finance_ap`) — built on Amazon Bedrock AgentCore, and is
designed to be forked, understood, and extended.

### Added

- **Autonomous exception-handling agent** built on Amazon Bedrock AgentCore Runtime using the
  Strands agent framework, with a domain-agnostic skill router that loads domain expertise and
  Standard Operating Procedures (SOPs) at runtime — new domains can be wired in without agent code
  changes.
- **AgentCore Gateway with Lambda-backed tools** (case management, knowledge base, notifications)
  providing a clean separation between agent logic and tool implementation.
- **SAP integration via the external AWS for SAP MCP server** — OData reads, writes, and discovery
  (`find_sap_services`, `get_metadata`, `odata_read`/`odata_count`, `odata_create`/`odata_update`/
  `odata_function_import`) flow through a managed external server; this project ships a thin adapter
  that mints Gateway targets onto it.
- **Cedar policy authorization** at the Gateway — role-gated writes and a forbidden-by-default
  `odata_delete`, enforced independently of the agent prompt so the agent cannot bypass its own
  permissions.
- **Autonomy control** via SSM — `trigger-mode` (auto/manual) governs whether the OData poller
  auto-enqueues detected cases or waits for a human to trigger them, changeable at runtime without
  redeployment. SAP write gating is handled by Cedar policy at the Gateway and the external MCP
  server's write-enablement knobs (threats T6/T15).
- **Autonomous exception detection** through a configurable OData poller using a SAP service
  account (machine identity).
- **Ticket-driven human approval workflows** — the agent creates tickets for approval gates,
  pauses, and resumes when reviewers approve or deny (demo feature, behind `demo.enabled`).
- **React frontend** with Cognito authentication, a three-panel workspace, direct SSE streaming
  to AgentCore, an analytics dashboard, and an agent observability/trace viewer.
- **Bedrock Knowledge Base** using Amazon S3 Vectors for SOP and SAP API-doc retrieval.
- **Dual infrastructure-as-code**: full parity between AWS CDK (`cdk/`) and Terraform
  (`terraform/`) — choose one and delete the other in your fork.
- **Pluggable notification channels** (SES, Slack, Jira, ServiceNow) via an adapter pattern.
- **Cost optimization**: model-tier routing, prompt caching, and turn limits.
- **Evaluation framework** with ground truth and a regression runner.
- **A single `demo.enabled` flag** gating all demo/sample resources, so a clean production base is
  one config change away.
- **Architecture Decision Records** (`docs/design-decisions/`) documenting the key choices, plus
  getting-started, SAP integration, security, and extension guides.

### Security

- Apache-2.0 license headers across all source files; complete third-party attribution in
  [NOTICE](NOTICE).
- User identity is derived server-side from validated JWTs rather than passed as a parameter,
  preventing impersonation via prompt injection.
- Input sanitization and content fencing for external data reaching the agent.

---

> This is the first public release. The project was developed internally as a private template
> (versions 0.1.0–0.7.0) before being prepared for publication; that history is not reproduced here.
> This project is provided as a sample and starting point — review the [NOTICE](NOTICE) disclaimer
> and conduct your own security and production-readiness assessment before deploying.
