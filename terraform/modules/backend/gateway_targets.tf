# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# =============================================================================
# Gateway Targets — One target per tool (TF provider limit: 1 tool_schema/target)
# =============================================================================

# The provider allows only one tool_schema per gateway target, so each tool gets its own target below.

locals {
  # SAP OData (read/write/discovery) is served by the external AWS-for-SAP MCP
  # server target, not a homegrown Lambda, so it's absent from this map.
  gateway_tool_lambdas_core = {
    case_management = aws_lambda_function.case_management
    notification    = aws_lambda_function.notification
    knowledge_base  = aws_lambda_function.knowledge_base
  }
  gateway_tool_lambdas_demo = var.demo_enabled ? {
    ticket_management = aws_lambda_function.ticket_management[0]
  } : {}
  gateway_tool_lambdas = merge(local.gateway_tool_lambdas_core, local.gateway_tool_lambdas_demo)

  gateway_tool_defs_core = {
    case_management = { spec_dir = "case_management" }
    notification    = { spec_dir = "notification" }
    knowledge_base  = { spec_dir = "knowledge_base" }
  }
  gateway_tool_defs_demo = var.demo_enabled ? {
    ticket_management = { spec_dir = "demo_ticket_management" }
  } : {}
  gateway_tool_defs = merge(local.gateway_tool_defs_core, local.gateway_tool_defs_demo)

  # Flatten: one entry per individual tool across all spec files
  all_gateway_tools = merge([
    for key, def in local.gateway_tool_defs : {
      for idx, tool in jsondecode(file("${path.module}/../../../agentcore/gateway/tools/${def.spec_dir}/tool_spec.json")) :
      "${key}_${tool.name}" => {
        lambda_key  = key
        tool_name   = tool.name
        tool_desc   = try(tool.description, "")
        schema_desc = try(tool.inputSchema.description, "Input parameters")
        properties  = try(tool.inputSchema.properties, {})
        required    = try(tool.inputSchema.required, [])
      }
    }
  ]...)
}

data "aws_iam_policy_document" "gateway_sap_tools_policy" {
  statement {
    sid       = "LambdaInvokeSapTools"
    effect    = "Allow"
    actions   = ["lambda:InvokeFunction"]
    resources = [for fn in local.gateway_tool_lambdas : fn.arn]
  }
}

resource "aws_iam_role_policy" "gateway_sap_tools" {
  name   = "${var.stack_name_base}-gateway-sap-tools-policy"
  role   = aws_iam_role.gateway.id
  policy = data.aws_iam_policy_document.gateway_sap_tools_policy.json
}

resource "aws_bedrockagentcore_gateway_target" "sap_tool" {
  for_each = local.all_gateway_tools

  name               = replace(each.value.tool_name, "_", "-")
  gateway_identifier = aws_bedrockagentcore_gateway.main.gateway_id
  description        = substr(coalesce(each.value.tool_desc, "Gateway tool"), 0, 190)

  credential_provider_configuration {
    gateway_iam_role {}
  }

  target_configuration {
    mcp {
      lambda {
        lambda_arn = local.gateway_tool_lambdas[each.value.lambda_key].arn

        tool_schema {
          inline_payload {
            name        = each.value.tool_name
            description = each.value.tool_desc

            input_schema {
              type        = "object"
              description = each.value.schema_desc

              dynamic "property" {
                for_each = each.value.properties
                content {
                  name        = property.key
                  type        = property.value.type
                  description = try(property.value.description, "")
                  required    = contains(each.value.required, property.key)
                }
              }
            }
          }
        }
      }
    }
  }

  depends_on = [aws_bedrockagentcore_gateway.main]
}

resource "null_resource" "policy_engine" {
  triggers = {
    gateway_id       = aws_bedrockagentcore_gateway.main.gateway_id
    enforcement_mode = var.cedar_enforcement_mode
    function_name    = aws_lambda_function.policy_engine.function_name
    region           = local.region
  }

  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    command     = <<-EOT
      set -e
      CEDAR_FILE="${path.module}/../../../agentcore/policies/sap_agent_policies.cedar"
      if [ ! -f "$CEDAR_FILE" ]; then
        echo "No Cedar policies found, skipping"
        exit 0
      fi
      PAYLOAD=$(cat <<'EOF'
{
  "RequestType": "Create",
  "ResourceProperties": {
    "EngineName": "${var.stack_name_base}-policy-engine",
    "GatewayId": "${aws_bedrockagentcore_gateway.main.gateway_id}",
    "Region": "${local.region}",
    "EnforcementMode": "${var.cedar_enforcement_mode}",
    "Policies": "[]"
  }
}
EOF
)
      echo "Creating Cedar policy engine..."
      RESPONSE_FILE=$(mktemp)
      aws lambda invoke \
        --function-name "${aws_lambda_function.policy_engine.function_name}" \
        --cli-binary-format raw-in-base64-out \
        --payload "$PAYLOAD" \
        --region "${local.region}" \
        --cli-read-timeout 120 \
        "$RESPONSE_FILE" || true
      cat "$RESPONSE_FILE"
      rm -f "$RESPONSE_FILE"
    EOT
  }

  depends_on = [
    aws_bedrockagentcore_gateway.main,
    aws_lambda_function.policy_engine
  ]
}
