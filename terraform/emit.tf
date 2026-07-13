# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Uses an external data source so the emitter runs at plan time and its output
# is available in the same plan. Returns {} for cognito (backend module falls
# back to Cognito-derived values); returns discovery_url + allowed_clients for
# entra/okta. Requires `python` (with PyYAML) on PATH.
data "external" "auth_profile" {
  program = ["python", "${path.root}/../scripts/deploy/run_emit.py", "--backend", "terraform"]
  query = {
    auth_profile    = var.auth_profile
    discovery_url   = var.auth_inbound_discovery_url
    allowed_clients = join(",", var.auth_inbound_allowed_clients)
    sap_mcp_enabled = tostring(var.sap_mcp_enabled)
  }
}

locals {
  emit_discovery_url       = lookup(data.external.auth_profile.result, "discovery_url", "")
  emit_allowed_clients_csv = lookup(data.external.auth_profile.result, "allowed_clients", "")
  emit_allowed_clients     = local.emit_allowed_clients_csv == "" ? [] : split(",", local.emit_allowed_clients_csv)
}
