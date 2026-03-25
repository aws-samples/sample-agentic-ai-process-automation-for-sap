import json
import os
import sys
import uuid
from datetime import datetime
import base64
import re

# Add parent directory to path to import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
import pandas as pd
import streamlit as st
import requests
from config import config

# Configure AWS
# AWS_PROFILE = "abhi-awsbuild02-aws-profile"
TABLE_NAME = "invoice-state-dev"
REGION = config.AWS_REGION


def get_dynamodb_data():
    """Fetch data from DynamoDB table"""
    try:
        # Use default AWS credentials from environment
        dynamodb = boto3.resource("dynamodb", region_name=REGION)
        table = dynamodb.Table(TABLE_NAME)

        # Check table status first
        table_status = table.table_status
        if table_status != "ACTIVE":
            st.error(f"Table status is {table_status}, not ACTIVE")
            return []

        # Scan table (use with caution for large tables)
        response = table.scan(Limit=100)  # Limit initial scan
        items = response["Items"]

        # Handle pagination if needed (but limit total items for demo)
        page_count = 1
        while "LastEvaluatedKey" in response and page_count < 5:
            response = table.scan(
                ExclusiveStartKey=response["LastEvaluatedKey"], Limit=100
            )
            items.extend(response["Items"])
            page_count += 1

        # Sort by creation date (newest first)
        if items:
            items.sort(key=lambda x: x.get('created_on', ''), reverse=True)
        
        return items
    except Exception as e:
        st.error(f"Error fetching data: {str(e)}")
        return []


def refresh_cognito_token():
    """Refresh expired Cognito JWT token"""
    try:
        region = os.environ.get('AWS_DEFAULT_REGION', config.AWS_REGION)
        secrets_client = boto3.client('secretsmanager', region_name=region)
        cognito_client = boto3.client('cognito-idp', region_name=region)
        
        # Get Cognito config
        response = secrets_client.get_secret_value(SecretId='sap_cognito_config')
        config = json.loads(response['SecretString'])
        
        # Generate SECRET_HASH
        import hmac
        import hashlib
        message = 'demo-user' + config['client_id']
        secret_hash = base64.b64encode(
            hmac.new(
                config['client_secret'].encode(),
                message.encode(),
                digestmod=hashlib.sha256
            ).digest()
        ).decode()
        
        # Get new token
        auth_response = cognito_client.admin_initiate_auth(
            UserPoolId=config['user_pool_id'],
            ClientId=config['client_id'],
            AuthFlow='ADMIN_NO_SRP_AUTH',
            AuthParameters={
                'USERNAME': 'demo-user',
                'PASSWORD': config.COGNITO_PERMANENT_PASSWORD,
                'SECRET_HASH': secret_hash
            }
        )
        
        new_token = auth_response['AuthenticationResult']['AccessToken']
        
        # Update stored config
        config['bearer_token'] = new_token
        secrets_client.update_secret(
            SecretId='sap_cognito_config',
            SecretString=json.dumps(config)
        )
        
        return new_token
        
    except Exception as e:
        st.error(f"Failed to refresh token: {e}")
        return None

def get_agentcore_config():
    """Get AgentCore agent configuration from AWS with automatic token refresh"""
    try:
        region = os.environ.get('AWS_DEFAULT_REGION', config.AWS_REGION)
        
        # Use default AWS credentials from environment
        ssm_client = boto3.client('ssm', region_name=region)
        secrets_client = boto3.client('secretsmanager', region_name=region)
        
        # Use the deployed Strands agent
        agent_arn_response = ssm_client.get_parameter(Name='/sap_strands_agent/runtime/agent_arn')
        agent_arn = agent_arn_response['Parameter']['Value']
        
        # Get fresh token automatically
        bearer_token = refresh_cognito_token()
        if not bearer_token:
            # Fallback to stored token if refresh fails
            response = secrets_client.get_secret_value(SecretId='sap_cognito_config')
            secret_value = response['SecretString']
            parsed_secret = json.loads(secret_value)
            bearer_token = parsed_secret['bearer_token']
        
        # Encode ARN for URL
        encoded_arn = agent_arn.replace(':', '%3A').replace('/', '%2F')
        agent_url = f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{encoded_arn}/invocations?qualifier=DEFAULT"
        
        headers = {
            "authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json"
        }
        
        return agent_url, headers
        
    except Exception as e:
        st.error(f"Failed to get AgentCore config: {e}")
        # Fallback to local for development
        return "http://localhost:8080/invocations", {"Content-Type": "application/json"}


@st.dialog("Processing Results")
def show_processing_dialog(transaction_id):
    """Show processing results in a modal dialog"""
    result = st.session_state.processing_results.get(transaction_id, {})
    
    st.subheader(f"Transaction: {transaction_id}")
    
    # Status indicator
    status = result.get('status', 'Unknown')
    if 'completed' in status.lower():
        st.success(f"✅ {status}")
    elif 'error' in status.lower():
        st.error(f"❌ {status}")
    else:
        st.info(f"🔄 {status}")
    
    # Content area with proper formatting
    content = result.get('content', '')
    if content:
        # Clean up the content
        cleaned_content = clean_agent_response(content)
        st.markdown(cleaned_content)
    
    # Close button
    if st.button("Close", use_container_width=True):
        if transaction_id in st.session_state.processing_results:
            st.session_state.processing_results[transaction_id]['show_modal'] = False
        st.rerun()

