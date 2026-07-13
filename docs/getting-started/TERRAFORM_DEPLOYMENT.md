<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Terraform Deployment Guide

This guide walks you through deploying the Agentic ERP Automation Quickstart to AWS using Terraform.

> **CDK alternative:** This guide covers Terraform deployment. This project also supports AWS CDK -- see [Deployment Guide](DEPLOYMENT.md) for the CDK deployment guide. We recommend choosing one infrastructure tool and deleting the other directory (`cdk/` or `terraform/`) from your fork to keep things clean.

> **Auth-profile scope — Terraform deploys `cognito-basic` only.** Terraform consumes just the
> inbound axis; the outbound (SAP MCP target), mode (batch runner), and frontend (direct-IdP SPA)
> axes are CDK-only, with no Terraform module. Any profile past `cognito-basic` — `cognito-m2m`,
> `entra-obo`, `okta-userfed`, or any Entra/Okta inbound — **loud-fails at `terraform plan`** with a
> "CDK-only" message (this guard is intentional). If you are testing auth-matrix permutations, use
> the [CDK backend](DEPLOYMENT.md). See [Auth Profile Selection](../sap/AUTH_PROFILE_SELECTION.md#terraform-scope).

## Prerequisites

Before deploying, ensure you have:

- **Terraform** >= 1.5.0 (see [Install Terraform](https://developer.hashicorp.com/terraform/install))
- **AWS CLI** configured with credentials (`aws configure`) - see [AWS CLI Configuration guide](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-quickstart.html)
- **Python 3.11+** (for the frontend deployment script)
- **Docker** (only required for `backend_deployment_type = "docker"`) - see [Install Docker Engine](https://docs.docker.com/engine/install/). Verify with `docker ps`. Alternatively, [Finch](https://github.com/runfinch/finch) can be used on Mac. See [below](#docker-cross-platform-build-setup-required-for-non-arm-machines) if you have a non-ARM machine.

  > **Note:** Docker/Finch is not needed for `backend_deployment_type = "zip"` (the default). Lambda dependencies are bundled locally using `pip install`.
- An AWS account with sufficient permissions to create:
  - S3 buckets
  - Cognito User Pools
  - Amplify Hosting projects
  - Bedrock AgentCore resources
  - IAM roles and policies

## Configuration

### 1. Create Configuration File

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` to customize your deployment:

```hcl
stack_name_base = "your-project-name"  # Base name for all resources (max 35 chars)

admin_user_email = "admin@example.com" # Optional: auto-creates user & emails credentials
```

**Important**:
- Change `stack_name_base` to a unique name for your project to avoid conflicts
- Maximum length is 35 characters (due to AWS AgentCore runtime naming constraints)
- **No underscores** — use hyphens instead (e.g. `my-project` not `my_project`). Underscores cause failures in AWS resource naming (S3 buckets, Cognito, etc.)

#### Required Variables

| Variable | Description |
|----------|-------------|
| `stack_name_base` | Base name for all resources |

#### Optional Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `admin_user_email` | Email for Cognito admin user | `null` |
| `backend_pattern` | Agent pattern to deploy | `"strands-single-agent"` |
| `backend_deployment_type` | `"docker"` (ECR container) or `"zip"` (S3 package) | `"docker"` |
| `backend_network_mode` | Network mode (PUBLIC/VPC) | `"PUBLIC"` |
| `backend_vpc_id` | VPC ID (required when VPC mode) | `null` |
| `backend_vpc_subnet_ids` | Subnet IDs (required when VPC mode) | `[]` |
| `backend_vpc_security_group_ids` | Security group IDs (optional for VPC mode) | `[]` |

**Region:** Set via the `AWS_REGION` environment variable or AWS CLI profile (`aws configure`). The Terraform provider uses the standard AWS SDK resolution chain -- no region variable is needed.

**Tags:** The provider applies default tags (Project, ManagedBy, Repository) to all resources automatically. Add custom tags directly in the provider's `default_tags` block in `main.tf`.

### Deployment Types

Set `backend_deployment_type` in `terraform.tfvars` to `"zip"` (default) or `"docker"`. See [Deployment Types](DEPLOYMENT.md#deployment-types) in the main Deployment Guide for guidance on choosing between them.

**Terraform-specific notes:**
- ZIP mode does not require Docker installed locally
- **ZIP packaging includes**: The `agentcore/<your-pattern>/` (e.g. `agentcore/agent/`), `agentcore/agent/utils/`, and `tools/` directories are bundled together with dependencies from `requirements.txt`

### Deployment into existing VPC

By default, the AgentCore Runtime runs in PUBLIC network mode with internet access. To deploy the runtime into an existing VPC for private network isolation, set `backend_network_mode = "VPC"` and provide your VPC details:

```hcl
backend_network_mode           = "VPC"
backend_vpc_id                 = "vpc-0abc1234def56789a"
backend_vpc_subnet_ids         = ["subnet-aaaa1111bbbb2222c", "subnet-cccc3333dddd4444e"]
backend_vpc_security_group_ids = ["sg-0abc1234def56789a"]  # Optional
```

The `backend_vpc_id` and `backend_vpc_subnet_ids` fields are required when using VPC mode. The `backend_vpc_security_group_ids` field is optional -- if omitted, a default security group is created with HTTPS (TCP 443) self-referencing ingress and all-traffic egress.

For detailed VPC prerequisites -- including required VPC endpoints, subnet requirements, NAT Gateway guidance, and security group configuration -- see [VPC Deployment](DEPLOYMENT.md#vpc-deployment) in the main Deployment Guide.

**Important:** AgentCore Runtime availability is limited to specific Availability Zones per region. Verify your subnets are in supported AZs before deploying. See [AWS documentation on supported Availability Zones](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html#agentcore-supported-azs) for details.

## Deployment Steps

### TL;DR
```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your configuration
terraform init
terraform apply
python scripts/deploy/deploy-frontend.py
```

### 1. Initialize Terraform

```bash
cd terraform
terraform init
```

### 2. Deploy Infrastructure

Build and deploy the complete stack:

```bash
terraform apply
```

The deployment will:

1. Create Amplify Hosting app and S3 staging bucket
1. Create a Cognito User Pool with web and machine clients
1. Create AgentCore Memory for persistent conversations
1. Set up OAuth2 Credential Provider for Runtime-to-Gateway authentication
1. Create AgentCore Gateway with Lambda tool targets
1. Build and deploy the AgentCore Runtime (Docker image or ZIP package)
1. Create the Feedback API (API Gateway + Lambda + DynamoDB)
1. Store configuration in SSM Parameters

- **Docker mode** (default): Automatically builds an ARM64 Docker image, pushes to ECR, and creates the runtime. Requires Docker to be running locally.
- **Zip mode**: Deploys a packager Lambda that bundles your agent code with ARM64 wheels, uploads to S3, and creates the runtime. No Docker required.

> **Note:** If you provide a pre-built image via `container_uri`, Terraform skips the build and uses your image directly.

### 3. Deploy Frontend

```bash
# From terraform directory
python scripts/deploy/deploy-frontend.py
```

This script automatically:

- Generates fresh `aws-exports.json` from Terraform outputs (see [below](#understanding-aws-exportsjson) for more information)
- Installs/updates npm dependencies if needed
- Builds the frontend
- Deploys to AWS Amplify Hosting

You will see the URL for the application in the script's output, which will look similar to this:

```
App URL: https://main.d123abc456def7.amplifyapp.com
```

A shell alternative is also available for macOS/Linux:
```bash
python scripts/deploy/deploy-frontend.py
```

### 4. Create a Cognito User (if necessary)

**If you provided `admin_user_email` in config:**

- Check your email for temporary password
- Sign in and change password on first login

**If you didn't provide email:**

1. Go to the [AWS Cognito Console](https://console.aws.amazon.com/cognito/)
2. Find your User Pool (named `{stack_name_base}-user-pool`)
3. Click on the User Pool
4. Go to "Users" tab
5. Click "Create user"
6. Fill in the user details:
   - **Email**: Your email address
   - **Temporary password**: Create a temporary password
   - **Mark email as verified**: Check this box
7. Click "Create user"

### 5. Access the Application

1. Open the Amplify Hosting URL in your browser
1. Sign in with the Cognito user you created
1. You'll be prompted to change your temporary password on first login

## Post-Deployment

### Updating the Application

To update the frontend code:

```bash
# From terraform directory
python scripts/deploy/deploy-frontend.py
```

To update the backend agent:

```bash
cd terraform
terraform apply
```

Terraform detects code changes automatically and rebuilds/redeploys the runtime. After a backend update that replaces the runtime, redeploy the frontend to pick up the new Runtime ARN:

```bash
python scripts/deploy/deploy-frontend.py
```

#### Manual Docker Build (Optional)

If you prefer to build the Docker image separately (e.g., in CI/CD):
```bash
./scripts/build-and-push-image.sh
```

**Options:**
```bash
./scripts/build-and-push-image.sh -h                          # Show help
./scripts/build-and-push-image.sh -p agent   # Use the Strands agent pattern
./scripts/build-and-push-image.sh -s my-stack -r us-west-2    # Override stack/region
```

### Verify Deployment

```bash
# Get deployment summary
terraform output deployment_summary

# Get all outputs
terraform output
```

### Test the Agent (Optional)

```bash
# From terraform directory
pip install boto3 requests colorama  # First time only
python scripts/test-agent.py 'Hello, what can you do?'
```

### Monitoring and Logs

- **Frontend logs**: Check Amplify build logs in the AWS Console
- **Backend logs**: Check CloudWatch logs for the AgentCore runtime
- **Feedback API logs**: Check CloudWatch logs for the feedback Lambda

## Cleanup

To remove all resources:

```bash
cd terraform
terraform destroy
```

Terraform handles resource dependencies automatically and destroys in the correct order.

**Warning**: This will delete all data including Cognito users, S3 buckets, DynamoDB tables, and ECR images.

### Verify Cleanup

After destroy completes, verify no resources remain:
```bash
aws resourcegroupstaggingapi get-resources --tag-filters Key=Project,Values=<your-stack-name>
```

## Troubleshooting

### Common Issues

1. **`terraform apply` fails with Docker errors**

   - This only applies to `backend_deployment_type = "docker"`
   - Ensure Docker is installed and the daemon is running: `docker ps`
   - On Mac, open Docker Desktop or start Finch: `finch vm start && export CDK_DOCKER=finch`
   - On Linux: `sudo systemctl start docker`
   - Switch to `backend_deployment_type = "zip"` to avoid Docker entirely

2. **"Architecture incompatible" or "exec format error" during Docker build**

   - This occurs when deploying from a non-ARM machine without cross-platform build setup
   - Follow the [Docker Cross-Platform Build Setup](#docker-cross-platform-build-setup-required-for-non-arm-machines) instructions below
   - Ensure you've installed QEMU emulation: `docker run --privileged --rm tonistiigi/binfmt --install all`
   - Verify ARM64 support: `docker buildx ls` should show `linux/arm64` in platforms

3. **Terraform Init Fails**

   Ensure you have the correct provider versions:
   ```bash
   terraform init -upgrade
   ```

4. **Authentication errors**

   Verify AWS credentials:
   ```bash
   aws sts get-caller-identity
   ```

   Also verify you created a Cognito user and that the user's email is verified.

5. **"Agent Runtime ARN not configured" or 404 errors**

   - Ensure the backend deployed successfully
   - Redeploy the frontend to pick up the latest Runtime ARN:
     ```bash
     python scripts/deploy/deploy-frontend.py
     ```
   - Verify SSM parameters match Terraform outputs:
     ```bash
     terraform output runtime_arn
     ```

6. **Permission errors**
   - Verify your AWS credentials have sufficient permissions
   - Check IAM roles created by the stack

### Getting Help

- Check CloudWatch logs for detailed error messages
- Review `terraform output` for resource identifiers
- Ensure all prerequisites are met

## Security Considerations

See [Security Considerations](DEPLOYMENT.md#security-considerations) in the main Deployment Guide. Additionally, consider deploying in [VPC mode](#deployment-into-existing-vpc) for network isolation.

## Docker Cross-Platform Build Setup (Required for non-ARM machines)

Bedrock AgentCore Runtime only supports ARM64 architecture. If you're deploying from a non-ARM machine (x86_64/amd64), you need to enable Docker's cross-platform building capabilities.

## Understanding aws-exports.json

The `aws-exports.json` file provides the frontend with Cognito authentication configuration.

For Terraform deployments, the file is generated by `deploy-frontend.py` which fetches configuration from `terraform output -json` (rather than CDK stack outputs). You should not manually edit this file as it's regenerated on each deployment.
