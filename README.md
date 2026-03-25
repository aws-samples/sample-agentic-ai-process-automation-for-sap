# SAP Agentic Exception Resolution System

> **Disclaimer:** This code is a reference implementation demonstrating how agentic AI systems can be architected for SAP exception handling. It shows how different components come together to create an intelligent automation solution. Additional considerations needed for security, monitoring, error handling, and compliance requirements before deploying in enterprise environments.

## Project Overview

An intelligent SAP ERP exception handling system that automatically processes blocked invoices and procurement exceptions. The system runs continuously in the background, detecting exceptions through event-based mechanisms or periodic polling. When a user clicks "Process" in the dashboard, the Claude-powered agent retrieves the latest transaction state from DynamoDB and follows Standard Operating Procedures (SOPs) to either resolve automatically or escalate via email. The agent can wait for email responses, perform complex validations (PO/GR/Invoice matching), create goods receipts when needed, and communicate with suppliers and receiving docks throughout the resolution process.

## System Architecture

### Core Components

```
┌─────────────────┐ ┌──────────────────┐ ┌─────────────────┐
│ SAP System      │───▶│ EventBridge      │───▶│ DynamoDB        │
│ (OData API)     │    │ (5min poll)      │    │ (State Store)   │
└─────────────────┘    └──────────────────┘    └─────────┬───────┘
                                                          │
┌─────────────────┐    ┌──────────────────┐              │
│ Streamlit UI    │───▶│ Strands Agent    │◀────────────┼─────────┐
│ (Dashboard)     │    │ (Claude 3.7)     │              │         │
└─────────┬───────┘    └──────────────────┘              │         │
          │                     │                         │         │
          │            ┌────────▼────────┐                │         │
          └─────────────▶│ MCP Server      │                │         │
                       │ (Tools & APIs)   │                │         │
                       └─────────┬───────┘                │         │
                                 │                         │         │
                        ┌────────▼────────┐                │         │
                        │ State Mgmt Tool │────────────────┘         │
                        └─────────────────┘                          │
                                 │                                   │
        ┌──────────────────────────┼──────────────────────┐         │
        │                          │                       │         │
┌───────▼──────┐    ┌──────────────▼──────┐    ┌─────────▼────┐   │
│ Bedrock KB   │    │ SAP OData           │    │ SES          │   │
│ (SOPs + API  │    │ Services            │    │ (Email)      │   │
│  Docs)       │    │                     │    │              │   │
└──────────────┘    └─────────────────────┘    └──────────────┘   │
                                                          │         │
                                                 ┌────────▼────────┐│
                                                 │ Email Lambda    ││
                                                 │ (Reply Handler) ││
                                                 └─────────────────┘│
                                                          │          │
                                                          └──────────┘
```

### Exception Processing Workflow

The system operates through **automated exception detection and resolution**:

#### 1. Exception Detection
- **Event-Based**: Design can be extended for real-time detection when invoices get blocked in SAP based on events.
- **Polling-Based**: EventBridge polls SAP OData APIs every 5 minutes (current implementation)
- **State Creation**: Exceptions automatically stored in DynamoDB with initial status

#### 2. Agent Processing Triggers
- **Dashboard-Triggered**: User clicks "Process" → Agent retrieves latest state → Executes SOP-driven resolution
- **Email-Triggered**: Email responses trigger continued processing with additional context
- **Background Processing**: Can run completely autonomous without Streamlit dashboard

#### 3. Intelligent Resolution Logic
- **PO/GR/Invoice Validation**: Checks quantity matching, delivery status, and payment terms
- **Automated Actions**: Creates goods receipts, releases invoices, updates payment terms
- **Multi-Party Communication**: Emails receiving dock, suppliers, and procurement teams
- **State Persistence**: Continuously updates DynamoDB throughout resolution process

## How It Works

### End-to-End Workflow

**5-step workflow from detection to resolution:**

1. **Detection** (Automated - Every 5 minutes)
   - EventBridge triggers Lambda to poll SAP OData APIs
   - Identifies blocked invoices with payment blocking reasons
   - Creates cases in DynamoDB with status = 'pending'

2. **User Initiation** (Current Demo Approach)
   - User opens Streamlit dashboard and selects a case
   - Clicks "Process" to trigger agent
   - Alternative: Event-driven Lambda automatically triggers agent when new entry created

3. **Data Gathering**
   - Agent retrieves case state from DynamoDB
   - Queries SAP for invoice details, PO data, goods receipt history
   - Assembles complete picture of the exception

4. **SOP-Driven Resolution**
   - Agent queries Bedrock Knowledge Base for relevant SOP
   - Follows documented procedures exactly as written
   - Performs validations (3-way matching, quantity checks, price verification)
   - Takes corrective actions (create GR, update PO, release invoice)
   - Escalates via email when human input required