def clean_agent_response(text):
    """Clean up agent response text for better readability"""
    if not text:
        return "No response received."
    
    import html
    import re
    
    # Decode HTML entities
    text = html.unescape(text)
    
    # Remove excessive quotes and escape characters
    text = text.replace('&quot;', '"').replace('&amp;', '&').replace('&#39;', "'")
    text = text.replace('\"', '"').replace('\\n', '\n')
    
    # Clean up excessive quotes
    text = re.sub(r'""([^"]+)""', r'\1', text)
    text = re.sub(r'"([^"]+)"', r'\1', text)
    
    # Fix line breaks
    text = text.replace('\n', '\n\n')
    
    # Remove excessive newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()

def process_transaction(row):
    """Call AgentCore runtime to resolve exception with transaction information"""
    import json
    import re

    import requests
    from requests.exceptions import ChunkedEncodingError

    transaction_id = row.get('transaction_number', 'unknown')
    
    # Show initial status
    with st.spinner("Starting transaction processing..."):
        pass

    try:

        # Convert pandas Series to dictionary if needed
        if hasattr(row, "to_dict"):
            row_dict = row.to_dict()
        elif isinstance(row, dict):
            row_dict = row
        else:
            st.error(f"Unsupported row data type: {type(row)}")
            return

        processed_row = {
            k: str(v) if v is not None else "" for k, v in row_dict.items()
        }

        # Prepare minimal payload
        payload = {
            "transaction_number": processed_row.get("transaction_number", ""),
            "transaction_item_number": processed_row.get(
                "transaction_item_number", ""
            ),
        }
        
        # Get AgentCore configuration
        agent_url, headers = get_agentcore_config()
        
        # Store data for logs view (no auto-redirect)
        st.session_state['current_transaction'] = transaction_id
        st.session_state['agent_url'] = agent_url
        st.session_state['headers'] = headers
        st.session_state['payload'] = payload
        st.success(f"✅ Transaction {transaction_id} ready for processing. Go to Agent Logs to start.")
            
    except Exception as e:
        st.error(f"Setup error: {str(e)}. Ensure AgentCore agents are deployed and accessible.")


def get_csrf_token(api_endpoint, auth_b64):
    """Get CSRF token and session for SAP API calls"""
    headers = {
        'x-csrf-token': 'Fetch',
        'Accept': 'application/json',
        'Authorization': f'Basic {auth_b64}'
    }
    
    try:
        # Create session to maintain cookies
        session = requests.Session()
        session.verify = False
        
        response = session.get(api_endpoint, headers=headers)
        
        if response.status_code != 200:
            st.error(f"Failed to fetch CSRF token. Status: {response.status_code}")
            return None, None
        
        csrf_token = response.headers.get('x-csrf-token')
        if not csrf_token:
            st.error("No CSRF token received")
            return None, None
        
        return csrf_token, session
        
    except Exception as e:
        st.error(f"Error fetching CSRF token: {e}")
        return None, None

def call_sap_release_api(supplier_invoice, fiscal_year, username, password):
    """Call SAP Release API with proper authentication and CSRF token"""
    base_url = config.SAP_BASE_URL
    api_endpoint = base_url
    release_url = f"{base_url}/Release?SupplierInvoice='{supplier_invoice}'&FiscalYear='{fiscal_year}'&DiscountDaysHaveToBeShifted=false"
    
    # Get authentication
    auth_string = f"{username}:{password}"
    auth_bytes = auth_string.encode('ascii')
    auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
    
    try:
        # Get CSRF token and session
        csrf_token, session = get_csrf_token(api_endpoint, auth_b64)
        
        if not csrf_token or not session:
            return False, "Failed to get CSRF token", None
        
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'x-csrf-token': csrf_token,
            'Authorization': f'Basic {auth_b64}'
        }
        
        response = session.post(release_url, headers=headers)
        
        # Parse response data
        try:
            response_data = response.json() if response.text else {"status_code": response.status_code, "headers": dict(response.headers)}
        except:
            response_data = {"status_code": response.status_code, "text": response.text, "headers": dict(response.headers)}
        
        if response.status_code in [200, 201, 204]:
            return True, "Invoice released successfully", response_data
        else:
            return False, f"API call failed with status {response.status_code}: {response.text}", response_data
            
    except Exception as e:
        return False, f"Error calling SAP API: {str(e)}", None

