import base64
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from threading import Lock
from typing import Any, Dict, List, Literal, Optional, Union

import boto3
import requests
from botocore.exceptions import BotoCoreError, ClientError
from fastmcp import FastMCP
from pydantic import BaseModel, Field
from requests.exceptions import RequestException
from starlette.responses import JSONResponse

# SAP Invoice State Type Definitions
# Type aliases for common field types
Status = Literal[
    "pending",
    "processing",
    "resolved",
    "failed",
    "requires_review",
    "awaiting_human_input",
    "requires_manual_intervention",
]
MessageType = Literal["INVOICE_EXCEPTION"]
TransactionType = Literal["INVOICE"]
Action = Literal[
    "create", "update", "resolve", "retry", "escalate", "email_sent", "email_received"
]
Result = Literal[
    "pending", "success", "failed", "requires_review", "escalated", "awaiting_response"
]


@dataclass
class ProcessingHistoryEntry:
    """
    Represents a single entry in the processing history of an invoice exception.

    The details dictionary should include structured information about the processing step:
    - For SOP-related actions: Include 'sop_id', 'sop_name', and 'sop_reason' fields
    - For SAP API actions: Include 'api_endpoint', 'method', 'request_data', and 'response_summary' fields
    - For status changes: Include 'previous_status', 'new_status', and 'reason' fields
    - For escalations: Include 'recipient', 'reason', and 'message_summary' fields

    This structured logging ensures compliance requirements are met and provides
    a clear audit trail of all actions taken during exception processing.
    """

    processor: str
    action: Action
    timestamp: str
    result: Result
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EscalationHistoryEntry:
    """
    Represents a single entry in the escalation history for email-based workflows.
    """

    timestamp: str
    email_content: str
    attempt_number: int
    recipient: str
    sender: str
    message_id: str = ""
    email_type: str = "outbound"  # "outbound" or "inbound"


@dataclass
class Metrics:
    """
    Processing metrics for tracking performance and retry behavior.
    """

    processing_time: str = "0"
    retry_count: str = "0"


@dataclass
class InvoiceExceptionState:
    """
    Complete state record for an invoice exception in the DynamoDB table.

    This represents the full schema used to track invoice exceptions from
    initial detection through resolution.

    Primary Key: transaction_number (derived from OriginalReferenceDocument, first characters only)
    Additional Key Field: document_date (indexed via GSI)

    Field Mappings from SAP OData:
    - transaction_number: OriginalReferenceDocument (first characters, excluding last 4 year digits)
    - document_date: DocumentDate
    - external_reference: DocumentReferenceID
    - supplier_number: Supplier
    - amount: AmountInTransactionCurrency
    - currency: TransactionCurrency
    - exception_type: PaymentBlockingReason
    - transaction_type: ReferenceDocumentTypeName
    """

    # Primary key field
    transaction_number: (
        str  # Derived from SAP OriginalReferenceDocument (first characters only)
    )

    # Additional key field (indexed)
    document_date: str  # SAP DocumentDate

    # Core state fields
    status: Status
    status_summary: str
    message_type: MessageType
    exception_type: str  # SAP PaymentBlockingReason values
    transaction_type: (
        str  # SAP ReferenceDocumentTypeName (not limited to TransactionType enum)
    )

    # Business data fields
    supplier_number: str  # SAP Supplier
    amount: Union[str, float]  # SAP AmountInTransactionCurrency
    currency: str  # SAP TransactionCurrency
    external_reference: str  # SAP DocumentReferenceID

    # Timestamp fields
    created_on: str
    timestamp: str
    last_modified_at: str

    # State management fields
    state_version: int
    processing_history: List[ProcessingHistoryEntry]
    auto_resolved: bool
    is_active: bool
    requires_human_review: bool

    # Performance and lifecycle fields
    metrics: Metrics
    ttl: int  # Unix timestamp for DynamoDB TTL

    # Escalation and email workflow fields
    escalation_history: List[EscalationHistoryEntry] = field(default_factory=list)
    escalation_attempts: int = 0
    max_escalation_rounds: int = 3