5. **Confirmation & Closure**
   - Agent updates SAP with resolution
   - Sends confirmation emails to stakeholders
   - Updates DynamoDB status to 'resolved'
   - Documents all actions in processing history

### Decision Logic

The agent uses **SOP-driven decision making** to determine the resolution path:

- Queries Knowledge Base for exception type-specific procedures
- Follows documented escalation paths for each blocking reason
- Applies materiality thresholds for approval requirements
- Routes to appropriate stakeholders based on exception category

## Streamlit Dashboard - Technical Implementation

### Overview

The Streamlit dashboard serves as a **demonstration UI** showcasing the system's capabilities. It's designed to be **swappable**—organizations can replace it with their own UI (React, Angular, internal portals) while keeping the core agent infrastructure intact.

### Key Technical Features

#### 1. HTTP Streaming for Real-Time Agent Logs

The dashboard uses **HTTP streaming** to display agent processing in real-time:

- Users see agent thinking/actions as they happen
- No waiting for complete response before displaying
- Better UX for long-running agent operations (2-5 minutes)

#### 2. Three-Page Architecture

**Cases List Page**:
- Displays all invoice exception cases from DynamoDB
- Shows status, exception type, amounts, suppliers
- Expandable details for full case information
- One-click "Process" button to trigger agent

**Case Logs Page**:
- Detailed processing history timeline for individual cases
- Shows all state transitions with timestamps
- Displays agent actions, decisions, and outcomes
- Searchable by invoice number

**Agent Logs Page** (Three log sources):
- **Live Processing**: Real-time HTTP streaming of current agent execution
- **Strands Agent Logs**: CloudWatch logs from Strands agent runtime with auto-refresh
- **MCP Server Logs**: CloudWatch logs from MCP server runtime

#### 3. CloudWatch Log Integration

Fetches and displays logs from Bedrock AgentCore runtimes with auto-refresh every 10 seconds, time range selector, color-coded log levels, and OpenTelemetry JSON format parsing.

#### 4. Zero Hardcoding - SSM/Secrets Manager Integration

All configuration retrieved dynamically from AWS Systems Manager Parameter Store and Secrets Manager for DynamoDB table names, AgentCore agent ARNs, and Cognito credentials.

#### 5. Cognito JWT Token Management

Automatic token refresh for AgentCore authentication with tokens refreshed automatically before each request and secure authentication with Bedrock AgentCore.

#### 6. Case Status Tracking

Real-time status display with visual indicators:
- 🔵 detected - New case detected
- 🟡 processing - Agent actively processing
- 🟠 awaiting_human_input - Waiting for email response
- 🟢 sap_updated - SAP updated successfully
- ✅ complete - Exception resolved
- 🔴 manual_review_required - Needs human intervention

### Swappable UI Architecture

The Streamlit dashboard is **intentionally decoupled** from the core system. You can swap the entire UI framework, authentication mechanism, and visualization approach while keeping DynamoDB schema, AgentCore APIs, CloudWatch logs, and SSM/Secrets Manager configuration the same.

## Key Advantages

### 1. Massive Time Savings
- **Before**: Hours or days of manual investigation per exception
- **After**: Minutes of agent processing + human approval when needed
- **ROI**: 90%+ time reduction on exception handling

### 2. Improved Accuracy
- Eliminates manual data entry errors
- Validates all actions before execution
- Maintains complete audit trail in DynamoDB
- Ensures compliance with documented SOPs

### 3. Scalability
- Handles hundreds of exceptions without additional headcount
- Processes cases in parallel
- Adapts to business growth automatically

### 4. Intelligent Automation
- Not just rule-based automation—agent makes context-aware decisions
- Parses natural language email responses
- Handles exceptions and edge cases gracefully
- Learns from SOPs stored in Knowledge Base

### 5. Full Transparency
- Every action documented in processing_history
- Stakeholders see complete resolution details
- Audit trail maintained for compliance
- Easy to understand what the agent did and why

### 6. Human Oversight
- Escalation to humans when agent uncertain
- Agent stops and asks for guidance when needed
- Manual review flags for data quality issues
- Users maintain control while eliminating tedious work

## Architecture Overview

### Technology Stack

- **AI/ML**: Amazon Bedrock (Claude 3.7 Sonnet - swappable with other Bedrock models), Bedrock AgentCore, Bedrock Knowledge Base
- **Agent Framework**: Strands (AWS open-source agentic framework)
- **Integration**: Model Context Protocol (MCP) for tool orchestration
- **Compute**: AWS Lambda (serverless functions), Bedrock AgentCore Runtime
- **Storage**: Amazon DynamoDB (case state), Amazon S3 (documents, SOPs)
- **Communication**: Amazon SES (email), Amazon EventBridge (scheduling)
- **SAP Integration**: SAP OData APIs (REST/JSON)
- **UI**: Streamlit (Python web framework with HTTP streaming for real-time agent logs)
- **IaC**: Python deployment script (boto3)