@st.dialog("SAP Authentication")
def show_auth_dialog(transaction_number):
    """Show authentication dialog popup"""
    row = st.session_state.get(f'action_row_{transaction_number}', {})
    st.write(f"Enter SAP credentials for transaction: **{transaction_number}**")
    
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Authenticate", use_container_width=True):
            if username and password:
                with st.spinner("Calling SAP Release API..."):
                    supplier_invoice = row.get('transaction_number')
                    fiscal_year = str(pd.to_datetime(row.get('document_date')).year)
                    
                    success, message, response_data = call_sap_release_api(supplier_invoice, fiscal_year, username, password)
                    
                    # Update DynamoDB status if SAP call successful
                    if success:
                        try:
                            dynamodb = boto3.resource("dynamodb", region_name=REGION)
                            table = dynamodb.Table(TABLE_NAME)
                            table.update_item(
                                Key={'transaction_number': transaction_number},
                                UpdateExpression='SET #status = :status, last_modified_at = :timestamp',
                                ExpressionAttributeNames={'#status': 'status'},
                                ExpressionAttributeValues={
                                    ':status': 'resolved',
                                    ':timestamp': datetime.now().isoformat() + 'Z'
                                }
                            )
                        except Exception as e:
                            st.error(f"SAP call succeeded but DynamoDB update failed: {e}")
                    
                    # Store result in session state
                    st.session_state['api_result'] = {
                        'success': success,
                        'message': message,
                        'response_data': response_data,
                        'supplier_invoice': supplier_invoice,
                        'fiscal_year': fiscal_year
                    }
                    st.session_state['show_result'] = True
                    st.rerun()
            else:
                st.error("Please enter both username and password")
    
    with col2:
        if st.button("Cancel", use_container_width=True):
            st.rerun()

@st.dialog("API Response")
def show_result_dialog():
    """Show API result dialog popup"""
    result = st.session_state.get('api_result', {})
    
    if result.get('success'):
        st.success(f"✅ {result.get('message')}")
        st.info(f"Action completed for invoice {result.get('supplier_invoice')} (FY: {result.get('fiscal_year')})")
    else:
        st.error(f"❌ {result.get('message')}")
    
    if result.get('response_data'):
        st.subheader("API Response:")
        st.json(result.get('response_data'))
    
    if st.button("Close", use_container_width=True):
        st.session_state['show_result'] = False
        st.session_state.pop('api_result', None)
        st.rerun()

def take_action(row):
    """Handle Take Action button click"""
    transaction_number = row.get('transaction_number', 'unknown')
    st.session_state[f'show_auth_{transaction_number}'] = True
    st.session_state[f'action_row_{transaction_number}'] = row

def format_agent_response(text):
    """Format the agent response for better readability"""
    if not text or not text.strip():
        return "No response received."

    # Clean up the text
    formatted = text.strip()

    # Remove excessive repetitive tool calls
    lines = formatted.split("\n")
    cleaned_lines = []
    tool_call_count = {}

    for line in lines:
        line = line.strip()
        if not line:
            # Preserve empty lines for spacing
            cleaned_lines.append("")
            continue

        # Count and limit repetitive tool calls
        if "🔧" in line and "tool" in line.lower():
            tool_key = line.split("🔧")[1].strip() if "🔧" in line else line
            tool_call_count[tool_key] = tool_call_count.get(tool_key, 0) + 1

            if tool_call_count[tool_key] <= 2:  # Only show first 2 occurrences
                cleaned_lines.append(line)
            elif tool_call_count[tool_key] == 3:  # Add summary for excessive calls
                cleaned_lines.append(
                    f"🔧 _(Continuing with {tool_key.split()[0]} operations...)_"
                )
        else:
            cleaned_lines.append(line)

    # Join lines and clean up excessive whitespace
    formatted = "\n".join(cleaned_lines)

    # Remove excessive consecutive newlines (more than 2)
    import re

    formatted = re.sub(r"\n{3,}", "\n\n", formatted)

    # Add proper markdown formatting
    formatted = f"""**🤖 Agent Response:**

{formatted}

---
*Processing completed at {datetime.now().strftime('%H:%M:%S')}*
"""

    return formatted


