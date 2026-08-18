# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Repository-local guided launcher for the Agentic ERP Automation sample.

This package is part of the sample, not a distributable tool. It deploys this
checkout and nothing else: it is never published to a package index, and the
cloned repository remains the deployment artifact because CDK synthesis reads
`agentcore/`, `skills/`, `lambdas/`, and the frontend through repository-relative
paths.

Only the standard library is imported at module scope, so `doctor` runs on a
clean clone before anything is installed. Optional imports (PyYAML, boto3) are
probed at the call site and degrade rather than fail.
"""