**Note on AgentCore**: Amazon Bedrock AgentCore handles scaling, rate limiting, and runtime management automatically. The agent code runs in a managed container environment with built-in throttling protection and circuit breakers.

## Project Structure

```
sap-exception-handling/
├── README.md                         # This file - Project overview
├── DEPLOYMENT.md                     # Deployment guide
├── deploy.py                         # Deployment script (idempotent)
├── config.py                         # Configuration management
├── requirements.txt                  # Python dependencies
│
├── lambda/                           # AWS Lambda functions
│   ├── odata_poller.py              # Polls SAP OData APIs for exceptions
│   └── s3_email_processor.py        # Processes incoming email responses
│
├── mcp_server/                       # Model Context Protocol server
│   ├── sap_mcp_server.py            # MCP server with SAP tools
│   └── requirements.txt             # MCP server dependencies
│
├── strands_agent/                    # Strands agent implementation
│   ├── strands_sap_agent_claude.py  # Main agent code
│   └── requirements.txt             # Agent dependencies
│
├── streamlit_dashboard/              # Streamlit web dashboard
│   ├── app.py                       # Main dashboard UI
│   ├── streaming_logs.py            # Live processing view
│   ├── agentcore_logs_viewer.py     # CloudWatch logs viewer
│   └── transaction_analytics.py     # Analytics dashboard
│
├── sops/                             # Standard Operating Procedures
│   ├── Supplier_Invoices_Exception_Handling_SOP.md  # SOP for AI agent
│   └── (PDF files removed for compliance - use markdown for Knowledge Base)
│
└── sap-api-docs/                     # SAP API documentation
    ├── API_PURCHASEORDER_PROCESS_SRV_SB2.yaml
    ├── API_SUPPLIERINVOICE_PROCESS_SRV_SB2.yaml
    ├── API_MATERIAL_DOCUMENT_SRV_SB2.yaml
    ├── sales_order_api-openapi_SB2.yaml
    ├── SAP_API_Integration_Guide.md
    └── (PDF files removed for compliance - YAML files are sufficient)
```

## What to Expect

### POC Demonstration

This proof-of-concept demonstrates:

✅ **Autonomous agent processing** - Agent follows SOPs to resolve invoice exceptions  
✅ **Multi-system orchestration** - Seamless integration of SAP, email, DynamoDB, and Knowledge Base  
✅ **Intelligent decision-making** - Agent applies business logic and validation rules  
✅ **Natural language processing** - Agent parses email responses to extract information  
✅ **3-way matching validation** - Accurate PO/GR/Invoice reconciliation  
✅ **Human oversight** - Escalation to humans when agent uncertain  
✅ **Complete audit trail** - Every action documented in DynamoDB  

---

## Enhancing This System Further

This codebase is a reference implementation showing how to architect an agentic AI system for SAP exception handling. It's great for learning and experimentation, but you'll want to add several security and operational improvements before deploying in enterprise environments.

### Protecting Against Malicious Email Content

Since the agent processes emails from external parties like suppliers and receiving docks, you'll want to add safeguards against malicious content. Consider implementing input sanitization that detects and filters out suspicious patterns in email text before it reaches the agent. It's also worth adding validation on the agent's responses to catch any unusual behavior. The system already includes some basic email parsing, but enhanced deployments would benefit from more robust content filtering and validation layers.

### Verifying Email Authenticity

Email spoofing is a real concern when your system acts on email instructions from suppliers or internal stakeholders. Setting up SPF, DKIM, and DMARC validation ensures you're only processing legitimate emails from authorized senders. This involves configuring your DNS records and updating the email processing Lambda to check authentication headers. For critical operations like invoice releases or goods receipt creation, you might want to add callback verification where the system confirms with the sender through a separate channel.

### Hardening System Prompts

AI agents can sometimes be manipulated through carefully crafted prompts. Strengthen your system prompts with explicit constraints about what the agent can and cannot do. Consider adding canary tokens that help detect if someone is trying to extract or manipulate the system prompt. Monitoring the agent's behavior for anomalies and validating responses against expected patterns adds another layer of protection.

### Securing SOP Documents

The SOP documents in S3 guide the agent's behavior, so protecting them is crucial. **For enhanced security, use PDF format for SOPs** - PDFs are harder to tamper with and provide better version control than markdown files. Enable versioning on your S3 buckets and consider requiring MFA for deletions. Set up access logging and CloudWatch alarms to alert you if anyone modifies these documents. You might also want to implement integrity checks using checksums to detect unauthorized changes. The current implementation uses markdown for demonstration purposes, but PDF format is recommended for enterprise deployments.