def get_dummy_data():
    """Generate dummy data for demonstration when DynamoDB is empty"""
    timestamp = datetime.now().isoformat() + "Z"
    ttl = int(datetime.now().timestamp()) + (90 * 24 * 60 * 60)  # 90 days TTL

    return [
        {
            "transaction_number": "1900000002",  # SAP AccountingDocument
            "transaction_item_number": "001",  # SAP AccountingDocumentItem
            "document_date": "2021-11-05T00:00:00.000Z",  # SAP DocumentDate
            "status": "pending",
            "message_type": "INVOICE_EXCEPTION",
            "exception_type": "A",  # SAP PaymentBlockingReason
            "transaction_type": "Invoice receipt",  # SAP ReferenceDocumentTypeName
            "supplier_number": "17300081",  # SAP Supplier
            "amount": "-200.00",  # SAP AmountInTransactionCurrency
            "currency": "USD",  # SAP TransactionCurrency
            "external_reference": "INV2022",  # SAP DocumentReferenceID
            "created_on": timestamp,
            "timestamp": timestamp,
            "state_version": 1,
            "processing_history": [
                {
                    "processor": "ODataPoller",
                    "action": "create",
                    "timestamp": timestamp,
                    "result": "pending",
                    "details": {"initialState": True},
                }
            ],
            "auto_resolved": False,
            "is_active": True,
            "requires_human_review": False,
            "last_modified_at": timestamp,
            "metrics": {"processing_time": "0", "retry_count": "0"},
            "ttl": ttl,
        },
        {
            "transaction_number": "1900000003",  # SAP AccountingDocument
            "transaction_item_number": "001",  # SAP AccountingDocumentItem
            "document_date": "2021-11-06T00:00:00.000Z",  # SAP DocumentDate
            "status": "resolved",
            "message_type": "INVOICE_EXCEPTION",
            "exception_type": "B",  # SAP PaymentBlockingReason
            "transaction_type": "Invoice receipt",  # SAP ReferenceDocumentTypeName
            "supplier_number": "17300082",  # SAP Supplier
            "amount": "750.50",  # SAP AmountInTransactionCurrency
            "currency": "USD",  # SAP TransactionCurrency
            "external_reference": "INV2023",  # SAP DocumentReferenceID
            "created_on": timestamp,
            "timestamp": timestamp,
            "state_version": 2,
            "processing_history": [
                {
                    "processor": "ODataPoller",
                    "action": "create",
                    "timestamp": timestamp,
                    "result": "pending",
                    "details": {"initialState": True},
                },
                {
                    "processor": "AutoResolver",
                    "action": "resolve",
                    "timestamp": timestamp,
                    "result": "success",
                    "details": {"autoResolution": True},
                },
            ],
            "auto_resolved": True,
            "is_active": True,
            "requires_human_review": False,
            "last_modified_at": timestamp,
            "metrics": {"processing_time": "120", "retry_count": "0"},
            "ttl": ttl,
        },
        {
            "transaction_number": "1900000004",  # SAP AccountingDocument
            "transaction_item_number": "001",  # SAP AccountingDocumentItem
            "document_date": "2021-11-07T00:00:00.000Z",  # SAP DocumentDate
            "status": "requires_review",
            "message_type": "INVOICE_EXCEPTION",
            "exception_type": "H",  # SAP PaymentBlockingReason
            "transaction_type": "Invoice receipt",  # SAP ReferenceDocumentTypeName
            "supplier_number": "17300083",  # SAP Supplier
            "amount": "2100.75",  # SAP AmountInTransactionCurrency
            "currency": "USD",  # SAP TransactionCurrency
            "external_reference": "INV2024",  # SAP DocumentReferenceID
            "created_on": timestamp,
            "timestamp": timestamp,
            "state_version": 1,
            "processing_history": [
                {
                    "processor": "ODataPoller",
                    "action": "create",
                    "timestamp": timestamp,
                    "result": "pending",
                    "details": {"initialState": True},
                },
                {
                    "processor": "ValidationEngine",
                    "action": "escalate",
                    "timestamp": timestamp,
                    "result": "requires_review",
                    "details": {"reason": "Missing required documentation"},
                },
            ],
            "auto_resolved": False,
            "is_active": True,
            "requires_human_review": True,
            "last_modified_at": timestamp,
            "metrics": {"processing_time": "45", "retry_count": "1"},
            "ttl": ttl,
        },
    ]


def add_sample_data():
    """Add sample data to DynamoDB table for testing"""
    try:
        # Use default AWS credentials from environment
        dynamodb = boto3.resource("dynamodb", region_name=REGION)
        table = dynamodb.Table(TABLE_NAME)

        timestamp = datetime.now().isoformat() + "Z"
        ttl = int(datetime.now().timestamp()) + (90 * 24 * 60 * 60)  # 90 days TTL

        sample_items = [
            {
                "transaction_number": f"TXN-{uuid.uuid4().hex[:8].upper()}",
                "transaction_item_number": "001",
                "status": "pending",
                "message_type": "INVOICE_EXCEPTION",
                "exception_type": "R",
                "transaction_type": "INVOICE",  # Fixed typo
                "supplier_number": "SUP001",
                "amount": "1250.00",
                "currency": "USD",
                "external_reference": f"EXT-{uuid.uuid4().hex[:6]}",
                "created_on": timestamp,
                "timestamp": timestamp,
                "state_version": 1,
                "processing_history": [
                    {
                        "processor": "ODataPoller",
                        "action": "create",
                        "timestamp": timestamp,
                        "result": "pending",
                        "details": {"initialState": True},
                    }
                ],
                "auto_resolved": False,
                "is_active": True,
                "requires_human_review": False,
                "last_modified_at": timestamp,
                "metrics": {"processing_time": "0", "retry_count": "0"},
                "ttl": ttl,
            },
            {
                "transaction_number": f"TXN-{uuid.uuid4().hex[:8].upper()}",
                "transaction_item_number": "001",
                "status": "resolved",
                "message_type": "INVOICE_EXCEPTION",
                "exception_type": "B",
                "transaction_type": "INVOICE",
                "supplier_number": "SUP002",
                "amount": "750.50",
                "currency": "USD",
                "external_reference": f"EXT-{uuid.uuid4().hex[:6]}",
                "created_on": timestamp,
                "timestamp": timestamp,
                "state_version": 1,
                "processing_history": [
                    {
                        "processor": "ODataPoller",
                        "action": "create",
                        "timestamp": timestamp,
                        "result": "pending",
                        "details": {"initialState": True},
                    }
                ],
                "auto_resolved": True,
                "is_active": True,
                "requires_human_review": False,
                "last_modified_at": timestamp,
                "metrics": {"processing_time": "0", "retry_count": "0"},
                "ttl": ttl,
            },
            {
                "transaction_number": f"TXN-{uuid.uuid4().hex[:8].upper()}",
                "transaction_item_number": "001",
                "status": "requires_review",
                "message_type": "INVOICE_EXCEPTION",
                "exception_type": "H",
                "transaction_type": "INVOICE",
                "supplier_number": "SUP003",
                "amount": "2100.75",
                "currency": "USD",
                "external_reference": f"EXT-{uuid.uuid4().hex[:6]}",
                "created_on": timestamp,
                "timestamp": timestamp,
                "state_version": 1,
                "processing_history": [
                    {
                        "processor": "ODataPoller",
                        "action": "create",
                        "timestamp": timestamp,
                        "result": "pending",
                        "details": {"initialState": True},
                    }
                ],
                "auto_resolved": False,
                "is_active": True,
                "requires_human_review": True,
                "last_modified_at": timestamp,
                "metrics": {"processing_time": "0", "retry_count": "0"},
                "ttl": ttl,
            },
        ]

        # Insert sample data
        with table.batch_writer() as batch:
            for item in sample_items:
                batch.put_item(Item=item)

        st.success(f"✅ Added {len(sample_items)} sample records to the table!")

    except Exception as e:
        st.error(f"Error adding sample data: {str(e)}")


