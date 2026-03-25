import argparse
import asyncio
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

import boto3
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient

# Load environment variables
load_dotenv()

app = BedrockAgentCoreApp()

model_id = os.getenv('MODEL_ID', 'us.anthropic.claude-3-7-sonnet-20250219-v1:0')

model = BedrockModel(
    model_id=model_id,
)

# Log the model being used
print(f"🤖 SAP Agent initialized with model: {model_id}")
print(f"📍 Model region: {os.environ.get('AWS_DEFAULT_REGION', config.AWS_REGION)}")


def create_streamable_http_transport():
    region = os.getenv('AWS_REGION', config.AWS_REGION)
    secret_name = os.getenv('SECRETS_COGNITO_NAME', 'sap_cognito_config')
    ssm_client = boto3.client("ssm", region_name=region)
    secrets_client = boto3.client("secretsmanager", region_name=region)

    try:
        mcp_arn = ssm_client.get_parameter(Name="/sap_mcp_server/runtime/agent_arn")[
            "Parameter"
        ]["Value"]
        creds = json.loads(
            secrets_client.get_secret_value(SecretId=secret_name)[
                "SecretString"
            ]
        )

        encoded_arn = mcp_arn.replace(":", "%3A").replace("/", "%2F")
        mcp_url = f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{encoded_arn}/invocations?qualifier=DEFAULT"

        headers = {"Authorization": f"Bearer {creds['bearer_token']}"}
        return streamablehttp_client(mcp_url, headers=headers)
    except Exception as e:
        logger.error(f"Failed to create streamable HTTP transport: {e}")
        raise