### Tightening Authentication

Reduce the Cognito access token expiration time from the default to something shorter like 1 hour. The system already implements token refresh, but you'll want to add the ability to revoke tokens if needed. Validate token claims on each request and monitor for suspicious patterns like tokens being reused from different IP addresses. For extra security, you could bind tokens to the originating IP address.

### Applying Least Privilege Access

Create separate IAM roles for different functions - your OData poller only needs read access while the agent needs write permissions. Restrict Secrets Manager access so each component can only access the specific secrets it needs. Use IAM Access Analyzer to continuously monitor and refine permissions. Set up automatic rotation for SAP credentials through Secrets Manager.

### Adding Approval Workflows

For high-value transactions or sensitive operations, implement approval workflows that require human review before execution. Define thresholds based on transaction amounts and action types. Track who requested each action and send notifications to designated approvers. This provides accountability and prevents unauthorized actions.

### Sanitizing Outputs and Logs

Implement output sanitization to automatically redact sensitive information like credit card numbers, passwords, API keys, and personal identifiers from agent responses and logs. Apply this to both what the agent returns and what gets written to CloudWatch Logs. Configure appropriate log retention policies and restrict access to logs using IAM policies.

### Making Audit Logs Immutable

Enable CloudTrail to capture all API calls and configure DynamoDB Streams to track state changes. Send these logs to an S3 bucket with object lock enabled so they can't be tampered with or deleted. Consider using a separate AWS account for audit log storage. Set up CloudWatch Alarms for suspicious patterns and integrate with a SIEM system for comprehensive monitoring.

### Preventing Resource Abuse

AgentCore provides built-in rate limiting and throttling protection, but you may want to add additional circuit breakers that stop calling external services when they're experiencing issues. Monitor for unusual patterns and implement automatic throttling when abuse is detected. This protects both your system and the external services it depends on.

### Validating Tool Responses

Add logging for all MCP tool invocations and their responses. Implement validation to ensure tool responses match expected patterns and business rules. For critical operations, consider adding approval workflows before acting on tool responses.

### Rotating Credentials Regularly

Set up automatic rotation for SAP credentials using Secrets Manager. While the system uses HTTPS/TLS for communication, regular credential rotation limits the window of opportunity if credentials are somehow compromised. Consider implementing certificate pinning for SAP API calls for additional protection.

### Securing Email Processing

Use well-maintained, secure libraries for parsing emails. Validate and sanitize all email content, headers, and attachments before processing. Apply least privilege IAM permissions to the email processing Lambda so it can only access what it needs.

### Compliance Considerations

If you're subject to regulatory requirements, keep these in mind:

For **SOX compliance**, you'll need immutable audit logs, separation of duties, and approval workflows for financial transactions.

For **GDPR compliance**, implement output sanitization, data minimization, access controls, and appropriate data retention policies.

For **PCI-DSS compliance**, ensure credential rotation, encryption in transit, access logging, and secure credential storage.

### Monitoring and Alerting

Set up CloudWatch dashboards to monitor authentication failures, unusual agent behavior, SOP document changes, and high-value transaction requests. Create alarms for suspicious patterns and integrate with your existing monitoring infrastructure. AgentCore provides built-in monitoring for agent invocations, but you'll want to add business-specific metrics.

### Testing Your Enhancements

After implementing security improvements, test them thoroughly. Try simulating prompt injection attacks, sending emails without proper authentication, and attempting to bypass approval workflows. Document what works and what needs refinement.

### Helpful Resources

Check out the AWS Security Best Practices documentation, OWASP LLM Top 10 for AI-specific security guidance, Anthropic's Claude Safety Best Practices, and SAP Security Guides for SAP-specific considerations.

---

**Remember**: This is a reference implementation meant for learning and demonstration. Take the time to implement appropriate security controls and conduct thorough testing before deploying in enterprise environments with real business data.

## Getting Started

Ready to deploy? Follow the comprehensive [Deployment Guide](DEPLOYMENT.md) for:
- Prerequisites and requirements
- Step-by-step deployment instructions
- Configuration details
- Verification steps
- Usage examples
- Troubleshooting tips

---

## License

This code is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file.

---

## Contributing

See [CONTRIBUTING](CONTRIBUTING.md) for more information.


## Notices

Customers are responsible for making their own independent assessment of the information in this Guidance. This Guidance: (a) is for informational purposes only, (b) represents AWS current product offerings and practices, which are subject to change without notice, and (c) does not create any commitments or assurances from AWS and its affiliates, suppliers or licensors. AWS products or services are provided "as is" without warranties, representations, or conditions of any kind, whether express or implied. AWS responsibilities and liabilities to its customers are controlled by AWS agreements, and this Guidance is not part of, nor does it modify, any agreement between AWS and its customers.