# Configure logging with improved formatting
class CustomFormatter(logging.Formatter):
    """Custom formatter that handles JSON data more elegantly"""

    def __init__(self, fmt=None, datefmt=None, style="%"):
        super().__init__(fmt, datefmt, style)
        self.max_json_length = 500  # Maximum length for JSON content in logs

    def _format_json(self, obj):
        """Format JSON objects for logging with truncation"""
        if not obj:
            return "{}"

        try:
            if isinstance(obj, str):
                # Try to parse string as JSON
                obj = json.loads(obj)

            # Convert to formatted string with indentation
            formatted = json.dumps(obj, indent=2)

            # Truncate if too long
            if len(formatted) > self.max_json_length:
                lines = formatted.split("\n")
                if len(lines) > 5:
                    # Keep first 3 and last 2 lines
                    truncated = (
                        "\n".join(lines[:3])
                        + f"\n... [truncated {len(lines)-5} lines] ...\n"
                        + "\n".join(lines[-2:])
                    )
                    return truncated
                else:
                    # Just truncate with ellipsis
                    return formatted[: self.max_json_length] + "... [truncated]"
            return formatted
        except (TypeError, json.JSONDecodeError):
            return str(obj)

    def format(self, record):
        """Override format to handle JSON data in log messages"""
        # Process the record message if it might contain JSON
        if record.args and len(record.args) > 0:
            new_args = []
            for arg in record.args:
                if isinstance(arg, (dict, list)) or (
                    isinstance(arg, str) and arg.startswith("{")
                ):
                    new_args.append(self._format_json(arg))
                else:
                    new_args.append(arg)
            record.args = tuple(new_args)

        return super().format(record)