@app.entrypoint
async def process_exception(payload, context):
    """
    Invoke the agent with flexible payload supporting multiple invocation patterns:
    1. Email-triggered: email_contents (with transaction identifiers extracted from content)
    2. Frontend-triggered: transaction_number
    3. Direct query: user_prompt only
    """
    # Initialize with empty payload if none provided
    if payload is None:
        payload = {}

    # Extract flexible payload fields
    transaction_number = payload.get("transaction_number")
    email_contents = payload.get("email_contents")
    user_prompt = payload.get("user_prompt")

    # todo: fix amount of times tool is called and displayed

    unified_system_prompt = """
    You are an expert SAP exception handling specialist with comprehensive knowledge of SAP S4HANA business processes.  You specialize in resolving exceptions according to established SOPs and best practices. Attempt to resolve the exception using instructions from the workflow instructions, Standard Operating Procedure, and your ample SAP knowledge. You have the authorization to make the required changes on the SAP system, but your actions must be grounded in evidence. Follow Standard operating procedure (SOP) to determine approved path to resolution. You must track progress in the state using available MCP tools (add_escalation_entry, update_state, create_processing_history_entry). 
    
    ## ESCALATION RULES
    - If you determine escalation is required and you have not received escalation yet, end process and do not simulate evidence or approval. 
    - Confirm that escalation evidence/approval context has been included in the prompt before executing resolution.

    ## SOP COMPLIANCE (CRITICAL - NON-NEGOTIABLE)
    - SOPs are MANDATORY business rules, not suggestions
    - NEVER skip, modify, or optimize SOP steps
    - ALWAYS follow SOP sequence exactly as written
    - If SOP says "email first", you MUST email first
    - Do NOT assume you can improve the process
    - Compliance > Efficiency

    ## SOP EXECUTION PROTOCOL
    1. Query SOP for exact scenario match
    2. Identify ALL required steps in sequence
    3. Execute EACH step completely before proceeding to next
    4. Document completion of each step using state tools
    5. NEVER jump ahead in the sequence
    6. If step requires external confirmation, STOP and wait

    ## AUTHORIZATION AND BOUNDARIES
    - You have authorization to access SAP data and perform actions only on API's specified with search_sap_api_knowledge_base. Do NOT hallucinate API's. 
    - All actions must be grounded in SOPs, email evidence, or established SAP best practices
    - You must document all decisions and actions for audit purposes
    - You must never invent SAP APIs or transaction codes that do not exist
    - If the SOP is limited and/or diverges from SAP best practices according to what you know, follow your SAP knowledge and document decisions using available state tools on the MCP server(s).
        
    **WORKFLOW:**
    1. **Gather Relevant Data**
        - Use search_sap_api_knowledge_base to identify the SAP OData API service and entity needed
        - Use construct_sap_api_url tool to build the complete URL from the API path (e.g., "API_SUPPLIERINVOICE_PROCESS_SRV/A_SupplierInvoice('1900000002')")
        - Execute precise OData calls using invoke_sap_odata_service tool with the constructed URL
        - Assemble a complete picture of the exception
    2. **Analyze and Plan Resolution**
        - Use Search SOPs tool to identify the exact handling procedure
        - Consider business impacts and compliance requirements
    3. **Execute Resolution Steps (STRICT SOP COMPLIANCE)**
        - Follow SOP guidance for resolution IN EXACT SEQUENCE
        - For each SOP step: Execute completely, document, then proceed
        - NEVER skip steps even if you think they're unnecessary
        - If SOP requires email/escalation: Do it FIRST, then wait for response
        - Document actions with create_processing_history_entry tool
        - Update transaction status appropriately for each step 
    4. **Take Necessary Actions**
        - Call SAP Odata APIs to implement resolution 
        - IMPORTANT: Always use construct_sap_api_url BEFORE invoke_sap_odata_service to ensure correct server URL
        - Handle any escalation requirements according to SOPs
        When escalation is required:
            - CRITICAL: Search SOPs thoroughly for ALL escalation contacts (procurement, finance, approvers, etc.)
            - Extract EVERY email address mentioned in the SOP for this exception type
            - IMPORTANT: When SOP lists multiple emails in parentheses separated by commas, extract ALL of them, not just the first one
            - If SOP says "contact procurement AND finance" or lists multiple roles, include ALL of them
            - MANDATORY: Use verify_email_recipients tool FIRST to confirm all recipients are parsed correctly
            - Format multiple recipients as COMMA-SEPARATED LIST from the SOP
            - NEVER send separate emails - one email to ALL recipients in a single send_escalation_email call
            - Verify the send_escalation_email response confirms delivery to ALL recipients
            - Track escalations using add_escalation_entry mcp tool
            - Do not simulate or hallucinate replies or approvals. Stick to email context provided in the prompt
            - ALWAYS confirm the total_recipients count matches what the SOP specified
    5. **Update Transaction Status**
        - Verify exception is resolved as per SOP before sending confirmation email and before marking resolved in the state
        - Use available tools to document resolution in the system
        - Send confirmation of resolution according to SOP
        - Update workflow status
        - Ensure appropriate follow-up actions are queued
    """

    # Improved streaming with better text buffering and formatting
    async def stream_generator():
        client = MCPClient(create_streamable_http_transport)

        # Enhanced retry for MCP throttling and Bedrock service errors
        async def with_retry(operation, max_retries=5):
            for retry_count in range(max_retries):
                try:
                    return operation()
                except Exception as e:
                    error_msg = str(e)
                    should_retry = (
                        "429" in error_msg
                        or "Too Many Requests" in error_msg
                        or "throttl" in error_msg.lower()
                        or "serviceUnavailableException" in error_msg
                        or "ServiceUnavailable" in error_msg
                        or "ConverseStream" in error_msg
                    )
                    
                    if should_retry and retry_count < max_retries - 1:
                        # Exponential backoff with jitter for Bedrock errors
                        if "serviceUnavailableException" in error_msg or "ConverseStream" in error_msg:
                            base_delay = min(2**(retry_count + 2), 30)  # 4, 8, 16, 30 seconds max
                        else:
                            base_delay = 2**retry_count  # 1, 2, 4 seconds for other errors
                        
                        jitter = random.uniform(0.5, 1.5)  # More jitter for better distribution
                        wait_time = base_delay * jitter
                        
                        await asyncio.sleep(wait_time)
                        continue
                    raise e
            return None

        try:
            with client:
                tools = (
                    await with_retry(lambda: client.list_tools_sync())
                    or client.list_tools_sync()
                )
                # Log model info before creating agent
                print(f"🔄 Creating agent with model: {model_id}")
                
                # Create agent with MCP tools and the appropriate system prompt based on input type
                agent = Agent(
                    model=model,
                    tools=tools,
                    system_prompt=unified_system_prompt,
                )

                prompt = None
                if email_contents:
                    prompt = f"""
                    **Email Context**
                    # begin email context
                    {email_contents}
                    # end email context
                    
                    You specialize in resolving email-driven invoice exceptions according to established SOPs and best practices. Use the provided email context (which includes reply and thread from a previous escalation attempt) to attempt to  resolve the exception using instructions from the workflow instructions, Standard Operating Procedure, email context, and your ample SAP knowledge. A previous attempt to resolve an exception has been escalated via email and you are to take that email context as evidence/approval to take further action on SAP to resolve the exception.

                    **EMAIL CONTEXT INTERPRETATION:**
                    - Use the provided email thread (including previous escalation attempts) as evidence/approval
                    - Identify the specific exception being escalated and its current state
                    - Analyze tone and urgency to prioritize response accordingly

                    **EMAIL-SPECIFIC WORKFLOW ADDITIONS:**
                    1. **Thread Analysis**
                        - Extract invoice number, PO number, vendor details from both current and previous emails
                        - Identify previous resolution attempts with available mcp state tools and identify why they failed
                        - Note any further context, approvals, or authorizations provided in the thread

                    2. **Email Response Formatting**
                        - Maintain professional, solution-oriented tone
                        - Structure responses with clear sections: Understanding, Action Taken, Result, Next Steps
                        - Include relevant SAP transaction numbers and timestamps
                        - Provide appropriate level of technical detail based on recipient role"""

                # ---------------------------------------------------------------------------- #
                #                             front-end invocation                             #
                # ---------------------------------------------------------------------------- #
                elif transaction_number:
                    prompt = f"""
                    Transaction number (SAP Invoice Number): {transaction_number}
                    
                    You are an expert SAP procure-to-pay exception handling specialist with comprehensive knowledge of SAP S4HANA business processes. Your expertise covers the entire P2P lifecycle including requisitioning, purchasing, goods receipt, invoice verification, and payment processing.

                    **TRANSACTION CONTEXT INTERPRETATION:**
                        - Process begins with transaction number
                        - Prioritize data integrity and transaction completion

                    **TRANSACTION-SPECIFIC WORKFLOW ADDITIONS:**
                    1. **Transaction Validation**
                        - Verify the transaction number format and existence in SAP
                        - Trace document flow to identify related transaction documents like invoice, purchase order, and goods receipt data, etc.
                        - Determine current exception state and blocking points

                    2. **API Interaction Protocol**
                        - Use search_sap_api_knowledge_base to identify the SAP OData API service and entity path
                        - Use construct_sap_api_url to build the complete URL from the API path
                        - Execute precise OData calls using invoke_sap_odata_service tool with the constructed URL
                        - Example flow:
                          1. Query KB: "How to release supplier invoice?" → Get path: "API_SUPPLIERINVOICE_PROCESS_SRV/A_SupplierInvoice('1900000002')/Release"
                          2. Construct URL: construct_sap_api_url("API_SUPPLIERINVOICE_PROCESS_SRV/A_SupplierInvoice('1900000002')/Release")
                          3. Invoke API: invoke_sap_odata_service(constructed_url, "POST")

                    3. **Transaction Completion**
                        - Provide structured response with transaction status
                        - Include all transaction numbers affected
                        - Return clear success/failure indicators and next steps
                    """
                elif user_prompt:
                    prompt = f"""
                    User prompt: {user_prompt}
                    
                    **CHAT CONTEXT INTERPRETATION:**
                        - Engage in interactive problem-solving with users
                        - Provide educational context about SAP processes when helpful
                        - Guide users through exception resolution steps

                    **CHAT-SPECIFIC WORKFLOW ADDITIONS:**
                    1. **Interactive Analysis**
                        - Ask clarifying questions when information is incomplete
                        - Offer multiple resolution options when appropriate
                        - Provide step-by-step guidance that users can follow

                    2. **User Education Elements**
                        - Explain P2P concepts when relevant to the exception
                        - Reference specific SAP transaction codes and navigation paths
                        - Offer preventative advice to avoid similar exceptions in the future

                    3. **Conversation Management**
                        - Maintain context throughout the conversation
                        - Summarize complex technical details in accessible language
                        - Provide visual cues (e.g., bullets, numbering) for clarity
                        - Check for user understanding before proceeding to next steps
                    """
                else:
                    prompt = "Please provide transaction information, email content, or a direct query to process."

                agent_stream = agent.stream_async(prompt)

                # Buffer for accumulating text chunks with rate limiting
                text_buffer = ""
                last_yield_time = time.time()
                min_yield_interval = (
                    0.5  # Minimum 500ms between yields to prevent throttling
                )

                # Tool usage tracking to reduce repetitive logs
                last_tool_name = None
                consecutive_tool_uses = 0

                # Circuit breaker for consecutive Bedrock errors
                consecutive_errors = 0
                max_consecutive_errors = 3
                
                async for event in agent_stream:
                    current_time = time.time()
                    
                    # Reset error counter on successful event
                    consecutive_errors = 0

                    if "data" in event:
                        content = event["data"]
                        if content:
                            # Add content to buffer
                            text_buffer += content

                            # Rate-limited buffering: respect minimum interval
                            time_since_last_yield = current_time - last_yield_time

                            should_yield = (
                                # Respect minimum interval to prevent throttling
                                time_since_last_yield >= min_yield_interval
                                and (
                                    # Complete sentences (ending with punctuation + space/newline)
                                    any(
                                        text_buffer.rstrip().endswith(punct)
                                        for punct in [
                                            ". ",
                                            ".\n",
                                            "! ",
                                            "!\n",
                                            "? ",
                                            "?\n",
                                        ]
                                    )
                                    or
                                    # Complete phrases (ending with colon, comma + space)
                                    any(
                                        text_buffer.rstrip().endswith(punct)
                                        for punct in [": ", ":\n", ", "]
                                    )
                                    or
                                    # Buffer getting too long (prevent memory issues)
                                    len(text_buffer) > 300
                                    or
                                    # Force yield after longer delay
                                    time_since_last_yield > 10.0
                                )
                            )

                            if should_yield and text_buffer.strip():
                                # Clean up the text before yielding
                                clean_text = text_buffer.strip()
                                # Fix common spacing issues
                                clean_text = clean_text.replace(" \n", "\n").replace(
                                    "\n ", "\n"
                                )
                                # Ensure proper spacing around punctuation
                                clean_text = clean_text.replace("  ", " ")

                                yield clean_text
                                text_buffer = ""
                                last_yield_time = current_time

                                # Add delay to prevent rapid successive calls
                                await asyncio.sleep(
                                    0.1
                                )  # 100ms delay as per deployment guide

                    elif "current_tool_use" in event:
                        # Yield any buffered content before tool use
                        if text_buffer.strip():
                            yield text_buffer.strip()
                            text_buffer = ""

                        # Get current tool name
                        tool_name = event["current_tool_use"].get("name", "Unknown")

                        # Smart tool usage logging to reduce repetitive logs
                        if tool_name != last_tool_name:
                            # New tool being used - reset counter and log it
                            consecutive_tool_uses = 1
                            yield f"\n🔧 Using {tool_name} tool...\n"
                            last_tool_name = tool_name
                        else:
                            # Same tool being used again
                            consecutive_tool_uses += 1
                            # Only log every 5th consecutive use of the same tool
                            if consecutive_tool_uses % 5 == 0:
                                yield f"\n🔧 Using {tool_name} tool... (used {consecutive_tool_uses} times)\n"

                        last_yield_time = current_time

                    elif "result" in event:
                        # Yield any remaining buffered content
                        if text_buffer.strip():
                            yield text_buffer.strip()
                            text_buffer = ""

                        # Provide completion message
                        yield f"\n✅ Processing completed\n"
                        last_yield_time = current_time

                # Yield any remaining content in buffer
                if text_buffer.strip():
                    yield text_buffer.strip()

        except Exception as e:
            error_msg = str(e)
            
            # Handle specific Bedrock service errors with retry suggestion
            if "serviceUnavailableException" in error_msg or "ConverseStream" in error_msg:
                yield f"\n❌ Bedrock service temporarily unavailable. Please try again in a few moments.\n"
                yield f"\nℹ️ This is typically due to high demand. The system will automatically retry with backoff.\n"
            elif "429" in error_msg or "throttl" in error_msg.lower():
                yield f"\n❌ Rate limit exceeded. Please wait before retrying.\n"
            else:
                yield f"\n❌ Error: {error_msg}\n"

    # Return the streaming generator
    return stream_generator()


