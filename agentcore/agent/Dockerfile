# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# nosemgrep: dockerfile-source-not-pinned — uv image tags are immutable (content-addressed)
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

# Configure UV for container environment
ENV UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1 \
    DOCKER_CONTAINER=1 \
    OTEL_PYTHON_LOG_CORRELATION=true \
    PYTHONUNBUFFERED=1

# Copy pyproject.toml and gateway package for the project package install
COPY pyproject.toml .
COPY agentcore/gateway/ gateway/

# Copy and install agent-specific requirements first
COPY agentcore/agent/requirements.txt requirements.txt
# nosemgrep: missing-pip-no-cache-dir — uv uses --no-cache (equivalent)
RUN uv pip install --no-cache -r requirements.txt && \
    uv pip install --no-cache aws-opentelemetry-distro==0.16.0

# Install the project package with only core dependencies (no dev/agent optional deps)
# nosemgrep: missing-pip-no-cache-dir
RUN uv pip install --no-cache -e . --no-deps && \
    uv pip install --no-cache requests>=2.31.0

# Create non-root user
RUN useradd -m -u 1000 bedrock_agentcore
USER bedrock_agentcore

EXPOSE 8080

# Copy agent code files
COPY agentcore/agent/basic_agent.py .
COPY agentcore/agent/utils/ utils/
COPY skills/ skills/

# nosemgrep: prefer-json-notation — HEALTHCHECK CMD needs shell form for || exit 1
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/ping', timeout=2)" || exit 1

# Start agent with OpenTelemetry instrumentation
CMD ["opentelemetry-instrument", "python", "-m", "basic_agent"]
