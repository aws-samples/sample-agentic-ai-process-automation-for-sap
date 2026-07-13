<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Fullstack AgentCore Solution Template - Infrastructure

This directory contains the AWS CDK infrastructure code for deploying the Fullstack AgentCore Solution Template.

## Prerequisites

- Node.js 18+
- AWS CLI configured with appropriate credentials
- AWS CDK CLI installed: `npm install -g aws-cdk`

## Minimal IAM Policy for Deployment

The file `minimal-deploy-policy.json` contains the minimum IAM permissions required to deploy this CDK application. This policy includes 30 actions across 7 statements covering CloudFormation, S3, SSM, ECR, IAM PassRole, and Amplify.

**Important:** This policy assumes CDK bootstrap has already been run in the target account. It does not include permissions for `cdk bootstrap`. To bootstrap a fresh account, you'll need additional IAM permissions (CreateRole, AttachRolePolicy, PutRolePolicy, etc.) - refer to the AWS CDK Bootstrap documentation for details.

**Security Note:** Some wildcards are present for resources (e.g., `arn:aws:cloudformation:*:*:stack/*`). For production environments, replace these with your specific resource ARNs to further scope down permissions.

## Getting Started

All of the following commands assuming you are in the top of the `cdk/` directory
### Install Dependencies

```bash
npm install
```

### Build TypeScript

```bash
npm run build
```

### Bootstrap CDK (First Time Only)

```bash
npx cdk bootstrap
```

### Deploy

```bash
npx cdk deploy --all
```

## Useful Commands

* `npm run build`   - Compile TypeScript to JavaScript
* `npm run watch`   - Watch for changes and compile automatically
* `npm run test`    - Run Jest unit tests
* `npx cdk deploy --all` - Deploy all stacks to your AWS account/region
* `npx cdk diff`    - Compare deployed stack with current state
* `npx cdk synth`   - Emit the synthesized CloudFormation template
* `npx cdk destroy --all` - Remove all deployed resources

## Configuration

Edit `config.yaml` to customize your deployment:

```yaml
stack_name_base: "erp-accrual-agent"

frontend:
  domain_name: null  # Optional: Set to your custom domain
  certificate_arn: null  # Optional: Set to your ACM certificate ARN

backend:
  pattern: "agent"  # Primary agent (Strands SDK)
```

## Project Structure

```
cdk/
├── bin/
│   └── app.ts               # CDK app entry point
├── lib/
│   ├── main-stack.ts        # Orchestrator: wires the stacks together
│   ├── frontend-stack.ts    # React frontend on Amplify
│   ├── cognito-stack.ts     # Cognito user pool + clients
│   ├── backend-stack.ts     # Backend / AgentCore (gateway, runtime, APIs) + S3 Vectors Knowledge Bases
│   ├── demo-stack.ts        # Opt-in demo infrastructure (demo.enabled)
│   ├── sap-mcp-stack.ts     # Adapter to the external AWS for SAP MCP server
│   ├── constructs/          # Reusable constructs (auth, observability, …)
│   └── utils/               # Config manager, resolvers, bundling helpers
├── test/                    # Jest unit tests
├── cdk.json                 # CDK configuration
├── config.yaml              # Application configuration
├── package.json
└── tsconfig.json
```

## Development Workflow

1. Make changes to TypeScript files in `lib/`
2. Run `npm run build` to compile
3. Run `npx cdk diff` to see what will change
4. Run `npx cdk deploy --all` to deploy changes

For faster iteration, use watch mode:
```bash
npm run watch
```

## Deployment Details

The CDK deployment creates multiple stacks with a specific deployment order:

### Stack Architecture & Deployment Order

1. **Frontend Stack** (FrontendStack):
   - Amplify app hosting the React frontend
   - Branch configuration + deployment staging bucket

2. **Cognito Stack** (CognitoStack):
   - Cognito User Pool for user authentication
   - User Pool Client for frontend OAuth flows
   - User Pool Domain for hosted UI