def show_logs_view():
    """Show streaming logs view"""
    from streaming_logs import show_streaming_logs
    show_streaming_logs()

def show_analytics_view():
    """Show analytics dashboard view"""
    from transaction_analytics import show_transaction_analytics
    
    # Back button
    if st.button("← Back to Dashboard", use_container_width=False):
        st.session_state['show_analytics'] = False
        st.rerun()
    
    # Show analytics dashboard
    show_transaction_analytics()

def show_agentcore_logs_view():
    """Show AgentCore logs view with optional real-time streaming"""
    import os
    import boto3
    from datetime import datetime, timedelta
    import json
    import requests
    import time
    
    st.title("🔍 Agent Logs")
    
    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("← Back to Dashboard"):
            st.session_state['show_agentcore_logs'] = False
            st.rerun()
    
    # Check if we have a current transaction being processed
    current_transaction = st.session_state.get('current_transaction')
    agent_url = st.session_state.get('agent_url')
    headers = st.session_state.get('headers')
    payload = st.session_state.get('payload')
    

    
    # Show pending transaction info if available
    if current_transaction:
        st.info(f"🔄 Transaction **{current_transaction}** ready for processing")
    
    # Log source selection with Live Processing option
    log_options = ["Strands Agent", "MCP Server"]
    if current_transaction and agent_url and headers and payload:
        log_options.insert(0, "Live Processing")
        st.success("Live Processing option available!")
    
    selected_source = st.selectbox("Select Log Source:", log_options)
    
    if selected_source == "Live Processing" and current_transaction:
        st.subheader(f"📝 Live Processing for {current_transaction}")
        
        if st.button("▶️ Start Processing", use_container_width=True):
            # Create placeholder for streaming content
            streaming_placeholder = st.empty()
            
            try:
                # Make streaming request to AgentCore
                response = requests.post(
                    agent_url,
                    headers=headers,
                    json=payload,
                    timeout=180,
                    stream=True
                )
                
                if response.status_code == 200:
                    accumulated_content = ""
                    chunk_count = 0
                    
                    def sanitize_content(raw_content):
                        """Clean up streaming content and filter out tool usage lines"""
                        lines = raw_content.split('\n')
                        cleaned_lines = []
                        
                        for line in lines:
                            line = line.strip()
                            if line.startswith('data: '):
                                # Remove data: prefix and quotes
                                content = line[6:]  # Remove 'data: '
                                if content.startswith('"') and content.endswith('"'):
                                    content = content[1:-1]  # Remove quotes
                                # Convert \n to actual line breaks
                                content = content.replace('\\n', '\n')
                                
                                # Filter out tool usage lines and fix colons
                                if not (
                                    '🔧 Using' in content and 'tool' in content
                                ) and content.strip():
                                    # Replace colons at end of sentences with periods
                                    content = content.rstrip()
                                    if content.endswith(':'):
                                        content = content[:-1] + '.'
                                    cleaned_lines.append(content)
                        
                        return '\n'.join(cleaned_lines)
                    
                    # Stream the response
                    for chunk in response.iter_content(chunk_size=1024, decode_unicode=True):
                        if chunk:
                            accumulated_content += chunk
                            chunk_count += 1
                            
                            # Sanitize and display content (filter out tool usage)
                            clean_content = sanitize_content(accumulated_content)
                            
                            # Update the streaming placeholder with cleaned content
                            with streaming_placeholder.container():
                                st.markdown("**Agent Response:**")
                                
                                # Add CSS for word wrapping and width control
                                st.markdown(
                                    "<style>.stMarkdown pre { white-space: pre-wrap; word-wrap: break-word; max-width: 100%; overflow-wrap: break-word; }</style>",
                                    unsafe_allow_html=True
                                )
                                
                                st.markdown(f"```\n{clean_content}\n```")
                                
                                # Auto-scroll to bottom
                                st.markdown(
                                    "<script>setTimeout(() => window.scrollTo(0, document.body.scrollHeight), 100);</script>",
                                    unsafe_allow_html=True
                                )
                            
                            # Small delay to make streaming visible
                            time.sleep(0.1)
                    
                    # Processing completed
                    st.success("✅ Transaction processing completed!")
                    
                    # Clear the current transaction from session state
                    st.session_state.pop('current_transaction', None)
                    st.session_state.pop('agent_url', None)
                    st.session_state.pop('headers', None)
                    st.session_state.pop('payload', None)
                    
                else:
                    st.error(f"❌ Error: HTTP {response.status_code} - {response.text}")
                    
            except Exception as e:
                st.error(f"❌ Streaming error: {str(e)}")
    
    elif selected_source == "Strands Agent":
        show_log_tab("Strands Agent", "/aws/bedrock-agentcore/runtimes/sap_strands_agent-sL8nKv3Zvs-DEFAULT")
    
    elif selected_source == "MCP Server":
        show_log_tab("MCP Server", "/aws/bedrock-agentcore/runtimes/sap_mcp_server-k3GSC92W5n-DEFAULT")

