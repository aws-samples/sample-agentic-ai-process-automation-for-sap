<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Adding a New Gateway Tool

Gateway tools are Lambda-backed MCP tools the agent calls via AgentCore Gateway. CDK auto-discovers them — add a directory under `agentcore/gateway/tools/` and deploy. The live homegrown tools are `case_management`, `notification`, `knowledge_base`, and `demo_ticket_management`.

> **SAP OData is NOT a homegrown Gateway tool.** SAP read/write operations (`odata_read`, `odata_create`, `odata_update`, `odata_function_import`, etc.) are served by the external AWS for SAP MCP server registered as a separate Gateway target — do not add a `sap_*` Lambda here. See [`../design-decisions/012-sap-mcp-server-integration.md`](../design-decisions/012-sap-mcp-server-integration.md). Use this guide only for net-new non-SAP tools.

## Step-by-Step

### 1. Create the Tool Directory

```bash
mkdir gateway/tools/<tool_name>
```

Use `snake_case` for the directory name.

### 2. Create `tool_spec.json`

This is the MCP tool schema the agent sees. Example (`agentcore/gateway/tools/notification/tool_spec.json`):

```json
{
  "name": "send_notification",
  "description": "Send a notification to the specified recipient.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "recipient": { "type": "string", "description": "Email address or channel ID" },
      "subject": { "type": "string", "description": "Notification subject" },
      "body": { "type": "string", "description": "Notification body (markdown)" }
    },
    "required": ["recipient", "subject", "body"]
  }
}
```

### 3. Create the Lambda Handler

Create `agentcore/gateway/tools/<tool_name>/<tool_name>_lambda.py`:

```python
import json
import os

STACK_NAME = os.environ["STACK_NAME_BASE"]


def handler(event, context):
    tool_name = context.client_context.custom["bedrockAgentCoreToolName"]
    body = json.loads(event.get("body", "{}"))

    # Your tool logic here

    return {
        "statusCode": 200,
        "body": json.dumps({"result": "success"}),
    }
```

Key patterns:
- Use `context.client_context.custom['bedrockAgentCoreToolName']` to route if the Lambda handles multiple tools
- Always use `os.environ["STACK_NAME_BASE"]` (no fallback) for stack-scoped resources
- Add `requirements.txt` if the Lambda needs extra dependencies

### 4. Wire to Skills

Add the tool name to `gateway_tools` in each skill's `config.json` that should use it:

```json
{
  "gateway_tools": [
    "existing_tool",
    "<tool_name>"
  ]
}
```

### 5. Deploy

```bash
cd cdk && cdk deploy --all
```

The backend stack (`cdk/lib/backend-stack.ts`) auto-discovers tools in `agentcore/gateway/tools/`. If your tool needs special IAM permissions or environment variables, add them in the CDK stack.

### 6. Test

Ask the agent to use the tool via chat. Check CloudWatch logs for the tool's Lambda if something goes wrong.

## Reference

| File | Purpose |
|------|---------|
| `agentcore/gateway/tools/notification/` | Minimal example tool |
| `agentcore/gateway/tools/demo_ticket_management/` | Multi-tool Lambda example (create/update/get/list) |
| `cdk/lib/backend-stack.ts` | Auto-discovery and IAM wiring |
