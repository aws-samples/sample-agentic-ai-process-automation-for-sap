#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Detect container runtime (Docker → Finch fallback) and export CDK_DOCKER.
# Source this before running cdk commands:
#   source scripts/setup-container-runtime.sh
#
# Or run standalone to check:
#   bash scripts/setup-container-runtime.sh

_setup_container_runtime() {
  # Already set by user — respect it
  if [[ -n "${CDK_DOCKER:-}" ]]; then
    echo "✅ Using CDK_DOCKER=${CDK_DOCKER} (already set)"
    return 0
  fi

  if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    echo "✅ Using docker as container runtime"
    return 0
  fi

  if command -v finch &>/dev/null; then
    if ! finch vm status 2>/dev/null | grep -q Running; then
      echo "⏳ Starting finch VM..."
      finch vm init 2>/dev/null || true
      finch vm start 2>/dev/null || true
    fi
    export CDK_DOCKER=finch
    echo "✅ Using finch as container runtime (CDK_DOCKER=finch)"
    return 0
  fi

  echo "❌ No container runtime found. Install Docker or Finch:"
  echo "   Docker: https://docs.docker.com/engine/install/"
  echo "   Finch:  brew install --cask finch && finch vm init"
  return 1
}

_setup_container_runtime
