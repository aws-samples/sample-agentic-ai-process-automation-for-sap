# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# =============================================================================
# API Gateway Routes — Autonomy, Cases, Tickets, Observability
# Maps to: backend-stack.ts createFeedbackApi() — additional endpoints
# All routes use the existing Cognito authorizer from feedback.tf
# =============================================================================

# API Gateway routes for Autonomy, Cases, Tickets, and Observability.

# /autonomy (GET + PUT)

resource "aws_api_gateway_resource" "autonomy" {
  rest_api_id = aws_api_gateway_rest_api.feedback.id
  parent_id   = aws_api_gateway_rest_api.feedback.root_resource_id
  path_part   = "autonomy"
}

resource "aws_api_gateway_method" "autonomy_get" {
  rest_api_id   = aws_api_gateway_rest_api.feedback.id
  resource_id   = aws_api_gateway_resource.autonomy.id
  http_method   = "GET"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito.id
}

resource "aws_api_gateway_method" "autonomy_put" {
  rest_api_id   = aws_api_gateway_rest_api.feedback.id
  resource_id   = aws_api_gateway_resource.autonomy.id
  http_method   = "PUT"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito.id
}

resource "aws_api_gateway_integration" "autonomy_get" {
  rest_api_id             = aws_api_gateway_rest_api.feedback.id
  resource_id             = aws_api_gateway_resource.autonomy.id
  http_method             = aws_api_gateway_method.autonomy_get.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.autonomy_api.invoke_arn
}

resource "aws_api_gateway_integration" "autonomy_put" {
  rest_api_id             = aws_api_gateway_rest_api.feedback.id
  resource_id             = aws_api_gateway_resource.autonomy.id
  http_method             = aws_api_gateway_method.autonomy_put.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.autonomy_api.invoke_arn
}

