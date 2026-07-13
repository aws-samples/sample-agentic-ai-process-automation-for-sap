# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# =============================================================================
# SAP Auth Lambda Layer
# Maps to: CDK constructs/sap-connectivity.ts — sapAuthLayer
#
# Shared layer with service-account credential fetching + error sanitization,
# attached to the OData poller (the only direct SAP caller).
# =============================================================================

# Shared Lambda layer: service-account credential fetching + error

locals {
  sap_auth_layer_source = "${path.module}/../../../lambdas/layers/sap_auth"
}

# Build layer: install deps into python/ directory (Lambda layer convention)
resource "null_resource" "sap_auth_layer_build" {
  triggers = {
    source_hash = filesha256("${local.sap_auth_layer_source}/sap_auth.py")
    reqs_hash   = filesha256("${local.sap_auth_layer_source}/requirements.txt")
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -e
      BUILD_DIR="${path.module}/artifacts/sap_auth_layer"
      rm -rf "$BUILD_DIR" && mkdir -p "$BUILD_DIR/python"
      cp ${local.sap_auth_layer_source}/*.py "$BUILD_DIR/python/"
      python3 -m pip install -r "${local.sap_auth_layer_source}/requirements.txt" \
        -t "$BUILD_DIR/python/" --quiet --upgrade --platform manylinux2014_aarch64 \
        --implementation cp --python-version 3.13 --only-binary=:all:
    EOT
  }
}

data "archive_file" "sap_auth_layer" {
  type        = "zip"
  source_dir  = "${path.module}/artifacts/sap_auth_layer"
  output_path = "${path.module}/artifacts/sap_auth_layer.zip"
  excludes    = ["__pycache__", "*.pyc", "*.dist-info"]
  depends_on  = [null_resource.sap_auth_layer_build]
}

resource "aws_lambda_layer_version" "sap_auth" {
  layer_name               = "${var.stack_name_base}-sap-auth"
  filename                 = data.archive_file.sap_auth_layer.output_path
  source_code_hash         = data.archive_file.sap_auth_layer.output_base64sha256
  compatible_runtimes      = ["python3.13", "python3.12"]
  compatible_architectures = ["arm64", "x86_64"]
  description              = "Shared SAP auth: service-account credentials + error sanitization"
}