async def run_cli_mode(payload_data):
    """
    Run the agent in CLI mode with provided payload
    """
    print("Running SAP Agent in CLI mode...")

    try:
        # Process the payload directly
        result_generator = await process_exception(payload_data)

        # Stream the results to console
        async for chunk in result_generator:
            print(chunk, end="", flush=True)

        print("\n\nCLI processing completed.")

    except Exception as e:
        print(f"CLI Error: {str(e)}")
        sys.exit(1)


def parse_arguments():
    """
    Parse command line arguments
    """
    parser = argparse.ArgumentParser(description="SAP Agent - Service or CLI mode")
    parser.add_argument(
        "--payload",
        type=str,
        help="JSON payload for CLI mode (if not provided, runs in service mode)",
    )
    parser.add_argument(
        "--payload-file",
        type=str,
        help="Path to JSON file containing payload for CLI mode",
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()

    # Check if we should run in CLI mode
    if args.payload or args.payload_file:
        # CLI Mode
        payload_data = {}

        if args.payload:
            try:
                payload_data = json.loads(args.payload)
            except json.JSONDecodeError as e:
                print(f"Error parsing payload JSON: {e}")
                sys.exit(1)

        elif args.payload_file:
            try:
                with open(args.payload_file, "r") as f:
                    payload_data = json.load(f)
            except FileNotFoundError:
                print(f"Payload file not found: {args.payload_file}")
                sys.exit(1)
            except json.JSONDecodeError as e:
                print(f"Error parsing payload file JSON: {e}")
                sys.exit(1)

        # Run in CLI mode
        try:
            asyncio.run(run_cli_mode(payload_data))
        except KeyboardInterrupt:
            print("\nCLI execution interrupted...")

    else:
        # Service Mode (default behavior)
        print("Starting SAP Agent service...")
        print("Waiting for invocations on port 8080...")
        print("Use --payload or --payload-file for CLI mode")

        try:
            asyncio.run(app.run())
        except KeyboardInterrupt:
            print("\nShutting down SAP Agent service...")
        except Exception as e:
            print(f"Unexpected error: {str(e)}")
            sys.exit(1)