3. **Backend Stack** (BackendStack):
   - **Machine Client & Resource Server**: OAuth2 client credentials for service-to-service auth
   - **AgentCore Gateway**: API gateway for tool integration with Lambda targets
   - **AgentCore Runtime**: Bedrock AgentCore runtime for agent execution
   - **Knowledge Bases**: S3 Vectors + Bedrock Knowledge Bases for SOPs and API docs
   - **Supporting Resources**: IAM roles, DynamoDB tables, API Gateway for feedback

Optional stacks (config-gated): **DemoStack** (`demo.enabled`) and **SapMcpStack** (`sap_mcp.enabled`).

### Component Dependencies

Within the Backend Stack, components are created in this order:
1. **Cognito Integration**: Import user pool from Cognito stack
2. **Machine Client**: Create OAuth2 client for M2M authentication
3. **Gateway**: Create AgentCore Gateway (depends on machine client)
4. **Runtime**: Create AgentCore Runtime (independent of gateway)

This order ensures authentication components are available before services that depend on them, while keeping the runtime deployment separate since it doesn't directly depend on the gateway.

### Docker Build Configuration

> **Note:** This section only applies when `deployment_type: docker` is set in `cdk/config.yaml`. The default `zip` deployment does not use Docker for any part of the deploy process — Lambda dependencies are bundled locally using `pip install`.

The agent container builds use a specific configuration to handle the repository structure efficiently:

#### Build Context Strategy

**Problem**: Agent patterns need access to the shared `gateway/` utilities package, but Docker build contexts cannot access parent directories using `../` paths.

**Solution**: Use repository root as build context with optimized file filtering:

1. **Build Context**: Repository root (`/path/to/agentic-erp-automation-quick-start/`)
2. **Dockerfile Location**: `agentcore/agent/Dockerfile`
3. **Package Installation**: Install the project package (`agentcore/gateway/` + `pyproject.toml`) as a proper Python package
4. **File Filtering**: `.dockerignore` excludes large directories to prevent build hangs

#### Docker Context Optimization

**Issue**: Large build contexts (including `node_modules/`, `.git/`, etc.) cause Docker builds to hang during the "transferring context" phase, especially in CDK deployments.

**Solution**: `.dockerignore` file at repository root excludes:
- `node_modules/` directories (frontend and infra)
- `.git/` version control data  
- Build artifacts (`cdk.out/`, `.next/`, `dist/`)
- Cache directories (`.ruff_cache/`, `__pycache__/`)

**Result**: Build context reduced from ~100MB+ to ~10MB, eliminating hang issues.

#### Package-Based Architecture

Instead of copying files with relative paths, the Dockerfile:

1. **Installs the project package**: `RUN pip install --no-cache-dir -e .`
   - Makes `gateway` utilities available as `from gateway.utils.*`
   - Eliminates need for file copying between directories
   - Works consistently across all agent patterns

2. **Copies only agent code**: `COPY agent/basic_agent.py .`
   - Minimal file copying for the specific agent
   - Clean separation between shared utilities and agent logic

3. **Removes problematic requirements**: Cleaned `requirements.txt` to avoid duplicate package installation

This approach scales to multiple agent patterns without code duplication while maintaining clean Docker builds.

### Key Resources Created

1. **Backend Stack**: 
   - Cognito User Pool integration and machine client
   - AgentCore Gateway with Lambda tool targets
   - AgentCore Runtime for agent execution
   - ECR repository for agent container images
   - CodeBuild project for container builds
   - DynamoDB table for application data
   - API Gateway for feedback endpoints
   - IAM roles and policies

2. **Amplify Hosting Stack**:
   - Amplify app for frontend deployment
   - Automatic builds from Git branches
   - Custom domain and SSL certificate integration
   - Environment-specific deployments

## Troubleshooting

### Build Errors

If you encounter TypeScript compilation errors:
```bash
npm run build
```

### Deployment Failures

Check CloudFormation events in the AWS Console for detailed error messages.

### Clean Build

If you need to start fresh:
```bash
rm -rf node_modules cdk.out
npm install
npm run build
```

## Testing

Run unit tests:
```bash
npm test
```

## Learn More

- [AWS CDK Documentation](https://docs.aws.amazon.com/cdk/)
- [AWS CDK TypeScript Reference](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-construct-library.html)
- [Bedrock AgentCore Documentation](https://docs.aws.amazon.com/bedrock/)