# Set up logger with custom formatter
logger = logging.getLogger(__name__)
handler = logging.StreamHandler()
formatter = CustomFormatter(
    fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
handler.setFormatter(formatter)
logger.handlers = [handler]
logger.setLevel(logging.INFO)

mcp = FastMCP(host="0.0.0.0", stateless_http=True)

# Initialize AWS clients
dynamodb = boto3.resource("dynamodb")
sqs = boto3.client("sqs")
ses = boto3.client("ses")

# Environment configuration
ENVIRONMENT = "dev"
DYNAMODB_TABLE_NAME = f"invoice-state-{ENVIRONMENT}"
STATE_TTL_DAYS = int(os.getenv("STATE_TTL_DAYS", "90"))

# Knowledge Base IDs
SAP_SOP_KNOWLEDGE_BASE = "6PIWQDUXT3"
SAP_API_KNOWLEDGE_BASE = "15DQJOV6E3"

# Email configuration
from config import config

SENDER_EMAIL = config.AGENT_EMAIL
SAP_BASE_URL = config.SAP_BASE_URL

# SAP OData API configuration - Retrieved from Secrets Manager
import os
from dotenv import load_dotenv
load_dotenv()

def get_sap_credentials():
    """Retrieve SAP credentials from AWS Secrets Manager"""
    try:
        region = config.AWS_REGION
        secret_name = os.getenv('SECRETS_SAP_NAME', 'sap_credentials')
        secrets_client = boto3.client('secretsmanager', region_name=region)
        response = secrets_client.get_secret_value(SecretId=secret_name)
        credentials = json.loads(response['SecretString'])
        return credentials['username'], credentials['password']
    except Exception as e:
        logger.error(f"Failed to retrieve SAP credentials from Secrets Manager: {e}")
        raise Exception("SAP credentials must be available in Secrets Manager")

# Get credentials at module level
SAP_USERNAME, SAP_PASSWORD = get_sap_credentials()

# Bedrock AgentCore configuration
BEDROCK_AGENTCORE_ENDPOINT = f"https://bedrock-agentcore.{config.AWS_REGION}.amazonaws.com"


# Utility function for consistent UTC timestamp generation
def utc_now() -> str:
    """Generate UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


# Helper functions for working with typed state objects
def create_processing_history_entry(
    processor: str,
    action: Action,
    result: Result = "success",
    details: Dict[str, Any] = None,
    sop_info: Dict[str, str] = None,
    sap_action_info: Dict[str, Any] = None,
) -> ProcessingHistoryEntry:
    """Create a properly structured processing history entry with enhanced logging

    Args:
        processor: Name of the processor making the entry (e.g., 'StrandsAgent', 'StateManager')
        action: Type of action being performed (e.g., 'update', 'resolve', 'escalate')
        result: Result of the action (e.g., 'success', 'failed', 'requires_review')
        details: General details about the action (optional)
        sop_info: Information about SOP used for decision making (optional)
            - sop_id: Identifier of the SOP
            - sop_name: Name of the SOP
            - sop_reason: Reason this SOP was selected
        sap_action_info: Information about SAP API actions taken (optional)
            - api_endpoint: The SAP API endpoint called
            - method: HTTP method used (GET, POST, etc.)
            - action_type: Type of action (e.g., 'block_removal', 'payment_approval')
            - entity_affected: Entity affected by the action

    Returns:
        A properly structured ProcessingHistoryEntry object
    """
    # Initialize details dictionary if not provided
    entry_details = details or {}

    # Add SOP information if provided
    if sop_info:
        entry_details["sop_info"] = sop_info

    # Add SAP action information if provided
    if sap_action_info:
        entry_details["sap_action_info"] = sap_action_info

    return ProcessingHistoryEntry(
        processor=processor,
        action=action,
        timestamp=utc_now(),
        result=result,
        details=entry_details,
    )


def create_escalation_history_entry(
    email_content: str,
    recipient: str,
    sender: str,
    attempt_number: int,
    message_id: str = "",
    email_type: str = "outbound",
) -> EscalationHistoryEntry:
    """Create a properly structured escalation history entry"""
    return EscalationHistoryEntry(
        timestamp=utc_now(),
        email_content=email_content,
        attempt_number=attempt_number,
        recipient=recipient,
        sender=sender,
        message_id=message_id,
        email_type=email_type,
    )


def dataclass_to_dict(obj) -> Dict[str, Any]:
    """Convert a dataclass instance to a dictionary for DynamoDB storage"""
    if hasattr(obj, "__dataclass_fields__"):
        result = {}
        for field_name, field_value in obj.__dict__.items():
            if isinstance(field_value, list):
                result[field_name] = [
                    (
                        dataclass_to_dict(item)
                        if hasattr(item, "__dataclass_fields__")
                        else item
                    )
                    for item in field_value
                ]
            elif hasattr(field_value, "__dataclass_fields__"):
                result[field_name] = dataclass_to_dict(field_value)
            else:
                result[field_name] = field_value
        return result
    return obj


@mcp.tool()
def search_sap_api_knowledge_base(query: str) -> str:
    """Use this KnowledgeBase contains:
    1. SAP documentation - Organized by Service Entities, descriptions, key fields, properties (fields) and property descriptions.
    Each Service entity forms an OData API that can be called independently by modifying the request URL (Service structure). Use this to understand user's query
    and identify corresponding API by matching business descriptions.
    2. OpenAPI schema definition of SAP APIs - This provides precise technical information including end point (SAP server),
    path (Service entity), parameters, etc.
    Use this knowledgebase to precisely identify OData API URLs including SAP server host name, service entity and parameters. Depending on user
    request, you may have to multiple SAP OData API calls.

    Here is examples of a valid SAP API calls:
    https://your-sap-system.com/sap/opu/odata/sap/API_SALES_ORDER_SRV/A_SalesOrder('127')
    https://your-sap-system.com/sap/opu/odata/sap/API_SALES_ORDER_SRV/A_SalesOrder('127')/to_Item

    Ensure each API call has valid host name.

    Do not make up any URLs, always test accuracy by referring to openAPI schema.
    """
    try:
        bedrock_agent = boto3.client("bedrock-agent-runtime", region_name=config.AWS_REGION)
        response = bedrock_agent.retrieve(
            knowledgeBaseId=SAP_API_KNOWLEDGE_BASE, retrievalQuery={"text": query}
        )

        results = []
        for result in response.get("retrievalResults", []):
            content = result.get("content", {}).get("text", "")
            if content:
                results.append(content)

        return (
            "\n\n".join(results)
            if results
            else "No relevant information found in knowledge base."
        )

    except (BotoCoreError, ClientError) as e:
        error_msg = f"AWS client error while searching knowledge base: {str(e)}"
        logger.error(error_msg)
        return error_msg
    except Exception as e:
        error_msg = f"Unexpected error while searching knowledge base: {str(e)}"
        logger.error(error_msg)
        return error_msg


@mcp.tool()
def search_sap_sops(query: str) -> str:
    """This KnowledgeBase contains SAP Systems Operating Plans (SOPs). Each SOP documents a business process, sub process
    and process flow. It lists all the possible process exceptions, ways to identify it and resolution steps.
    Use this knowledge base to analyze the data, identify the exception accurately and come up with precise steps to
    resolve the exception. These resolution steps need to be executed in SAP as OData API calls to systematically take
    an action. If you can't find exact exception, do not make things up.
    """
    try:
        bedrock_agent = boto3.client("bedrock-agent-runtime", region_name=config.AWS_REGION)
        response = bedrock_agent.retrieve(
            knowledgeBaseId=SAP_SOP_KNOWLEDGE_BASE, retrievalQuery={"text": query}
        )

        # Extract relevant information from results
        results = []
        for result in response.get("retrievalResults", []):
            content = result.get("content", {}).get("text", "")
            if content:
                results.append(content)

        return (
            "\n\n".join(results)
            if results
            else "No relevant information found in knowledge base."
        )
    except Exception as e:
        return f"Error searching knowledge base: {str(e)}"


@mcp.tool()
def construct_sap_api_url(api_path: str) -> str:
    """Construct a complete SAP OData API URL from a relative path.
    
    This tool combines the SAP base URL from configuration with the API path to create
    a complete URL that can be used with invoke_sap_odata_service.
    
    Args:
        api_path: The relative API path starting with /sap/opu/odata/sap/
                 Example: "/sap/opu/odata/sap/API_SUPPLIERINVOICE_PROCESS_SRV/A_SupplierInvoice('1900000002')"
                 Or just the service and entity: "API_MATERIAL_DOCUMENT_SRV/A_MaterialDocumentHeader"
    
    Returns:
        Complete SAP OData API URL
        Example: "https://your-server.com/sap/opu/odata/sap/API_SUPPLIERINVOICE_PROCESS_SRV/A_SupplierInvoice('1900000002')"
    """
    # Ensure api_path starts with /sap/opu/odata/sap/ or add it if missing
    if not api_path.startswith("/sap/opu/odata/sap/"):
        if api_path.startswith("/"):
            api_path = api_path.lstrip("/")
        api_path = f"/sap/opu/odata/sap/{api_path}"
    
    # Combine base URL with API path
    complete_url = f"{SAP_BASE_URL}{api_path}"
    
    logger.info(f"Constructed SAP API URL: {complete_url}")
    return complete_url


@mcp.tool()
def invoke_sap_odata_service(
    odata_api_url: str, http_method: str = "GET", request_body: str = ""
) -> str:
    """This tool calls the SAP OData API URL with specified HTTP method and optional request body

    Args:
        odata_api_url: The complete SAP OData API URL
        http_method: HTTP method (GET, POST, PUT, PATCH, DELETE)
        request_body: JSON string for POST/PUT/PATCH requests
    """
    # Log the incoming OData call request with a single, comprehensive message
    logger.info(
        f"SAP API: {http_method} {odata_api_url} - Body size: {len(request_body) if request_body else 0} bytes"
    )

    try:
        # Validate HTTP method
        supported_methods = ["GET", "POST", "PUT", "PATCH", "DELETE"]
        http_method = http_method.upper()
        if http_method not in supported_methods:
            return f"Unsupported HTTP method. Supported: {supported_methods}"

        # Validate request body for write operations
        if http_method in ["POST", "PUT", "PATCH"] and not request_body:
            return f"{http_method} requests require a request body"

        # Validate URL
        if not odata_api_url.startswith("https://"):
            return "Invalid URL: Must use HTTPS"

        # Set up authentication using configuration variables
        auth_string = f"{SAP_USERNAME}:{SAP_PASSWORD}"
        auth_bytes = auth_string.encode("ascii")
        auth_b64 = base64.b64encode(auth_bytes).decode("ascii")

        # Get session with valid CSRF token
        try:
            session_manager = SAPSessionManager.get_instance()
            session, csrf_token, cookies = session_manager.get_session_with_token(
                odata_api_url, auth_b64
            )
            logger.info(f"SAP API: Session established with CSRF token for {odata_api_url}")
        except Exception as e:
            logger.error(f"SAP API: Failed to get CSRF token - {str(e)}")
            return f"Failed to get session with CSRF token: {str(e)}"

        # Set up request headers
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-csrf-token": csrf_token,
            "Authorization": f"Basic {auth_b64}",
        }

        # Add cookies if available
        if cookies:
            cookie_string = "; ".join(
                [f"{name}={value}" for name, value in cookies.items()]
            )
            headers["Cookie"] = cookie_string

        # Log the actual request being made (debug level for headers)
        logger.debug(f"SAP API: Headers for {http_method} {odata_api_url} - {headers}")

        # Make request using session
        response = session.request(
            method=http_method,
            url=odata_api_url,
            headers=headers,
            data=request_body if request_body else None,
            timeout=30,
            verify=True,
        )

        # Log response status
        logger.info(f"SAP API: Response {response.status_code} from {http_method} {odata_api_url}")

        # Handle error responses
        if response.status_code >= 400:
            logger.error(f"SAP API: Error {response.status_code} - {response.text[:200]}")
            return f"HTTP {response.status_code}: {response.text}"

        # Parse and validate response
        if response.content:
            try:
                data = response.json()
                # Log success with content length and optionally log keys at debug level
                content_length = len(response.content) if response.content else 0
                logger.info(f"SAP API: Success - {content_length} bytes of JSON data received")
                if isinstance(data, dict) and logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"SAP API: Response contains keys: {list(data.keys())}")
                return json.dumps(data, indent=2)
            except json.JSONDecodeError as e:
                logger.error(f"SAP API: JSON parsing failed - {str(e)}")
                return (
                    f"Invalid JSON response: {str(e)}\nResponse text: {response.text}"
                )
        else:
            logger.info(f"SAP API: Success - Empty response with status {response.status_code}")
            return f"Request successful. Status: {response.status_code}"

    except (
        requests.exceptions.SSLError,
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.RequestException,
        json.JSONDecodeError,
        Exception,
    ) as e:

        if isinstance(e, requests.exceptions.SSLError):
            error_msg = f"SSL/TLS error: {str(e)}"
        elif isinstance(e, requests.exceptions.ConnectionError):
            error_msg = f"Connection error: {str(e)}"
        elif isinstance(e, requests.exceptions.Timeout):
            error_msg = f"Request timed out: {str(e)}"
        elif isinstance(e, requests.exceptions.RequestException):
            error_msg = f"Network error: {str(e)}"
            if hasattr(e, "response") and e.response is not None:
                error_msg += f"\nResponse status: {e.response.status_code}"
                error_msg += f"\nResponse text: {e.response.text}"
        elif isinstance(e, json.JSONDecodeError):
            error_msg = f"JSON parsing error: {str(e)}"
        else:
            error_msg = f"Unexpected error: {str(e)}"

        logger.error(error_msg)
        return error_msg


# DynamoDB State Management Tools
# Note: State creation is handled automatically by EventBridge and Lambda
# These tools focus on operations using primary/secondary keys (transaction_number, transaction_item_number)


@mcp.tool()
async def update_state(
    transaction_number: str,
    updates: Dict[str, Any],
    action: Action = "update",
) -> Dict[str, Any]:
    """Update an existing state entry with version control and history tracking

    Args:
        transaction_number: Transaction number of state to update (now the primary key)
        updates: Fields to update
        action: Action being performed (for history tracking)

    Returns:
        Updated state entry
    """
    # Validate status updates if present
    if "status" in updates:
        valid_statuses = [
            "pending",
            "processing",
            "resolved",
            "failed",
            "requires_review",
            "awaiting_human_input",
            "requires_manual_intervention",
        ]
        if updates["status"] not in valid_statuses:
            raise ValueError(
                f"Invalid status: {updates['status']}. Must be one of: {valid_statuses}"
            )
    table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    timestamp = utc_now()

    # Get current state for version check (self-contained DynamoDB access)
    response = table.get_item(
        Key={
            "transaction_number": transaction_number,
        },
        ConsistentRead=True,
    )
    current_state = response.get("Item")

    if not current_state:
        raise ValueError(f"No state found for transaction {transaction_number}")

    # Prepare update expression parts
    update_parts = []
    expression_values = {":ts": timestamp}
    expression_names = {}

    # Handle each update field
    for key, value in updates.items():
        update_parts.append(f"#{key} = :{key}")
        expression_names[f"#{key}"] = key
        expression_values[f":{key}"] = value

    # Create typed history entry using helper function
    history_entry_obj = create_processing_history_entry(
        processor="StateManager",
        action=action,
        result="success",
        details={"updates": updates},
    )
    # Convert to dict for DynamoDB storage
    history_entry = dataclass_to_dict(history_entry_obj)

    # Initialize escalation fields if they don't exist
    if "escalation_history" not in current_state:
        update_parts.append("escalation_history = :empty_list")
        expression_values[":empty_list"] = []

    if "escalation_attempts" not in current_state:
        update_parts.append("escalation_attempts = :zero")
        expression_values[":zero"] = 0

    if "max_escalation_rounds" not in current_state:
        update_parts.append("max_escalation_rounds = :max_rounds")
        expression_values[":max_rounds"] = 3

    # Add version and history updates
    update_parts.extend(
        [
            "state_version = :newVersion",
            "last_modified_at = :ts",
            "processing_history = list_append(processing_history, :history)",
        ]
    )
    expression_values.update(
        {
            ":newVersion": current_state["state_version"] + 1,
            ":history": [history_entry],
            ":oldVersion": current_state["state_version"],
        }
    )

    update_expression = "SET " + ", ".join(update_parts)

    try:
        response = table.update_item(
            Key={
                "transaction_number": transaction_number,
            },
            UpdateExpression=update_expression,
            ExpressionAttributeNames=expression_names,
            ExpressionAttributeValues=expression_values,
            ConditionExpression="state_version = :oldVersion",
            ReturnValues="ALL_NEW",
        )
        return response["Attributes"]
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        raise ValueError(
            f"Concurrent update detected for transaction {transaction_number}"
        )


@mcp.tool()
async def get_state(transaction_number: str) -> Dict[str, Any]:
    """Get a state entry by transaction number with consistent read

    Args:
        transaction_number: Transaction number of state to retrieve (now the primary key)

    Returns:
        State entry if found
    """
    table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    response = table.get_item(
        Key={
            "transaction_number": transaction_number,
        },
        ConsistentRead=True,
    )
    return response.get("Item")


@mcp.tool()
async def get_state_history(transaction_number: str) -> List[Dict[str, Any]]:
    """Get the processing history for a state entry

    Args:
        transaction_number: Transaction number of state to retrieve history for (now the primary key)

    Returns:
        List of processing history entries
    """
    # Self-contained DynamoDB access
    table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    response = table.get_item(
        Key={
            "transaction_number": transaction_number,
        },
        ConsistentRead=True,
    )
    state = response.get("Item")

    if not state:
        return []
    return state.get("processing_history", [])


@mcp.tool()
async def query_states_by_status(
    status: Status, limit: int = 100
) -> List[Dict[str, Any]]:
    """Query states by status using GSI

    Args:
        status: Status to query for (must be one of the valid Status values)
        limit: Maximum number of items to return

    Returns:
        List of state entries matching the status, sorted by timestamp
    """
    table = dynamodb.Table(DYNAMODB_TABLE_NAME)

    try:
        response = table.query(
            IndexName="status-index",
            KeyConditionExpression="#status = :status",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":status": status},
            Limit=limit,
            ScanIndexForward=False,  # Return most recent first
        )
        return response.get("Items", [])
    except Exception as e:
        logger.error(f"Error querying states by status: {str(e)}")
        raise


@mcp.tool()
async def get_state_metrics(transaction_number: str) -> Dict[str, Any]:
    """Get metrics for a state entry

    Args:
        transaction_number: Transaction number of state to retrieve metrics for (now the primary key)

    Returns:
        State metrics if found
    """
    # Self-contained DynamoDB access
    table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    response = table.get_item(
        Key={
            "transaction_number": transaction_number,
        },
        ConsistentRead=True,
    )
    state = response.get("Item")

    if not state:
        return {}
    return state.get("metrics", {})


@mcp.tool()
async def add_escalation_entry(
    transaction_number: str,
    email_content: str,
    recipient: str,
    sender: str,
    message_id: str = "",
    email_type: str = "outbound",
) -> Dict[str, Any]:
    """Add an escalation history entry and update escalation attempt count

    Args:
        transaction_number: Transaction number of state to update (now the primary key)
        email_content: Content of the email
        recipient: Email recipient
        sender: Email sender
        message_id: SES message ID (optional)
        email_type: "outbound" or "inbound"

    Returns:
        Updated state entry
    """
    # Log concise operation info
    logger.info(f"Adding {email_type} escalation entry for transaction {transaction_number} to {recipient}")
    
    table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    timestamp = utc_now()

    # Get current state (self-contained DynamoDB access)
    response = table.get_item(
        Key={
            "transaction_number": transaction_number,
        },
        ConsistentRead=True,
    )
    current_state = response.get("Item")

    if not current_state:
        raise ValueError(f"No state found for transaction {transaction_number}")

    # Get current escalation attempts and history - ensure proper type conversion
    current_attempts = int(current_state.get("escalation_attempts", 0))
    escalation_history = current_state.get("escalation_history", [])

    # Create typed escalation entry using helper function
    escalation_entry_obj = create_escalation_history_entry(
        email_content=email_content,
        recipient=recipient,
        sender=sender,
        attempt_number=(
            current_attempts + 1 if email_type == "outbound" else current_attempts
        ),
        message_id=message_id,
        email_type=email_type,
    )
    # Convert to dict for DynamoDB storage
    escalation_entry = dataclass_to_dict(escalation_entry_obj)

    # Prepare update expression
    update_parts = []
    expression_values = {":ts": timestamp}
    expression_names = {}

    # Add escalation entry to history
    update_parts.append(
        "escalation_history = list_append(if_not_exists(escalation_history, :empty_list), :escalation_entry)"
    )
    expression_values[":empty_list"] = []
    expression_values[":escalation_entry"] = [escalation_entry]

    # Update attempt count for outbound emails
    if email_type == "outbound":
        update_parts.append("escalation_attempts = :new_attempts")
        expression_values[":new_attempts"] = current_attempts + 1

    # Create typed processing history entry using helper function
    history_entry_obj = create_processing_history_entry(
        processor="EscalationManager",
        action="email_sent" if email_type == "outbound" else "email_received",
        result="success",
        details={
            "email_type": email_type,
            "recipient": recipient,
            "sender": sender,
            "message_id": message_id,
        },
    )
    # Convert to dict for DynamoDB storage
    history_entry = dataclass_to_dict(history_entry_obj)

    # Add version and history updates
    update_parts.extend(
        [
            "state_version = :newVersion",
            "last_modified_at = :ts",
            "processing_history = list_append(processing_history, :history)",
        ]
    )
    expression_values.update(
        {
            ":newVersion": current_state["state_version"] + 1,
            ":history": [history_entry],
            ":oldVersion": current_state["state_version"],
        }
    )

    update_expression = "SET " + ", ".join(update_parts)

    try:
        # Only include ExpressionAttributeNames if we have any
        update_params = {
            "Key": {
                "transaction_number": transaction_number,
            },
            "UpdateExpression": update_expression,
            "ExpressionAttributeValues": expression_values,
            "ConditionExpression": "state_version = :oldVersion",
            "ReturnValues": "ALL_NEW",
        }

        # Only add ExpressionAttributeNames if we have any
        if expression_names:
            update_params["ExpressionAttributeNames"] = expression_names

        response = table.update_item(**update_params)
        return response["Attributes"]
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        raise ValueError(
            f"Concurrent update detected for transaction {transaction_number}"
        )


@mcp.tool()
async def check_escalation_limit(transaction_number: str) -> Dict[str, Any]:
    """Check if escalation limit has been reached for a transaction

    Args:
        transaction_number: Transaction number to check (now the primary key)

    Returns:
        Dictionary with escalation status information
    """
    # Self-contained DynamoDB access
    table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    response = table.get_item(
        Key={
            "transaction_number": transaction_number,
        },
        ConsistentRead=True,
    )
    state = response.get("Item")

    if not state:
        return {"error": "State not found"}

    # Ensure proper type conversion for comparison - DynamoDB may return Decimal or string types
    escalation_attempts = int(state.get("escalation_attempts", 0))
    max_escalation_rounds = int(state.get("max_escalation_rounds", 3))
    escalation_history = state.get("escalation_history", [])

    return {
        "escalation_attempts": escalation_attempts,
        "max_escalation_rounds": max_escalation_rounds,
        "limit_reached": escalation_attempts >= max_escalation_rounds,
        "remaining_attempts": max(0, max_escalation_rounds - escalation_attempts),
        "escalation_history_count": len(escalation_history),
    }


# 3. Email Notification Tools
@mcp.tool()
def send_escalation_email(
    recipient: str,
    transaction_number: str,
    transaction_item_number: str,
    external_reference: str,
    escalation_message: str,
    sender: str = "",
) -> Dict[str, Any]:
    """Send an escalation email with standardized format that includes transaction identifiers
    in both subject and body for reliable extraction by the email processing lambda.

    The recipient parameter can contain multiple email addresses separated by commas,
    which will all be included in a single email (first recipient in To, others in CC).

    Args:
        recipient: Email address(es) of the recipient(s), comma-separated for multiple recipients
        transaction_number: Transaction number for the invoice exception
        transaction_item_number: Transaction item number for the invoice exception
        external_reference: External reference (e.g., invoice number, PO number)
        escalation_message: The main escalation message content
        sender: Sender email address (defaults to SENDER_EMAIL if empty)

    Returns:
        SES send email response with message ID and status
    """
    # Set default sender if not provided or empty
    if not sender:
        sender = SENDER_EMAIL

    # Create standardized subject line with transaction identifiers
    subject = f"SAP Invoice Exception - Transaction: {transaction_number}, Item: {transaction_item_number}"

    # Create standardized body with transaction identifiers at the top
    body = f"""Transaction Number: {transaction_number}
Transaction Item Number: {transaction_item_number}
Reference: {external_reference}

{escalation_message}

Please respond to this email with your input to continue processing.

---
This is an automated message from the SAP Agentic Exception Resolution System.
"""

    try:
        # Log a single, comprehensive message instead of multiple separate ones
        recipients = [r.strip() for r in recipient.split(",") if r.strip()]
        logger.info(
            f"Preparing escalation email: Transaction={transaction_number}/{transaction_item_number}, "
            f"From={sender}, To={recipient}, Recipients={len(recipients)}"
        )
        
        # Create the email message
        msg = MIMEMultipart()
        msg["From"] = sender
        
        # Email headers require proper formatting - put all recipients in To field
        if recipients:
            msg["To"] = ", ".join(recipients)  # All recipients in To field
            # Also log the exact recipient list for debugging
            logger.info(f"Email recipients parsed: {recipients}")
            logger.info(f"Email To header: {msg['To']}")
        
        msg["Subject"] = subject
        
        # Attach the body as plain text
        msg.attach(MIMEText(body, "plain"))

        # Send email using SES send_raw_email - ensure all recipients get the email
        logger.info(f"SES Destinations list: {recipients}")
        response = ses.send_raw_email(
            Source=sender,
            Destinations=recipients,  # This ensures SES delivers to all recipients
            RawMessage={"Data": msg.as_string()},
        )

        logger.info(f"Email sent: Transaction={transaction_number}, MessageID={response.get('MessageId')}")

        # Return structured response with recipient confirmation
        return {
            "success": True,
            "message_id": response.get("MessageId"),
            "sender": sender,
            "recipient": recipient,
            "recipients_list": recipients,
            "total_recipients": len(recipients),
            "subject": subject,
            "transaction_number": transaction_number,
            "transaction_item_number": transaction_item_number,
            "external_reference": external_reference,
            "timestamp": utc_now(),
            "confirmation": f"Email successfully sent to {len(recipients)} recipient(s): {', '.join(recipients)}",
            "ses_response": response,
        }

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_message = e.response["Error"]["Message"]
        error_msg = f"SES ClientError ({error_code}): {error_message}"
        logger.error(f"Email send failed: Transaction={transaction_number}, Error={error_code}")

        return {
            "success": False,
            "error": error_msg,
            "error_code": error_code,
            "sender": sender,
            "recipient": recipient,
            "transaction_number": transaction_number,
            "transaction_item_number": transaction_item_number,
            "timestamp": utc_now(),
        }

    except Exception as e:
        error_msg = f"Unexpected error sending escalation email: {str(e)}"
        logger.error(f"Email send failed: Transaction={transaction_number}, Error={type(e).__name__}")

        return {
            "success": False,
            "error": error_msg,
            "error_type": type(e).__name__,
            "sender": sender,
            "recipient": recipient,
            "transaction_number": transaction_number,
            "transaction_item_number": transaction_item_number,
            "timestamp": utc_now(),
        }


@mcp.tool()
def verify_email_recipients(recipient_string: str) -> Dict[str, Any]:
    """Verify and parse email recipients to confirm all intended recipients are included.
    
    This tool helps the agent confirm that all recipients from SOPs are properly included
    in the email before sending.
    
    Args:
        recipient_string: Comma-separated email addresses to verify
        
    Returns:
        Dictionary with parsed recipients and confirmation details
    """
    try:
        # Parse recipients
        recipients = [r.strip() for r in recipient_string.split(",") if r.strip()]
        
        # Validate email format
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        valid_recipients = []
        invalid_recipients = []
        
        for email in recipients:
            if re.match(email_pattern, email):
                valid_recipients.append(email)
            else:
                invalid_recipients.append(email)
        
        return {
            "total_recipients": len(recipients),
            "valid_recipients": valid_recipients,
            "invalid_recipients": invalid_recipients,
            "recipient_list": recipients,
            "formatted_string": ", ".join(valid_recipients),
            "confirmation": f"Verified {len(valid_recipients)} valid recipient(s): {', '.join(valid_recipients)}",
            "ready_to_send": len(invalid_recipients) == 0 and len(valid_recipients) > 0
        }
        
    except Exception as e:
        return {
            "error": f"Error verifying recipients: {str(e)}",
            "ready_to_send": False
        }


class SAPDocument(BaseModel):
    """Model for representing SAP document data structures.

    This class provides a standardized structure for SAP documents,
    containing document identification, type classification, and
    flexible data storage for various SAP document formats.
    """

    document_id: str
    document_type: str
    data: Dict[str, Any]


class SAPSessionManager:
    """Singleton session manager for SAP OData API calls with CSRF token handling.

    This class manages HTTP sessions and CSRF tokens for SAP OData API calls,
    implementing a singleton pattern to ensure consistent session state across
    multiple API calls. It handles token expiration and automatic refresh.
    """

    _instance = None
    _lock = Lock()

    def __init__(self):
        self.session = None
        self.csrf_token = None
        self.cookies = None
        self.last_token_fetch = None
        self.token_expiry = timedelta(hours=1)  # 1 hour default
        self.logger = logging.getLogger(__name__)

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def initialize_session(self):
        """Initialize or reinitialize the session"""
        if self.session is None:
            self.session = requests.Session()
            self.csrf_token = None
            self.cookies = None
            self.last_token_fetch = None

    def is_token_valid(self) -> bool:
        """Check if the current token is still valid"""
        if not all([self.csrf_token, self.last_token_fetch]):
            return False

        if datetime.now(timezone.utc) - self.last_token_fetch > self.token_expiry:
            return False

        return True

    def get_session_with_token(self, api_endpoint: str, auth_b64: str) -> tuple:
        """Get or refresh session with valid CSRF token"""
        self.initialize_session()

        if not self.is_token_valid():
            self.refresh_token(api_endpoint, auth_b64)

        return self.session, self.csrf_token, self.cookies

    def refresh_token(self, api_endpoint: str, auth_b64: str):
        """Force refresh of CSRF token"""
        # Find /sap/opu/odata/sap and extract everything up to the service name
        parts = api_endpoint.split("/")
        base_path = "/".join(parts[:8]) + "/"

        headers = {
            "x-csrf-token": "Fetch",
            "Accept": "application/json",
            "Authorization": f"Basic {auth_b64}",
            "Content-Type": "application/json",
        }

        self.logger.info("Fetching new CSRF token...")

        try:
            response = self.session.get(
                base_path, headers=headers, timeout=30, verify=True
            )

            if response.status_code != 200:
                raise Exception(
                    f"Failed to fetch CSRF token. Status: {response.status_code}"
                )

            csrf_token = response.headers.get("x-csrf-token")
            if not csrf_token:
                raise Exception("No CSRF token received")

            self.csrf_token = csrf_token
            self.cookies = requests.utils.dict_from_cookiejar(self.session.cookies)
            self.last_token_fetch = datetime.now(timezone.utc)

        except Exception as e:
            self.logger.error(f"Error refreshing token: {str(e)}")
            # Reset session state on error
            self.session = None
            self.csrf_token = None
            self.cookies = None
            self.last_token_fetch = None
            raise


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
