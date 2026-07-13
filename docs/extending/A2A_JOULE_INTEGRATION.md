<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# A2A Protocol & Joule Integration

How to expose the ERP exception agent via the [Agent-to-Agent (A2A) protocol](https://a2a-protocol.org/) so SAP Joule and other A2A-compatible agents can discover and invoke it.

## Background

The A2A protocol (contributed by Google to the Linux Foundation, adopted by SAP) standardizes how AI agents communicate across platforms. Key concepts:

- **Agent Card** — JSON metadata at `/.well-known/agent-card.json` describing an agent's identity, skills, endpoint, and auth requirements
- **JSON-RPC 2.0** — Communication via `message/send` (synchronous) and `message/stream` (streaming) methods
- **Task lifecycle** — Submitted → Working → Completed/Failed/Canceled
- **SAP Agent Catalog** — Joule discovers agents via [Open Resource Discovery (ORD)](https://open-resource-discovery.github.io/specification/) and the A2A Connector

SAP's A2A adoption means Joule can orchestrate external agents — including this quickstart — as first-class participants in enterprise workflows.

## Architecture

Two integration patterns depending on where the A2A server runs:

### Pattern 1: A2A on AgentCore Runtime (recommended)

Expose the Strands agent directly as an A2A server on AgentCore Runtime. Joule calls it over HTTPS.

```
┌──────────────────────────────────────────────────────────┐
│  SAP BTP                                                 │
│  Joule ──▶ Agent Catalog ──▶ A2A Connector               │
└──────────────────────────────┬───────────────────────────┘
                               │ HTTPS + A2A JSON-RPC
                               ▼
┌──────────────────────────────────────────────────────────┐
│  AWS                                                     │
│  AgentCore Runtime (port 9000, protocol: A2A)            │
│  ┌────────────────────────────────────────────────────┐  │
│  │  A2AServer (Strands)                               │  │
│  │  ├── /.well-known/agent-card.json                  │  │
│  │  ├── message/send   → basic_agent.py               │  │
│  │  └── message/stream → basic_agent.py (SSE)         │  │
│  └────────────────────────────────────────────────────┘  │
│       ↓                                                  │
│  AgentCore Gateway → Tool Lambdas → SAP OData            │
└──────────────────────────────────────────────────────────┘
```

### Pattern 2: BTP Bridge App

If SAP requires agents to be BTP-hosted for Joule discovery, deploy a thin Cloud Foundry proxy on BTP. See [BTP Hosting — Option B](../sap/BTP_HOSTING.md#option-b-btp-sidecar-for-joule-integration).

## Implementation

### Step 1: Add A2A dependency

```bash
# In agent/requirements.txt, add the a2a extra:
strands-agents[a2a]
```

### Step 2: Create the A2A server wrapper

Create `agent/a2a_server.py` alongside the existing `basic_agent.py`:

```python
"""
A2A server wrapper for the ERP Exception Agent.

Exposes the Strands agent via the A2A protocol so Joule and other
A2A-compatible agents can discover and invoke it.

Runs on port 9000 (AgentCore Runtime A2A convention).
"""

import logging
import os

import uvicorn
from fastapi import FastAPI
from strands import Agent
from strands.multiagent.a2a import A2AServer

from utils.skill_router import list_skills

logging.basicConfig(level=logging.INFO)

runtime_url = os.environ.get(
    "AGENTCORE_RUNTIME_URL", "http://127.0.0.1:9000/"
)

# Build skill metadata for the agent card from auto-discovered skills
skills_meta = []
for skill in list_skills():
    skills_meta.append({
        "id": skill["skill_id"],
        "name": skill["display_name"],
        "description": f"Processes: {', '.join(skill['process_types'])}",
    })

# Create a lightweight agent for A2A — the full skill routing
# happens inside basic_agent.py when the A2A message is dispatched
strands_agent = Agent(
    name="SAP ERP Exception Agent",
    description=(
        "Autonomous agent for SAP finance exception handling. "
        "Processes PO accruals and AP invoice matching."
    ),
    tools=[],  # Tools loaded dynamically per skill at invocation time
    callback_handler=None,
)

a2a_server = A2AServer(
    agent=strands_agent,
    http_url=runtime_url,
    serve_at_root=True,
)

app = FastAPI()


@app.get("/ping")
def ping():
    return {"status": "healthy"}


app.mount("/", a2a_server.to_fastapi_app())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9000)
```

### Step 3: Agent Card

The A2A server auto-generates an agent card at `/.well-known/agent-card.json`. To customize it, provide explicit metadata:

```json
{
  "name": "SAP ERP Exception Agent",
  "description": "Autonomous agent for SAP finance exception handling across PO accruals and AP invoice matching.",
  "url": "https://bedrock-agentcore.<region>.amazonaws.com/runtimes/<ARN>/invocations/",
  "version": "1.0.0",
  "capabilities": {
    "streaming": true,
    "pushNotifications": false
  },
  "authentication": {
    "schemes": ["oauth2"],
    "credentials": {
      "oauth2": {
        "tokenUrl": "https://<domain>.auth.<region>.amazoncognito.com/oauth2/token",
        "grantType": "client_credentials"
      }
    }
  },
  "skills": [
    {
      "id": "po_accruals",
      "name": "PO Accrual Processing",
      "description": "Detects month-end accrual exceptions, validates delivery dates, calculates time-proportional accruals, updates SAP schedule lines, creates parked journal entries.",
      "tags": ["finance", "accruals", "month-end"]
    },
    {
      "id": "ap_invoice_matching",
      "name": "AP Invoice Matching",
      "description": "Processes invoice exceptions, validates PO/GR matching, routes for approval.",
      "tags": ["finance", "accounts-payable", "invoices"]
    }
  ]
}
```

Skills in the agent card are derived from `skills/*/config.json` — when you add a new skill directory, the agent card should be updated to advertise it.

### Step 4: Deploy as A2A on AgentCore Runtime

```bash
# Configure for A2A protocol
agentcore configure -e agent/a2a_server.py --protocol A2A

# Deploy
agentcore deploy
```

AgentCore Runtime runs A2A servers on port 9000 at `/`, with JSON-RPC passthrough. The agent card is accessible at:

```
https://bedrock-agentcore.<region>.amazonaws.com/runtimes/<ARN>/invocations/.well-known/agent-card.json
```

### Step 5: Register in SAP Agent Catalog

Register the agent card URL in SAP's Agent Catalog so Joule can discover it:

1. In **Joule Studio**, navigate to the Agent Catalog
2. Add an external agent registration with the agent card URL
3. SAP's A2A Connector handles the JSON-RPC communication

The exact registration flow depends on SAP's Agent Catalog API (currently evolving — see [SAP Architecture Center: Agent Interoperability](https://architecture.learning.sap.com/docs/ref-arch/e5eb3b9b1d/8)).

## Identity Flow

A2A messages from Joule carry the BTP user's identity. How that identity reaches SAP depends on the work:

```
Joule (BTP user) ──▶ A2A message + user JWT
                          │
                          ▼
              AgentCore Runtime (A2A server)
                          │
                          ▼
              SAP OData via external AWS for SAP MCP server
              ├── autonomous / background work → service-account (machine credentials)
              └── interactive per-user work → MCP USER_FEDERATION (SAP sees the human user)
```

| Joule Scenario | SAP identity | SAP Sees |
|---|---|---|
| Joule autonomous background task | service-account | Machine user (SVC_AGENT) |
| User asks Joule to process an exception | MCP USER_FEDERATION (OBO) | Human user (JSMITH) |

Per-user SAP identity is handled entirely by the external AWS for SAP MCP server's USER_FEDERATION flow — this project no longer implements SAP identity modes itself. To map BTP/Joule users through to SAP, configure federation on the MCP server and (if using email-based federation) the Cognito→IAS path. See [SAP MCP User Federation](../sap/SAP_MCP_USER_FEDERATION.md) and [Same-Sub Federation](../sap/SAP_MCP_SAME_SUB_FEDERATION.md).

## A2A vs MCP: When to Use Which

This quickstart already uses MCP (via AgentCore Gateway) for tool invocation. A2A serves a different purpose:

| | MCP (current) | A2A (new) |
|---|---|---|
| **Purpose** | Agent → Tool communication | Agent → Agent communication |
| **Direction** | Agent calls tools | External agent calls your agent |
| **Protocol** | MCP over OAuth2 M2M | JSON-RPC 2.0 over HTTPS |
| **Discovery** | Gateway auto-discovers tool Lambdas | Agent card at `/.well-known/agent-card.json` |
| **Use case** | `odata_read`, `send_notification`, etc. | Joule invokes ERP exception processing |

They are complementary — A2A is the external interface, MCP is the internal tool layer:

```
External (A2A)                    Internal (MCP)
Joule ──A2A──▶ Agent ──MCP──▶ Gateway ──▶ case_management
                                       ──▶ notification
                                       ──▶ knowledge_base
                          └──MCP──▶ AWS for SAP MCP server ──▶ SAP OData (odata_read/odata_create/…)
```

## SAP Dispute Resolution Reference

SAP published a reference implementation for A2A multi-agent collaboration: [btp-a2a-dispute-resolution](https://github.com/SAP-samples/btp-a2a-dispute-resolution). Key patterns from that sample:

- **Agent Catalog** aggregates agent metadata using ORD
- **A2A Connector** bridges SAP's internal agent framework with external runtimes
- Agents discover each other's capabilities dynamically and delegate sub-tasks
- Multiple organizations collaborate through domain-specific agents

This quickstart follows the same pattern — the ERP exception agent is a domain-specific agent that Joule can orchestrate alongside other SAP and third-party agents.

## Multi-Agent A2A Pattern

A multi-agent A2A topology for this use case looks like:

- **Skill servers** — each domain agent runs as a separate A2A server with its own tools and prompt
- **Orchestrator** — discovers skill agents via `A2AClientToolProvider` and delegates
- **Agent cards** — auto-generated at `/.well-known/agent.json` per skill agent

The [SAP A2A Dispute Resolution Sample](https://github.com/SAP-samples/btp-a2a-dispute-resolution)
is a good external reference for this topology. The roadmap below maps the steps to take this
quickstart's single Strands agent in that direction.

## Implementation Roadmap

| Phase | What | Effort |
|---|---|---|
| 1. A2A server wrapper | Add `strands-agents[a2a]`, create `a2a_server.py` | Small — wrapper around existing agent |
| 2. Agent card with skill metadata | Auto-generate from `skills/*/config.json` | Small — read existing configs |
| 3. Deploy as A2A on AgentCore Runtime | `agentcore configure --protocol A2A && agentcore deploy` | Small — deployment config change |
| 4. BTP bridge app (if needed) | CF Python app proxying to AgentCore | Medium — new BTP deployment |
| 5. SAP Agent Catalog registration | Register agent card URL via ORD | Depends on SAP's catalog API maturity |
| 6. Identity integration | Configure XSUAA issuer trust in interceptor | Small — config change |

## References

- [A2A Protocol](https://a2a-protocol.org/) — protocol specification
- [SAP Architecture Center: Agent Interoperability](https://architecture.learning.sap.com/docs/ref-arch/e5eb3b9b1d/8) — SAP's A2A reference architecture
- [SAP BTP Agentic Capabilities](https://news.sap.com/2025/11/new-agentic-capabilities-sap-btp-supercharge-developers/) — Joule Studio, A2A, MCP support
- [AgentCore A2A Deployment](https://aws.github.io/bedrock-agentcore-starter-toolkit/user-guide/runtime/a2a.html) — deploying A2A servers on AgentCore Runtime
- [Strands A2A](https://google.github.io/adk-docs/a2a/intro/) — A2A concepts and when to use A2A vs local sub-agents
- [SAP A2A Dispute Resolution Sample](https://github.com/SAP-samples/btp-a2a-dispute-resolution) — reference implementation
- [BTP Hosting Options](../sap/BTP_HOSTING.md) — deployment models for BTP