def show_log_tab(source_name, log_group):
    """Show logs for a specific source in a tab"""
    import os
    import boto3
    from datetime import datetime, timedelta
    import json
    
    st.subheader(f"📋 {source_name} Logs")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        minutes = st.selectbox("Time Range:", [5, 10, 30, 60], format_func=lambda x: f"{x} minutes")
    with col2:
        auto_refresh = st.checkbox("Auto-refresh (10s)", value=False)
    with col3:
        fetch_button = st.button("🔍 Fetch Logs", use_container_width=True)
    
    if fetch_button or auto_refresh:
        try:
            logs_client = boto3.client('logs', region_name=config.AWS_REGION)
            end_time = datetime.now()
            start_time = end_time - timedelta(minutes=minutes)
            
            with st.spinner(f"Fetching {source_name} logs..."):
                response = logs_client.filter_log_events(
                    logGroupName=log_group,
                    startTime=int(start_time.timestamp() * 1000),
                    endTime=int(end_time.timestamp() * 1000),
                    limit=100
                )
            
            events = response.get('events', [])
            
            if events:
                st.success(f"Found {len(events)} log entries from {source_name}")
                st.markdown("---")
                
                def clean_log_message(msg):
                    """Extract and format meaningful content from log messages using Claude"""
                    # Handle JSON logs
                    if msg.startswith('{') and msg.endswith('}'):
                        try:
                            json_obj = json.loads(msg)
                            
                            # Extract from body.content[0].text (agent responses)
                            if 'body' in json_obj and 'content' in json_obj['body']:
                                content_list = json_obj['body']['content']
                                if content_list and isinstance(content_list, list) and 'text' in content_list[0]:
                                    raw_text = content_list[0]['text']
                                    return format_with_claude(raw_text)
                            
                            # Extract from toolResult.content[0].text (tool responses)
                            if 'body' in json_obj and 'content' in json_obj['body']:
                                content_list = json_obj['body']['content']
                                if content_list and isinstance(content_list, list):
                                    for item in content_list:
                                        if 'toolResult' in item and 'content' in item['toolResult']:
                                            tool_content = item['toolResult']['content']
                                            if tool_content and isinstance(tool_content, list) and 'text' in tool_content[0]:
                                                raw_text = tool_content[0]['text']
                                                return format_with_claude(raw_text)
                            
                            # Fallback for other JSON structures
                            if 'message' in json_obj:
                                return format_with_claude(json_obj['message'])
                            elif 'msg' in json_obj:
                                return format_with_claude(json_obj['msg'])
                                
                        except:
                            pass
                    
                    # Return formatted message if no JSON parsing worked
                    return format_with_claude(msg)
                
                def format_with_claude(text):
                    """Use Claude to create readable summary from raw logs"""
                    if not text or len(text.strip()) < 20:
                        return text.strip()
                    
                    try:
                        import boto3
                        bedrock = boto3.client('bedrock-runtime', region_name=config.AWS_REGION)
                        
                        prompt = f"""Summarize the key actions and data from this log entry for troubleshooting.

STRICT RULES:
- ONLY use data that is explicitly written in the log text
- Do NOT create fake SQL queries, API endpoints, or response data
- Do NOT invent specific numbers, IDs, or values not in the log
- If the log mentions a tool or action, just say "Used [tool name]" or "Performed [action]"
- Do NOT create example data structures or mock responses
- Keep it brief and factual - no elaboration beyond what's written
- If unclear, say "Log shows [general action]" without specifics

Log text:
{text[:2000]}"""
                        
                        response = bedrock.invoke_model(
                            modelId='anthropic.claude-3-haiku-20240307-v1:0',
                            body=json.dumps({
                                'anthropic_version': 'bedrock-2023-05-31',
                                'max_tokens': 400,
                                'messages': [{'role': 'user', 'content': prompt}]
                            })
                        )
                        
                        result = json.loads(response['body'].read())
                        summary = result['content'][0]['text'].strip()
                        
                        # Fallback if summary is too short or seems wrong
                        if len(summary) < 10 or 'API call:' in summary or 'Response:' in summary:
                            return text[:300] + '...' if len(text) > 300 else text
                        
                        return summary
                        
                    except Exception as e:
                        # Fallback to simple cleaning if Claude fails
                        clean_text = text.strip()
                        lines = clean_text.split('\n')
                        cleaned_lines = [' '.join(line.split()) for line in lines]
                        clean_text = '\n'.join(cleaned_lines)
                        return clean_text[:300] + '...' if len(clean_text) > 300 else clean_text
                
                for event in reversed(events[-200:]):
                    timestamp = datetime.fromtimestamp(event['timestamp'] / 1000)
                    message = event['message'].strip()
                    
                    # Clean and display the message
                    clean_content = clean_log_message(message)
                    
                    # Show all log content without filtering
                    if clean_content and clean_content.strip():
                        st.text(f"{timestamp.strftime('%H:%M:%S')} - {clean_content}")
                        st.divider()
            else:
                st.info(f"No logs found for {source_name} in the last {minutes} minutes")
                
        except Exception as e:
            st.error(f"Error fetching logs: {e}")
    
    # Auto-refresh functionality
    if auto_refresh:
        import time
        time.sleep(10)
        st.rerun()



