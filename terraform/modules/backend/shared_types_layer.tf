# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# =============================================================================
# Shared Types Lambda Layer
# Maps to: CDK backend-stack.ts — SharedTypesLayer
#
# Generated pydantic models (source of truth: types/*.schema.json) + pydantic,
# shared across Python Lambdas so runtime data can be validated against the same
# schema the frontend types are generated from. Attached to the OData poller.
# =============================================================================

# Shared Lambda layer: generated pydantic models (source of truth:
# types/*.schema.json) + pydantic, so Python Lambdas validate runtime data

locals {
  shared_types_layer_source = "${path.module}/../../../lambdas/layers/shared_types"
}

# Build layer: install deps + copy models into python/ (Lambda layer convention)
resource "null_resource" "shared_types_layer_build" {
  triggers = {
    source_hash = sha256(join("", [for f in fileset(local.shared_types_layer_source, "*.py") : filesha256("${local.shared_types_layer_source}/${f}")]))
    reqs_hash   = filesha256("${local.shared_types_layer_source}/requirements.txt")
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -e
      BUILD_DIR="${path.module}/artifacts/shared_types_layer"
      rm -rf "$BUILD_DIR" && mkdir -p "$BUILD_DIR/python"
      cp ${local.shared_types_layer_source}/*.py "$BUILD_DIR/python/"
      python3 -m pip install -r "${local.shared_types_layer_source}/requirements.txt" \
        -t "$BUILD_DIR/python/" --quiet --upgrade --platform manylinux2014_aarch64 \
        --implementation cp --python-version 3.13 --only-binary=:all:
    EOT
  }
}

data "archive_file" "shared_types_layer" {
  type        = "zip"
  source_dir  = "${path.module}/artifacts/shared_types_layer"
  output_path = "${path.module}/artifacts/shared_types_layer.zip"
  excludes    = ["__pycache__", "*.pyc", "*.dist-info"]
  depends_on  = [null_resource.shared_types_layer_build]
}

resource "aws_lambda_layer_version" "shared_types" {
  layer_name               = "${var.stack_name_base}-shared-types"
  filename                 = data.archive_file.shared_types_layer.output_path
  source_code_hash         = data.archive_file.shared_types_layer.output_base64sha256
  compatible_runtimes      = ["python3.13", "python3.12"]
  compatible_architectures = ["arm64", "x86_64"]
  description              = "Generated pydantic models (WorkItem, Ticket) + pydantic"
}
