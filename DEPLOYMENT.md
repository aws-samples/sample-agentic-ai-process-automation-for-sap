# SAP Invoice Exception Handling - Deployment Guide

Complete deployment instructions and configuration for the SAP Invoice Exception Handling system.

---

## ⚠️ Important Disclaimer

**This code is not meant for production deployment** but to demonstrate how agentic AI systems can be architected for SAP exception handling. It serves as a reference implementation to understand how different components come together to create an intelligent automation solution. Additional considerations needed for security, monitoring, error handling, and compliance requirements.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Architecture](#architecture)
- [Deployment Steps](#deployment-steps)
- [Configuration](#configuration)
- [Usage](#usage)
- [Monitoring](#monitoring)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### AWS Account Requirements

- AWS Account with appropriate permissions
- AWS CLI configured with credentials
- **Python 3.11+** installed (minimum supported version)
- Lambda functions use Python 3.13 runtime
- Ensure your local environment has Python 3.11 or higher
- Access to Amazon Bedrock (Claude 3.7 Sonnet model - configurable via MODEL_ID)

### SAP System Requirements

- SAP S/4HANA system with OData APIs enabled
- SAP user account with permissions for:
  - Reading supplier invoices (API_SUPPLIERINVOICE_PROCESS_SRV)
  - Reading purchase orders (API_PURCHASEORDER_PROCESS_SRV)
  - Reading material documents/goods receipts (API_MATERIAL_DOCUMENT)
  - Releasing blocked invoices (API_SUPPLIERINVOICE_PROCESS_SRV - Release operation)
  - Creating goods receipts (API_MATERIAL_DOCUMENT - POST operations)
- Network connectivity from AWS to SAP system

### Email Configuration (SES)

**Required for inbound email processing:**
- Verified domain or email address in Amazon SES
- SES receipt rule set created and activated
- SES receipt rule configured to deliver emails to S3 bucket
- S3 bucket configured with event notification to trigger Lambda
- Lambda permission for S3 to invoke the function

**Email addresses (defined in SOP, not hardcoded):**
- Agent email (for receiving stakeholder responses) - Agent queries this from SOP
- Procurement team email (for escalation) - Agent queries this from SOP
- Receiving dock email (for goods receipt confirmation) - Agent queries this from SOP
- Supplier email (for delivery inquiries) - Agent queries this from SOP

**Note:** Email addresses are stored in the SOP document, not in environment variables. The agent dynamically queries the SOP for stakeholder email addresses based on the workflow context. Only the agent's receiving email needs to be configured in SES for inbound processing.

**What deploy_mcp_and_agent_script.py Automates:**
- ✅ Creates S3 bucket for email storage
- ✅ Configures S3 bucket policy to allow SES writes
- ✅ Deploys email processor Lambda function
- ✅ Sets up S3 event notification to trigger Lambda
- ✅ Adds Lambda permission for S3 invocation

**What Requires Manual Steps:**
- ❗ **Email setup and verification** - You must verify the sender email address/domain in SES console before sending emails
- ❗ **SES receipt rules** - Configure SES to receive emails and route to S3

**Reference**: For detailed SES inbound email setup, see [AWS Knowledge Center - SES Receive Inbound Emails](https://repost.aws/knowledge-center/ses-receive-inbound-emails)

---

## Architecture

### System Components

The system consists of the following AWS components:

1. **Amazon S3** - Storage for SOPs, API documentation, emails, and data
2. **AWS Secrets Manager** - Secure storage for SAP credentials (username/password) and Cognito configuration
3. **AWS Systems Manager (SSM) Parameter Store** - Configuration management
   - Stores all resource ARNs and identifiers
   - Stores bucket names, table names, Knowledge Base IDs
4. **Amazon DynamoDB** - Case state management and agent scope
   - Primary key: transaction_number (invoice number)
   - Maintains processing state and audit logs
   - Enables reporting on case status and actions taken
5. **AWS Lambda** - SAP OData polling function and email processor
6. **Amazon EventBridge** - Scheduled polling (every 5 minutes)
7. **Amazon Bedrock** - Knowledge Bases for SOPs and API docs
8. **Bedrock AgentCore** - MCP server and Strands agent runtime
   - **Public domain**: For publicly accessible SAP systems (default)
   - **VPC deployment**: For private SAP systems (manual configuration)
9. **Amazon SES** - Email communication (inbound and outbound)
10. **Amazon Cognito** - Authentication for MCP server access
11. **Amazon CloudWatch** - Logging and monitoring for all components
12. **Streamlit** - Web dashboard (local deployment for demo, can be swapped)

### SAP Integration

**Standard APIs**:
- API_SUPPLIERINVOICE_PROCESS_SRV (Supplier Invoices)
- API_PURCHASEORDER_PROCESS_SRV (Purchase Orders)
- API_MATERIAL_DOCUMENT (Goods Receipts)
- API_SALES_ORDER_SRV (Sales Orders - optional)

### Data Flow

**Option 1: EventBridge Polling (Current Implementation)**

```
EventBridge (5 min) → Lambda → SAP OData APIs → DynamoDB
                                                    ↓
User → Streamlit Dashboard → Strands Agent → MCP Server → SAP/DynamoDB/SES
                                                    ↓
                                            Resolution Complete
                                                    ↓
                                        SAP Invoice Released/GR Created
```

**Option 2: Direct SAP Integration (Alternative)**

```
SAP System → AWS ABAP SDK → DynamoDB (direct insert)
                                ↓
User → Streamlit Dashboard → Strands Agent → MCP Server → SAP/DynamoDB/SES
                                ↓
                        Resolution Complete
                                ↓
                    SAP Invoice Released/GR Created
```

**DynamoDB as Agent Scope**:
- DynamoDB acts as the **scope** for agents to identify relevant exceptions
- Maintains **state** for each case (pending, processing, resolved, escalated)
- Stores complete **audit logs** in processing_history
- Enables **reporting** on case status and actions taken
- Supports building dashboards to track which cases are at what stage

### Alternative: Direct SAP Integration

Instead of using EventBridge and Lambda polling, you can use the **AWS ABAP SDK** to insert cases directly from SAP into DynamoDB:

**Benefits**:
- Real-time case creation (no polling delay)
- Reduced AWS Lambda costs
- Tighter SAP integration
- Event-driven architecture

**Implementation**:
1. Install AWS ABAP SDK in your SAP system
2. Configure AWS credentials in SAP
3. Create ABAP program to identify invoice exceptions
4. Use SDK to insert cases directly to DynamoDB table
5. Agent picks up cases from DynamoDB as usual

**Use Case**: This approach is ideal when you want SAP to push data to AWS rather than AWS polling SAP.

### Technology Stack

- **AI/ML**: Amazon Bedrock (configurable model via MODEL_ID, default: Claude 3.7 Sonnet), Bedrock AgentCore, Bedrock Knowledge Base
- **Agent Framework**: Strands (AWS open-source agentic framework)
- **Integration**: Model Context Protocol (MCP) for tool orchestration
- **Compute**: AWS Lambda (serverless functions), Bedrock AgentCore Runtime
- **Storage**: Amazon DynamoDB (case state), Amazon S3 (documents, SOPs)
- **Communication**: Amazon SES (email), Amazon EventBridge (scheduling)
- **SAP Integration**: SAP OData APIs (REST/JSON)
- **UI**: Streamlit (Python web framework)
- **IaC**: Python deployment script (boto3)

---

## Deployment Steps

### Step 1: Clone the Repository

```bash
git clone <repository-url>
cd sap-exception-handling
```

### Step 2: Set Up Python Environment

**Requirements**: Python 3.11 or higher

```bash
# Verify Python version (must be 3.11+)
python3 --version

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate  # On macOS/Linux
# OR
venv\Scripts\activate  # On Windows

# Install dependencies
pip install -r requirements.txt
```

**Note**: Lambda functions are deployed with Python 3.13 runtime. Ensure your local environment has Python 3.11+ for compatibility.

### Step 3: Configure Environment Variables

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Edit `.env` with your configuration:

```bash
# AWS Configuration
AWS_REGION=us-east-1
AWS_ACCOUNT_ID=123456789012

# SAP Configuration
SAP_BASE_URL=https://your-sap-system.com
SAP_USERNAME=your-sap-username
SAP_PASSWORD=your-sap-password

# Email Configuration (Note: Email addresses are defined in SOP, not used by deployment)
# These are for reference only - the agent queries email addresses from the SOP
AGENT_EMAIL=invoice-agent@yourdomain.com  # Used for SES verification only

# Bedrock Configuration (Any Bedrock model can be used - just update MODEL_ID)
MODEL_ID=us.anthropic.claude-3-7-sonnet-20250219-v1:0

# Deployment Configuration
DEPLOYMENT_PHASE=all  # or: phase1, phase2, phase3, phase4
```

**IMPORTANT: Update Email Addresses in SOP**

Before deployment, you MUST update the email addresses in the SOP file to match your organization's contacts:

1. Open `sops/Supplier_Invoices_Exception_Handling_SOP_RFC2119.md`
2. Search for `@abc.company.com` email addresses
3. Replace with your actual stakeholder emails:
   - `test1@abc.company.com`, `test2@abc.company.com`, `test3@abc.company.com` → Receiving dock contacts
   - `test4@abc.company.com`, `test5@abc.company.com`, `test6@abc.company.com` → Supplier/vendor contacts
4. Update Section 6 (Contact Information) with the same email addresses

The agent dynamically queries these email addresses from the SOP during workflow execution.

### Step 4: Verify SES Email Addresses

Before deployment, verify your sender email in Amazon SES:

```bash
aws ses verify-email-identity --email-address invoice-agent@yourdomain.com
```

Check your email and click the verification link.

### Step 5: Deploy Infrastructure

The deployment script handles all AWS resource creation:

```bash
python deploy_mcp_and_agent_script.py
```

#### What deploy_mcp_and_agent_script.py Automates

The script automatically handles:

✅ **DynamoDB** - Creates table with transaction_number as primary key  
✅ **Secrets Manager** - Stores SAP credentials and Cognito config securely  
✅ **Lambda Functions** - Deploys OData poller and email processor  
✅ **EventBridge** - Sets up scheduled polling (every 5 minutes)  
✅ **IAM Roles & Policies** - Configures all necessary permissions  
✅ **S3 Buckets** - Creates buckets for SOPs, API docs, and emails  
✅ **S3 Bucket Policies** - Allows SES to write emails  
✅ **S3 Event Notifications** - Triggers Lambda on email arrival  
✅ **Cognito** - Sets up authentication for AgentCore  
✅ **MCP Server** - Deploys to Bedrock AgentCore runtime  
✅ **Strands Agent** - Deploys to Bedrock AgentCore runtime  
✅ **SSM Parameters** - Stores all configuration  
✅ **Knowledge Bases** - Uploads SOPs and API docs to S3  

#### Manual Steps Required

❗ **Email Verification** - Verify email address/domain in SES console  
❗ **SES Receipt Rules** - Configure SES to receive emails (if using email workflows)  
❗ **Knowledge Bases** - Create in Bedrock console (script uploads files to S3)  
❗ **VPC Configuration** - If using private SAP endpoint, manually update MCP/Agent to VPC deployment  

#### Deployment Process

The script will:

1. **Create DynamoDB Table**
   - Creates table for transaction state storage
   - Primary key: transaction_number
   - Enables TTL for automatic cleanup

2. **Store SAP Credentials**
   - Stores credentials in Secrets Manager
   - Encrypts with KMS

3. **Upload Documentation**
   - Uploads SOP documents to S3
   - Uploads SAP API documentation to S3
   - Note: You'll need to create Knowledge Bases manually in Bedrock console

4. **Deploy Lambda Functions**
   - Deploys OData poller Lambda
   - Deploys email processor Lambda
   - Configures EventBridge rule (5-minute polling)
   - Sets up S3 event notifications

5. **Setup Cognito Authentication**
   - Creates Cognito User Pool
   - Generates bearer tokens
   - Stores credentials in Secrets Manager

6. **Deploy AgentCore Runtimes**
   - Deploys MCP server to AgentCore
   - Deploys Strands agent to AgentCore
   - Stores ARNs in SSM Parameter Store

7. **Configure IAM Permissions**
   - Adds comprehensive permissions to all roles
   - Configures least privilege access

### Step 5a: Manual Knowledge Base Creation (First Time Only)

**Important**: The deployment script uploads files to S3 but **Knowledge Bases must be created manually** in the Bedrock console.

#### Create SOP Knowledge Base

1. **Go to Bedrock Console**
   - Navigate to: https://console.aws.amazon.com/bedrock/home#/knowledge-bases
   - Click "Create knowledge base"

2. **Knowledge Base Details**
   - Name: `SAP-Invoice-Exception-SOP-KB`
   - Description: `Standard Operating Procedures for SAP Invoice Exception Handling`
   - Click "Next"

3. **Configure Data Source**
   - Data source name: `sop-s3-source`
   - Data source type: **Amazon S3**
   - S3 URI: Browse and select the bucket created by script (e.g., `sap-invoice-sops-{account-id}`)
   - Click "Next"

4. **Select Embeddings Model**
   - Embeddings model: **Titan Text Embeddings V2**
   - Click "Next"

5. **Configure Vector Store**
   - Vector database: **Quick create a new vector store**
   - This will create an Amazon OpenSearch Serverless collection automatically
   - Click "Next"

6. **Review and Create**
   - Review all settings
   - Click "Create knowledge base"
   - **Wait for creation to complete** (may take 2-3 minutes)
   - **Copy the Knowledge Base ID** (e.g., `ABCDEFGHIJ`)

#### Create API Documentation Knowledge Base

Repeat the same steps for API documentation:

1. **Go to Bedrock Console**
   - Click "Create knowledge base"

2. **Knowledge Base Details**
   - Name: `SAP-API-Docs-KB`
   - Description: `SAP API Documentation for Invoice Exception Handling`
   - Click "Next"

3. **Configure Data Source**
   - Data source name: `api-docs-s3-source`
   - Data source type: **Amazon S3**
   - S3 URI: Browse and select the bucket (e.g., `sap-api-docs-{account-id}`)
   - Click "Next"

4. **Select Embeddings Model**
   - Embeddings model: **Titan Text Embeddings V2**
   - Click "Next"

5. **Configure Vector Store**
   - Vector database: **Quick create a new vector store**
   - Click "Next"

6. **Review and Create**
   - Click "Create knowledge base"
   - **Wait for creation to complete**
   - **Copy the Knowledge Base ID**

#### Update .env File

Add the Knowledge Base IDs to your `.env` file:

```bash
# Add these lines to .env
KNOWLEDGE_BASE_ID=YOUR_SOP_KB_ID_HERE
SAP_API_KNOWLEDGE_BASE_ID=YOUR_API_KB_ID_HERE
```

#### Subsequent Deployments

**Good news**: This manual step is only required the first time. For subsequent deployments:
- The script will automatically sync any changes to SOP or API docs files
- Knowledge Bases will be updated automatically
- No manual console work needed

### Step 6: Verify Deployment

After deployment, verify each component:

#### 1. Check DynamoDB Table

```bash
aws dynamodb describe-table --table-name invoice-state-dev
```

#### 2. Check S3 Buckets

```bash
aws s3 ls | grep sap
```

#### 3. Check Secrets Manager

```bash
aws secretsmanager describe-secret --secret-id sap_credentials
```

#### 4. Check Lambda Functions

```bash
aws lambda get-function --function-name invoice-odata-poller-dev
aws lambda get-function --function-name s3-email-processor-dev
```

#### 5. Check SSM Parameters

```bash
aws ssm get-parameters-by-path --path /sap --recursive
```

#### 6. Check AgentCore Runtimes

```bash
aws ssm get-parameter --name /sap_mcp_server/runtime/agent_arn
aws ssm get-parameter --name /sap_strands_agent/runtime/agent_arn
```

### Step 7: Initial Data Load

Trigger the Lambda function manually to create initial cases:

```bash
aws lambda invoke \
  --function-name invoice-odata-poller-dev \
  --payload '{}' \
  response.json

cat response.json
```

This will:
- Query SAP for blocked invoices
- Filter invoices with payment blocking reasons
- Create cases in DynamoDB with status = 'pending'

### Step 8: Configure MCP Server and Strands Agent Network Settings (Optional)

**Important**: The deployment script automatically deploys the MCP server and Strands agent as Bedrock AgentCore runtimes to the **public domain** by default. If your SAP system is in a private VPC, you need to manually update the network configuration to VPC deployment.

#### Network Configuration Options

Choose the deployment option based on your SAP system's network accessibility:

**Option 1: Public SAP Endpoint (Current Setup)**
- Deploy MCP server to Bedrock AgentCore **public domain**
- Suitable when SAP system is publicly reachable
- Simpler setup, no VPC configuration needed

**Option 2: Private SAP Endpoint (Secure Connectivity)**
- Deploy MCP server to Bedrock AgentCore **in VPC**
- Deploy to the **same VPC as your SAP system**
- Ensures secure, private connectivity
- Required when SAP is in a private network

**To Configure VPC Deployment**:
1. After deploying the MCP server, go to **Bedrock AgentCore** console
2. Navigate to **Agent Runtime**
3. Click **Update Hosting**
4. Go to **Advanced Configurations**
5. Select **VPC** instead of Public
6. Select the **same VPC that your SAP system is hosted on**
7. Configure security groups to allow connectivity to SAP
8. Save changes

#### MCP Server Deployment

The MCP server (`mcp_server/sap_mcp_server.py`) provides tools for:
- SAP OData API integration with CSRF token management
- DynamoDB state management
- Email communication via SES
- Knowledge Base queries for SOPs and API documentation

**What deploy_mcp_and_agent_script.py Automates**:
1. ✅ Packages the MCP server code with dependencies
2. ✅ Deploys to Bedrock AgentCore runtime (public domain)
3. ✅ Sets up Cognito authentication
4. ✅ Stores MCP server ARN in SSM Parameter Store

**Manual Step (Only if using private SAP endpoint)**:
- Update MCP server to VPC deployment following steps above

#### Strands Agent Deployment

The Strands agent (`strands_agent/strands_sap_agent_claude.py`) orchestrates the entire workflow:
- Follows SOPs for decision-making
- Calls MCP tools for SAP integration
- Manages email workflows
- Performs 3-way matching validation

**What deploy_mcp_and_agent_script.py Automates**:
1. ✅ Packages the Strands agent code
2. ✅ Deploys to Bedrock AgentCore runtime (public domain)
3. ✅ Configures connection to MCP server
4. ✅ Stores agent ARN in SSM Parameter Store

**Manual Step (Only if using private SAP endpoint)**:
- Update Strands agent to VPC deployment following the same VPC configuration steps as MCP server

### Step 9: Launch Streamlit Dashboard

```bash
# Activate virtual environment if not already active
source venv/bin/activate

# Set AWS credentials
export AWS_ACCESS_KEY_ID=your-access-key
export AWS_SECRET_ACCESS_KEY=your-secret-key
export AWS_DEFAULT_REGION=us-east-1

# Run Streamlit app
streamlit run streamlit_dashboard/app.py
```

The dashboard will open in your browser at `http://localhost:8501`.

---

## Configuration

### DynamoDB Schema

**Table**: `invoice-state-dev`

**Primary Key**:
- Partition Key: `transaction_number` (String) - SAP Invoice Number

**Attributes**:

```json
{
  "transaction_number": "1900000002",
  "document_date": "2021-11-05T00:00:00.000Z",
  "status": "pending",
  "message_type": "INVOICE_EXCEPTION",
  "exception_type": "A",
  "transaction_type": "Invoice receipt",
  "supplier_number": "17300081",
  "amount": "200.00",
  "currency": "USD",
  "external_reference": "INV2022",
  "created_on": "2025-11-24T09:00:00Z",
  "timestamp": "2025-11-24T09:00:00Z",
  "state_version": 1,
  "processing_history": [
    {
      "processor": "ODataPoller",
      "action": "create",
      "timestamp": "2025-11-24T09:00:00Z",
      "result": "pending",
      "details": {"initialState": true}
    }
  ],
  "auto_resolved": false,
  "is_active": true,
  "requires_human_review": false,
  "last_modified_at": "2025-11-24T09:00:00Z",
  "metrics": {"processing_time": "0", "retry_count": "0"},
  "ttl": 1735689600
}
```

### SSM Parameters

All configuration is stored in AWS Systems Manager Parameter Store:

```
/sap_mcp_server/runtime/agent_arn
/sap_strands_agent/runtime/agent_arn
/sap/dynamodb/table-name
/sap/s3/sops-bucket
/sap/s3/api-docs-bucket
/sap/s3/email-bucket
```

### Secrets Manager

SAP credentials are stored securely in AWS Secrets Manager:

```json
{
  "username": "your-sap-username",
  "password": "your-sap-password"
}
```

Cognito configuration is also stored in Secrets Manager:

```json
{
  "user_pool_id": "us-east-1_XXXXXXXXX",
  "client_id": "XXXXXXXXXXXXXXXXXXXXXXXXXX",
  "client_secret": "XXXXXXXXXXXXXXXXXXXXXXXXXX",
  "discovery_url": "https://cognito-idp.us-east-1.amazonaws.com/...",
  "bearer_token": "eyJraWQiOiI..."
}
```

---

## Usage

### Processing an Invoice Exception Case

1. **Open the Dashboard**
   - Navigate to `http://localhost:8501`
   - You'll see a list of detected invoice exception cases

2. **Select a Case**
   - Review the case details (invoice number, exception type, amount, supplier)
   - Click the "Process" button

3. **Agent Processing**
   - The agent will stream its progress in real-time
   - You'll see each step as it executes:
     - Retrieving case state from DynamoDB
     - Querying SAP for invoice, PO, and GR details
     - Performing 3-way matching validation
     - Determining resolution path
     - Executing resolution (create GR, release invoice, etc.)
     - Sending confirmation emails

4. **Review Results**
   - Check processing history in the dashboard
   - Verify resolution in SAP
   - Review audit trail in DynamoDB

### Email Workflows

#### Escalation Email (Complex Cases)

For cases requiring human input:

1. Agent sends escalation email to procurement/receiving dock
2. Stakeholder replies with required information
3. Agent parses response from email
4. Agent takes corrective action in SAP
5. Agent sends confirmation to stakeholders

#### Confirmation Email (All Cases)

For all processed cases:

1. Agent completes resolution
2. Agent sends confirmation email with:
   - Complete case details
   - Actions taken
   - SAP transaction numbers
   - Next steps if any

---

## Monitoring

### View Case Status

```bash
aws dynamodb scan \
  --table-name invoice-state-dev \
  --filter-expression "attribute_exists(#status)" \
  --expression-attribute-names '{"#status":"status"}'
```

### View Processing History

Check the `processing_history` field in DynamoDB for complete audit trail of agent actions.

### View Lambda Logs

```bash
aws logs tail /aws/lambda/invoice-odata-poller-dev --follow
aws logs tail /aws/lambda/s3-email-processor-dev --follow
```

### View Agent Logs

Agent logs are available in CloudWatch Logs under the Bedrock AgentCore runtime log group:

```bash
# Get MCP server logs
aws logs tail /aws/bedrock-agentcore/runtimes/sap_mcp_server-DEFAULT --follow

# Get Strands agent logs
aws logs tail /aws/bedrock-agentcore/runtimes/sap_strands_agent-DEFAULT --follow
```

---

## Troubleshooting

### Common Issues

#### 1. Lambda Function Fails to Query SAP

**Symptom**: Lambda function returns error when querying SAP OData APIs

**Solutions**:
- Verify SAP credentials in Secrets Manager
- Check network connectivity from Lambda to SAP system
- Verify SAP user has required permissions
- Check SAP OData service is enabled and accessible

#### 2. Agent Cannot Connect to MCP Server

**Symptom**: Agent fails with connection errors

**Solutions**:
- Verify MCP server is deployed as Bedrock AgentCore runtime
- Check MCP server ARN in SSM Parameter Store
- Check Cognito credentials in Secrets Manager
- Agent automatically refreshes Cognito token on startup
- Verify network connectivity and IAM permissions

#### 3. Knowledge Base Queries Return No Results

**Symptom**: Agent cannot find SOPs or API documentation

**Solutions**:
- Verify Knowledge Base IDs in .env file
- Check documents are uploaded to S3
- Verify OpenSearch Serverless index is created
- Re-sync Knowledge Base data sources in Bedrock console

#### 4. Email Not Sending

**Symptom**: Agent fails to send emails

**Solutions**:
- Verify sender email is verified in SES
- Check SES sending limits (sandbox vs. full access)
- Verify recipient email addresses are valid
- Check SES logs in CloudWatch

#### 5. Email Not Being Received/Processed

**Symptom**: Agent doesn't respond to email replies

**Solutions**:
- Verify SES receipt rules are configured
- Check S3 bucket has emails
- Verify S3 event notification is triggering Lambda
- Check email processor Lambda logs

### Getting Help

For issues not covered here:

1. Check CloudWatch Logs for detailed error messages
2. Review DynamoDB processing_history for agent actions
3. Verify all prerequisites are met
4. Check AWS service quotas and limits

---

## Customizing SOPs for Your Business Process

### SOP Format Recommendations

**Preferred Approach: PDF Format**

For production deployments, we strongly recommend using **PDF format** for your SOPs:

**Benefits of PDF SOPs:**
- **Immutable**: Cannot be accidentally edited or modified
- **Version Control**: Clear versioning with document metadata
- **Professional**: Maintains formatting and structure
- **Audit Trail**: Signed and approved documents
- **Compliance**: Meets regulatory requirements for documentation

**Development Workflow:**

1. **Start with the Markdown Template**
   - Use `sops/Supplier_Invoices_Exception_Handling_SOP_RFC2119.md` as your starting point
   - This file demonstrates RFC2119 compliance and proper structure
   - Contains examples of all required sections

2. **Customize for Your Business Process**
   - Edit the markdown file to match your specific workflows
   - Update exception scenarios to reflect your business rules
   - Modify contact information and escalation paths
   - Add or remove resolution steps as needed
   - Update email addresses and stakeholder roles

3. **Convert to PDF**
   - Once finalized, convert the markdown to PDF
   - Add document metadata (version, approval date, approvers)
   - Sign and approve the PDF document
   - Store the PDF in `sops/` directory

4. **Upload to Knowledge Base**
   - The deployment script automatically uploads all PDFs from `sops/` directory
   - Knowledge Base ingests the PDF content
   - Agent queries the SOP dynamically during execution

### Extending MCP Tools for Custom Workflows

If your business process requires additional SAP operations or integrations:

**1. Identify Required Operations**
   - Review your custom SOP requirements
   - Identify SAP APIs or external systems needed
   - Document input/output requirements

**2. Add Tools to MCP Server**
   - Edit `mcp_server/sap_mcp_server.py`
   - Add new `@mcp.tool()` decorated functions
   - Follow existing patterns for SAP API integration
   - Include proper error handling and logging

**Example: Adding a Custom Tool**

```python
@mcp.tool()
async def create_purchase_requisition(
    material: str,
    quantity: int,
    plant: str,
    delivery_date: str
) -> Dict[str, Any]:
    """Create a purchase requisition in SAP
    
    Args:
        material: Material number
        quantity: Quantity to order
        plant: Plant code
        delivery_date: Required delivery date (ISO format)
    
    Returns:
        Purchase requisition details including PR number
    """
    # Construct API URL
    api_path = "API_PURCHASE_REQUISITION_SRV/A_PurchaseRequisition"
    url = construct_sap_api_url(api_path)
    
    # Prepare request body
    request_body = json.dumps({
        "Material": material,
        "Quantity": str(quantity),
        "Plant": plant,
        "DeliveryDate": delivery_date
    })
    
    # Call SAP API
    response = invoke_sap_odata_service(url, "POST", request_body)
    return json.loads(response)
```

**3. Update Agent Instructions**
   - Edit `strands_agent/strands_sap_agent_claude.py`
   - Add guidance on when to use the new tool
   - Update workflow instructions if needed

**4. Test and Deploy**
   - Test the new tool locally
   - Update your SOP to reference the new capability
   - Redeploy using `python deploy.py`

### SOP Best Practices

**Structure Requirements:**
- Use RFC2119 keywords (MUST, SHOULD, MAY) for clarity
- Include clear exception scenarios with root causes
- Provide step-by-step resolution procedures
- Document all required approvals and escalations
- Specify exact email addresses and contact information

**Content Guidelines:**
- Write for the AI agent, not human operators
- Be explicit about stopping points (MUST STOP and wait)
- Include all data points required in emails
- Document what to store in DynamoDB vs. CloudWatch
- Specify exact SAP API operations to perform

**Maintenance:**
- Review SOPs quarterly or when business processes change
- Version control all SOP documents
- Test agent behavior after SOP updates
- Maintain audit trail of SOP changes

---

## Changing the AI Model

The system uses **Claude 3.7 Sonnet** by default, but you can easily swap to any other Bedrock-supported model.

### Supported Models

Any model available in Amazon Bedrock can be used:
- **Anthropic Claude** (3.7 Sonnet, 3.5 Sonnet, 3 Opus, etc.)
- **Amazon Nova** (Pro, Lite, Micro)
- **Meta Llama** (3.1, 3.2, etc.)
- **Mistral AI** (Large, 7B, etc.)
- **Cohere Command** (R, R+)

### How to Change the Model

**1. Update .env File**

Edit your `.env` file and change the `MODEL_ID` variable:

```bash
# Example: Switch to Claude 3.5 Sonnet
MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0

# Example: Switch to Amazon Nova Pro
MODEL_ID=us.amazon.nova-pro-v1:0

# Example: Switch to Llama 3.1 70B
MODEL_ID=meta.llama3-1-70b-instruct-v1:0
```

**2. Verify Model Access**

Ensure you have access to the model in your AWS region:

```bash
aws bedrock list-foundation-models \
  --region us-east-1 \
  --query "modelSummaries[?modelId=='your-model-id']"
```

**3. Redeploy Strands Agent**

The agent reads the MODEL_ID from environment variables:

```bash
python deploy.py
```

**4. Test the New Model**

Launch the Streamlit dashboard and process a test case to verify the new model works correctly.

### Model Selection Considerations

**Claude 3.7 Sonnet (Default)**
- Best balance of performance and cost
- Excellent reasoning and instruction following
- Strong at complex multi-step workflows
- Good at parsing structured data

**Claude 3 Opus**
- Highest capability for complex reasoning
- Best for critical decision-making
- Higher cost per token

**Amazon Nova Pro**
- Cost-effective alternative
- Good for straightforward workflows
- Lower latency

**Llama 3.1 70B**
- Open-source option
- Good for basic workflows
- Most cost-effective

### Important Notes

- The MCP server and tools remain the same regardless of model
- Different models may require prompt adjustments for optimal performance
- Test thoroughly when switching models
- Monitor costs as pricing varies significantly between models

---

## Additional Resources

- [Main README](README.md) - Project overview and key features
- [SOP Documentation](sops/) - Standard Operating Procedures
- [SAP API Documentation](sap-api-docs/) - SAP OData API specifications

---

## License

See the [LICENSE](LICENSE) file for details.
