<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Changelog

All notable changes to the Agentic ERP Automation Quickstart will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