def main():
    st.set_page_config(
        page_title="Invoice Exceptions Dashboard",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    
    # Check if we should show logs view
    if st.session_state.get('show_logs', False):
        show_logs_view()
        return
    
    # Check if we should show AgentCore logs view
    if st.session_state.get('show_agentcore_logs', False):
        show_agentcore_logs_view()
        return
    
    # Check if we should show analytics view
    if st.session_state.get('show_analytics', False):
        show_analytics_view()
        return
    



    st.title("📊 Invoice Exceptions Dashboard")
    
    # Add navigation buttons in header
    col1, col2, col3, col4 = st.columns([4, 2, 2, 2])
    with col2:
        if st.button("📊 Analytics", use_container_width=True):
            st.session_state['show_analytics'] = True
            st.rerun()
    with col3:
        if st.button("🔍 Agent Logs", use_container_width=True):
            st.session_state['show_agentcore_logs'] = True
            st.rerun()
    with col4:
        if st.button("🔄 Refresh Data", use_container_width=True):
            st.rerun()
    
    # Handle dialog popups
    if st.session_state.get('show_result'):
        show_result_dialog()
    
    # Check for authentication requests
    for key in list(st.session_state.keys()):
        if key.startswith('show_auth_') and st.session_state[key]:
            transaction_number = key.replace('show_auth_', '')
            st.session_state[key] = False  # Reset flag
            show_auth_dialog(transaction_number)
            break

    # Fetch data
    with st.spinner("Loading data from DynamoDB..."):
        data = get_dynamodb_data()



    if not data:
        st.warning(
            "📭 No data found in DynamoDB table. Using demo data for visualization."
        )

        # Automatically use dummy data
        data = get_dummy_data()

        # Show option to add real data to DynamoDB
        if st.button("🔧 Add Sample Data to DynamoDB"):
            add_sample_data()
            st.rerun()


    # Convert to DataFrame
    df = pd.DataFrame(data)

    # Sidebar filters
    st.sidebar.header("Filters")

    # Status filter
    if "status" in df.columns:
        status_options = ["All"] + sorted(df["status"].unique().tolist())
        selected_status = st.sidebar.selectbox("Status", status_options)
        if selected_status != "All":
            df = df[df["status"] == selected_status]

    # Supplier filter
    if "supplier_number" in df.columns:
        supplier_options = ["All"] + sorted(df["supplier_number"].unique().tolist())
        selected_supplier = st.sidebar.selectbox("Supplier", supplier_options)
        if selected_supplier != "All":
            df = df[df["supplier_number"] == selected_supplier]

    # Main content
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Exceptions", len(df))

    with col2:
        if "status" in df.columns:
            active_count = len(df[df.get("is_active", True) == True])
            st.metric("Active Exceptions", active_count)

    with col3:
        if "requires_human_review" in df.columns:
            review_count = len(df[df.get("requires_human_review", False) == True])
            st.metric("Requires Review", review_count)

    with col4:
        if "amount" in df.columns:
            total_amount = (
                df["amount"].astype(str).str.replace(",", "").astype(float).sum()
            )
            st.metric("Total Amount", f"${total_amount:,.2f}")

    # Status distribution
    if "status" in df.columns:
        st.subheader("Status Distribution")
        # Define custom order for status (using actual status values from data)
        status_order = ["pending", "processing", "awaiting_human_input", "requires_manual_intervention", "resolved"]
        status_counts = df["status"].value_counts()
        # Reorder according to custom order
        ordered_data = {}
        for status in status_order:
            if status in status_counts.index:
                ordered_data[status] = status_counts[status]
        # Add any remaining statuses not in the predefined order
        for status in status_counts.index:
            if status not in status_order:
                ordered_data[status] = status_counts[status]
        # Convert to pandas Series with the correct order
        ordered_status = pd.Series(ordered_data)
        st.bar_chart(ordered_status)

    # Data table with filters
    st.subheader("Transaction Details")

    # Select columns to display
    display_columns = [
        "transaction_number",
        "status",
        "supplier_number",
        "amount",
        "currency",
        "message_type",
        "created_on",
    ]
    display_columns = [col for col in display_columns if col in df.columns]


    header_cols = st.columns([3, 2, 2, 2, 1, 2, 2, 1])
    with header_cols[0]:
        st.write("**Transaction Number**")
        txn_filter = st.text_input("", placeholder="Filter...", key="txn_filter")
    with header_cols[1]:
        st.write("**Status**")
        status_filter = st.selectbox(
            "", ["All"] + sorted(df["status"].unique().tolist()), key="status_filter"
        )
    with header_cols[2]:
        st.write("**Supplier Number**")
        supplier_filter = st.text_input(
            "", placeholder="Filter...", key="supplier_filter"
        )
    with header_cols[3]:
        st.write("**Amount**")
        amount_filter = st.text_input("", placeholder="Filter...", key="amount_filter")
    with header_cols[4]:
        st.write("**Currency**")
        currency_filter = st.selectbox(
            "",
            ["All"] + sorted(df["currency"].unique().tolist()),
            key="currency_filter",
        )
    with header_cols[5]:
        st.write("**Message Type**")
        msg_filter = st.selectbox(
            "", ["All"] + sorted(df["message_type"].unique().tolist()), key="msg_filter"
        )
    with header_cols[6]:
        st.write("**Created On**")
        date_filter = st.text_input("", placeholder="Filter...", key="date_filter")
    with header_cols[7]:
        st.write("**Details**")

    # Apply filters
    if txn_filter:
        df = df[df["transaction_number"].str.contains(txn_filter, case=False, na=False)]
    if status_filter != "All":
        df = df[df["status"] == status_filter]
    if supplier_filter:
        df = df[
            df["supplier_number"].str.contains(supplier_filter, case=False, na=False)
        ]
    if amount_filter:
        df = df[
            df["amount"].astype(str).str.contains(amount_filter, case=False, na=False)
        ]
    if currency_filter != "All":
        df = df[df["currency"] == currency_filter]
    if msg_filter != "All":
        df = df[df["message_type"] == msg_filter]
    if date_filter:
        df = df[df["created_on"].str.contains(date_filter, case=False, na=False)]

    st.divider()

    for idx, row in df.iterrows():
        expand_key = f"expand_{idx}"
        cols = st.columns([3, 2, 2, 2, 1, 2, 2, 1])

        with cols[0]:
            st.write(row.get("transaction_number", "N/A"))
        with cols[1]:
            st.write(row.get("status", "N/A"))
        with cols[2]:
            st.write(row.get("supplier_number", "N/A"))
        with cols[3]:
            st.write(row.get("amount", "N/A"))
        with cols[4]:
            st.write(row.get("currency", "N/A"))
        with cols[5]:
            st.write(row.get("message_type", "N/A"))
        with cols[6]:
            st.write(row.get("created_on", "N/A"))
        with cols[7]:
            expand_key = f"expand_{idx}"
            if st.button("👓", key=f"view_{idx}", help="View Details"):
                st.session_state[expand_key] = not st.session_state.get(
                    expand_key, False
                )

        # Show expanded details outside column layout
        if st.session_state.get(expand_key, False):
            with st.expander(
                f"Details: {row.get('transaction_number', 'N/A')}", expanded=True
            ):
                col1, col2 = st.columns(2)

                with col1:
                    st.write("**Core Information:**")
                    st.write(f"Status: {row.get('status', 'N/A')}")
                    st.write(f"Message Type: {row.get('message_type', 'N/A')}")
                    st.write(f"Exception Type: {row.get('exception_type', 'N/A')}")
                    st.write(
                        f"Transaction Type: {row.get('transaction_type', 'N/A')}"
                    )  # Fixed typo
                    st.write(f"State Version: {row.get('state_version', 'N/A')}")

                with col2:
                    st.write("**Supplier & Amount:**")
                    st.write(f"Supplier: {row.get('supplier_number', 'N/A')}")
                    st.write(
                        f"Amount: {row.get('amount', 'N/A')} {row.get('currency', '')}"
                    )
                    st.write(f"Created: {row.get('created_on', 'N/A')}")
                    st.write(f"Active: {row.get('is_active', 'N/A')}")
                    st.write(f"Auto Resolved: {row.get('auto_resolved', 'N/A')}")
                    st.write(f"Last Modified: {row.get('last_modified_at', 'N/A')}")

                # Additional details section
                st.write("**Processing Details:**")
                col3, col4 = st.columns(2)

                with col3:
                    st.write(
                        f"External Reference: {row.get('external_reference', 'N/A')}"
                    )
                    metrics = row.get("metrics", {})
                    if isinstance(metrics, dict):
                        st.write(
                            f"Processing Time: {metrics.get('processing_time', 'N/A')}s"
                        )
                        st.write(f"Retry Count: {metrics.get('retry_count', 'N/A')}")
                    st.write(f"TTL: {row.get('ttl', 'N/A')}")

                with col4:
                    processing_history = row.get("processing_history", [])
                    if processing_history and isinstance(processing_history, list):
                        st.write("**Processing History:**")
                        for i, entry in enumerate(
                            processing_history[-3:]
                        ):  # Show last 3 entries
                            if isinstance(entry, dict):
                                st.write(
                                    f"• {entry.get('processor', 'Unknown')}: {entry.get('action', 'N/A')} → {entry.get('result', 'N/A')}"
                                )
                    else:
                        st.write("No processing history available")

                # Action buttons
                if row.get('status') == 'requires_manual_intervention':
                    action_cols = st.columns([6, 1, 1])
                    with action_cols[1]:
                        if st.button("Process", key=f"process_{idx}"):
                            process_transaction(row)
                    with action_cols[2]:
                        if st.button("Take Action", key=f"action_{idx}"):
                            take_action(row)
                            st.rerun()
                else:
                    action_cols = st.columns([7, 1])
                    with action_cols[1]:
                        if st.button("Process", key=f"process_{idx}"):
                            process_transaction(row)


if __name__ == "__main__":
    main()