resource "aws_api_gateway_method" "autonomy_options" {
  rest_api_id   = aws_api_gateway_rest_api.feedback.id
  resource_id   = aws_api_gateway_resource.autonomy.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "autonomy_options" {
  rest_api_id       = aws_api_gateway_rest_api.feedback.id
  resource_id       = aws_api_gateway_resource.autonomy.id
  http_method       = aws_api_gateway_method.autonomy_options.http_method
  type              = "MOCK"
  request_templates = { "application/json" = jsonencode({ statusCode = 200 }) }
}

resource "aws_lambda_permission" "autonomy_api" {
  statement_id  = "AllowAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.autonomy_api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.feedback.execution_arn}/*/*"
}

# /cases (GET) + /cases/{case_id} (GET) + nested
# One path parameter, because case_id is the cases table's partition key.

resource "aws_api_gateway_resource" "cases" {
  rest_api_id = aws_api_gateway_rest_api.feedback.id
  parent_id   = aws_api_gateway_rest_api.feedback.root_resource_id
  path_part   = "cases"
}

resource "aws_api_gateway_resource" "cases_detail" {
  rest_api_id = aws_api_gateway_rest_api.feedback.id
  parent_id   = aws_api_gateway_resource.cases.id
  path_part   = "{case_id}"
}

resource "aws_api_gateway_resource" "cases_traces" {
  rest_api_id = aws_api_gateway_rest_api.feedback.id
  parent_id   = aws_api_gateway_resource.cases_detail.id
  path_part   = "traces"
}

resource "aws_api_gateway_resource" "cases_rating" {
  rest_api_id = aws_api_gateway_rest_api.feedback.id
  parent_id   = aws_api_gateway_resource.cases_detail.id
  path_part   = "rating"
}

resource "aws_api_gateway_resource" "cases_enqueue" {
  rest_api_id = aws_api_gateway_rest_api.feedback.id
  parent_id   = aws_api_gateway_resource.cases.id
  path_part   = "enqueue"
}

locals {
  cases_routes = {
    cases_list    = { resource_id = aws_api_gateway_resource.cases.id, method = "GET", fn = aws_lambda_function.cases_api }
    cases_detail  = { resource_id = aws_api_gateway_resource.cases_detail.id, method = "GET", fn = aws_lambda_function.cases_api }
    cases_traces  = { resource_id = aws_api_gateway_resource.cases_traces.id, method = "POST", fn = aws_lambda_function.cases_api }
    cases_rating  = { resource_id = aws_api_gateway_resource.cases_rating.id, method = "PUT", fn = aws_lambda_function.cases_api }
    cases_enqueue = { resource_id = aws_api_gateway_resource.cases_enqueue.id, method = "POST", fn = aws_lambda_function.webhook_processor }
  }
}

resource "aws_api_gateway_method" "cases" {
  for_each      = local.cases_routes
  rest_api_id   = aws_api_gateway_rest_api.feedback.id
  resource_id   = each.value.resource_id
  http_method   = each.value.method
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito.id
}

resource "aws_api_gateway_integration" "cases" {
  for_each                = local.cases_routes
  rest_api_id             = aws_api_gateway_rest_api.feedback.id
  resource_id             = each.value.resource_id
  http_method             = aws_api_gateway_method.cases[each.key].http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = each.value.fn.invoke_arn
}

resource "aws_lambda_permission" "cases_api" {
  statement_id  = "AllowAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.cases_api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.feedback.execution_arn}/*/*"
}

resource "aws_lambda_permission" "webhook_processor_apigw" {
  statement_id  = "AllowAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.webhook_processor.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.feedback.execution_arn}/*/*"
}

# /tickets (GET, POST) + /tickets/{id} (GET, PUT) + /tickets/{id}/action
# Demo supervised-approval API — gated by var.demo_enabled.

resource "aws_api_gateway_resource" "tickets" {
  count       = var.demo_enabled ? 1 : 0
  rest_api_id = aws_api_gateway_rest_api.feedback.id
  parent_id   = aws_api_gateway_rest_api.feedback.root_resource_id
  path_part   = "tickets"
}

resource "aws_api_gateway_resource" "ticket_detail" {
  count       = var.demo_enabled ? 1 : 0
  rest_api_id = aws_api_gateway_rest_api.feedback.id
  parent_id   = aws_api_gateway_resource.tickets[0].id
  path_part   = "{id}"
}

resource "aws_api_gateway_resource" "ticket_action" {
  count       = var.demo_enabled ? 1 : 0
  rest_api_id = aws_api_gateway_rest_api.feedback.id
  parent_id   = aws_api_gateway_resource.ticket_detail[0].id
  path_part   = "action"
}

locals {
  ticket_routes = var.demo_enabled ? {
    tickets_list   = { resource_id = aws_api_gateway_resource.tickets[0].id, method = "GET", fn = aws_lambda_function.tickets_api[0] }
    tickets_create = { resource_id = aws_api_gateway_resource.tickets[0].id, method = "POST", fn = aws_lambda_function.tickets_api[0] }
    ticket_get     = { resource_id = aws_api_gateway_resource.ticket_detail[0].id, method = "GET", fn = aws_lambda_function.tickets_api[0] }
    ticket_update  = { resource_id = aws_api_gateway_resource.ticket_detail[0].id, method = "PUT", fn = aws_lambda_function.tickets_api[0] }
    ticket_action  = { resource_id = aws_api_gateway_resource.ticket_action[0].id, method = "POST", fn = aws_lambda_function.tickets_api[0] }
  } : {}
}

resource "aws_api_gateway_method" "tickets" {
  for_each      = local.ticket_routes
  rest_api_id   = aws_api_gateway_rest_api.feedback.id
  resource_id   = each.value.resource_id
  http_method   = each.value.method
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito.id
}

resource "aws_api_gateway_integration" "tickets" {
  for_each                = local.ticket_routes
  rest_api_id             = aws_api_gateway_rest_api.feedback.id
  resource_id             = each.value.resource_id
  http_method             = aws_api_gateway_method.tickets[each.key].http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = each.value.fn.invoke_arn
}

resource "aws_lambda_permission" "tickets_api" {
  count         = var.demo_enabled ? 1 : 0
  statement_id  = "AllowAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.tickets_api[0].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.feedback.execution_arn}/*/*"
}

# The /tickets/{id}/action route is served by tickets_api (folded in); its
# aws_lambda_permission.tickets_api above already grants the /*/* invoke.

# /observability (metrics, health, traces)

resource "aws_api_gateway_resource" "observability" {
  rest_api_id = aws_api_gateway_rest_api.feedback.id
  parent_id   = aws_api_gateway_rest_api.feedback.root_resource_id
  path_part   = "observability"
}

resource "aws_api_gateway_resource" "obs_metrics" {
  rest_api_id = aws_api_gateway_rest_api.feedback.id
  parent_id   = aws_api_gateway_resource.observability.id
  path_part   = "metrics"
}

resource "aws_api_gateway_resource" "obs_health" {
  rest_api_id = aws_api_gateway_rest_api.feedback.id
  parent_id   = aws_api_gateway_resource.observability.id
  path_part   = "health"
}

resource "aws_api_gateway_resource" "obs_traces" {
  rest_api_id = aws_api_gateway_rest_api.feedback.id
  parent_id   = aws_api_gateway_resource.observability.id
  path_part   = "traces"
}

locals {
  obs_routes = {
    metrics = { resource_id = aws_api_gateway_resource.obs_metrics.id }
    health  = { resource_id = aws_api_gateway_resource.obs_health.id }
    traces  = { resource_id = aws_api_gateway_resource.obs_traces.id }
  }
}

resource "aws_api_gateway_method" "observability" {
  for_each      = local.obs_routes
  rest_api_id   = aws_api_gateway_rest_api.feedback.id
  resource_id   = each.value.resource_id
  http_method   = "GET"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito.id
}

resource "aws_api_gateway_integration" "observability" {
  for_each                = local.obs_routes
  rest_api_id             = aws_api_gateway_rest_api.feedback.id
  resource_id             = each.value.resource_id
  http_method             = aws_api_gateway_method.observability[each.key].http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.observability_api.invoke_arn
}

resource "aws_lambda_permission" "observability_api" {
  statement_id  = "AllowAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.observability_api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.feedback.execution_arn}/*/*"
}

# Redeploys the API whenever any route resource changes, including the
# routes defined in feedback.tf.
resource "aws_api_gateway_deployment" "full_api" {
  rest_api_id = aws_api_gateway_rest_api.feedback.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.feedback.id,
      aws_api_gateway_method.post_feedback.id,
      aws_api_gateway_integration.post_feedback.id,
      aws_api_gateway_resource.autonomy.id,
      aws_api_gateway_method.autonomy_get.id,
      aws_api_gateway_method.autonomy_put.id,
      aws_api_gateway_resource.cases.id,
      aws_api_gateway_resource.cases_enqueue.id,
      join(",", [for r in aws_api_gateway_resource.tickets : r.id]),
      join(",", [for r in aws_api_gateway_resource.ticket_action : r.id]),
      aws_api_gateway_resource.observability.id,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [
    aws_api_gateway_integration.autonomy_get,
    aws_api_gateway_integration.autonomy_put,
    aws_api_gateway_integration.cases,
    aws_api_gateway_integration.tickets,
    aws_api_gateway_integration.observability,
    aws_api_gateway_integration.post_feedback,
  ]
}
