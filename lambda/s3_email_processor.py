import base64
import email
import hashlib
import hmac
import json
import logging
import os
import re
import urllib.parse
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import boto3
import requests
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
s3_client = boto3.client("s3")


def lambda_handler(event, context):
    """
    Lambda function to process emails stored in S3 and invoke the local agent.

    This function:
    1. Gets triggered by S3 object creation events
    2. Downloads and parses the email from S3
    3. Sends the parsed email content to the local agent
    """

    try:
        logger.info(f"Received S3 event: {json.dumps(event, default=str)}")

        # Parse the S3 event
        for record in event["Records"]:
            # Get S3 bucket and object information
            bucket_name = record["s3"]["bucket"]["name"]
            object_key = record["s3"]["object"]["key"]

            logger.info(f"Processing email from S3: s3://{bucket_name}/{object_key}")

            # Download email from S3
            try:
                email_content = download_email_from_s3(bucket_name, object_key)
            except Exception as e:
                logger.error(f"Failed to download email from S3: {str(e)}")
                continue

            # Parse email content
            try:
                email_data = parse_email_content(email_content)
            except Exception as e:
                logger.error(f"Failed to parse email content: {str(e)}")
                continue

            # Prepare agent payload with all email data in email_contents object
            agent_payload = {
                "email_contents": {
                    "subject": email_data.get("subject", ""),
                    "from": email_data.get("from", ""),
                    "to": email_data.get("to", ""),
                    "date": email_data.get("date", ""),
                    "body": email_data.get("body", ""),
                    "html_body": email_data.get("html_body", ""),
                    "threading": email_data.get("threading", {}),
                    "thread_data": email_data.get("thread_data", {}),
                    "s3_bucket": bucket_name,
                    "s3_key": object_key,
                }
            }

            logger.info(f"Invoking local agent with email data")
            logger.info(f"Subject: {agent_payload['email_contents']['subject']}")
            logger.info(f"From: {agent_payload['email_contents']['from']}")
            logger.info(
                f"Body length: {len(agent_payload['email_contents']['body'])} characters"
            )

            # Log threading information if available
            threading_info = agent_payload["email_contents"]["threading"]
            if threading_info.get("is_reply"):
                logger.info(
                    f"Email is a reply in thread: {threading_info.get('thread_topic', 'Unknown')}"
                )
                thread_data = agent_payload["email_contents"]["thread_data"]
                if thread_data.get("has_thread"):
                    logger.info(
                        f"Thread contains {thread_data.get('message_count', 1)} messages"
                    )
                    logger.info(
                        f"New content length: {len(thread_data.get('new_content', ''))} characters"
                    )

            # Invoke AgentCore Strands agent
            try:
                logger.info(f"🚀 Calling AgentCore Strands agent...")
                agent_response = invoke_local_agent(agent_payload)
                logger.info(f"✅ AgentCore Strands agent response received")
                logger.info(f"📄 Response preview: {str(agent_response)[:500]}...")

            except Exception as e:
                logger.error(f"❌ Failed to invoke AgentCore Strands agent: {str(e)}")
                continue

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": "Email processing completed successfully",
                    "processed_records": len(event["Records"]),
                }
            ),
        }

    except Exception as e:
        logger.error(f"Error processing S3 event: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps(
                {"error": "Failed to process S3 event", "details": str(e)}
            ),
        }


def download_email_from_s3(bucket_name, object_key):
    """
    Download email content from S3.

    Args:
        bucket_name (str): S3 bucket name
        object_key (str): S3 object key

    Returns:
        str: Raw email content
    """

    try:
        logger.info(f"Downloading email from s3://{bucket_name}/{object_key}")

        response = s3_client.get_object(Bucket=bucket_name, Key=object_key)
        email_content = response["Body"].read().decode("utf-8")

        logger.info(
            f"Successfully downloaded email, size: {len(email_content)} characters"
        )
        return email_content

    except Exception as e:
        logger.error(f"Error downloading email from S3: {str(e)}")
        raise


def parse_email_content(raw_email_content):
    """
    Parse raw email content to extract subject, body, threading info, and other metadata.

    Args:
        raw_email_content (str): Raw email content from S3

    Returns:
        dict: Parsed email data with subject, body, threading info, from, etc.
    """

    try:
        # Parse the email using Python's email library
        msg = email.message_from_string(raw_email_content)

        # Extract basic headers
        subject = msg.get("Subject", "")
        from_addr = msg.get("From", "")
        to_addr = msg.get("To", "")
        date = msg.get("Date", "")

        # Extract threading headers
        threading_info = extract_threading_info(msg)

        # Extract body content
        body = ""
        html_body = ""

        if msg.is_multipart():
            # Handle multipart messages
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))

                # Skip attachments
                if "attachment" in content_disposition:
                    continue

                # Get text content
                if content_type == "text/plain":
                    charset = part.get_content_charset() or "utf-8"
                    part_body = part.get_payload(decode=True)
                    if part_body:
                        try:
                            body += part_body.decode(charset, errors="ignore")
                        except:
                            body += str(part_body)
                elif content_type == "text/html":
                    charset = part.get_content_charset() or "utf-8"
                    part_body = part.get_payload(decode=True)
                    if part_body:
                        try:
                            html_body += part_body.decode(charset, errors="ignore")
                        except:
                            html_body += str(part_body)
        else:
            # Handle single-part messages
            charset = msg.get_content_charset() or "utf-8"
            payload = msg.get_payload(decode=True)
            if payload:
                try:
                    content = payload.decode(charset, errors="ignore")
                    if msg.get_content_type() == "text/html":
                        html_body = content
                    else:
                        body = content
                except:
                    body = str(payload)

        # If we only have HTML, convert it to text
        if not body and html_body:
            import re

            body = re.sub(r"<[^>]+>", "", html_body)

        # Clean up the body text
        body = body.strip()

        # Parse email thread if this is a reply
        thread_data = parse_email_thread(body, html_body)

        logger.info(
            f"Parsed email - Subject: '{subject}', From: '{from_addr}', Body length: {len(body)}"
        )
        if threading_info["is_reply"]:
            logger.info(f"Email is part of thread: {threading_info['thread_topic']}")

        return {
            "subject": subject,
            "body": body,
            "html_body": html_body,
            "from": from_addr,
            "to": to_addr,
            "date": date,
            "threading": threading_info,
            "thread_data": thread_data,
            "raw_content": (
                raw_email_content[:1000] + "..."
                if len(raw_email_content) > 1000
                else raw_email_content
            ),
        }

    except Exception as e:
        logger.error(f"Error parsing email content: {str(e)}")
        raise


def extract_threading_info(msg):
    """
    Extract email threading information from message headers.

    Args:
        msg: Email message object

    Returns:
        dict: Threading information
    """

    try:
        # Extract threading headers
        message_id = msg.get("Message-ID", "")
        in_reply_to = msg.get("In-Reply-To", "")
        references = msg.get("References", "")
        thread_topic = msg.get("Thread-Topic", "")
        thread_index = msg.get("Thread-Index", "")

        # Determine if this is a reply
        is_reply = bool(
            in_reply_to or references or (thread_index and len(thread_index) > 22)
        )  # Thread-Index grows with replies

        # Extract conversation ID (simplified)
        conversation_id = (
            thread_topic or message_id.split("@")[0] if "@" in message_id else ""
        )

        return {
            "message_id": message_id,
            "in_reply_to": in_reply_to,
            "references": references,
            "thread_topic": thread_topic,
            "thread_index": thread_index,
            "conversation_id": conversation_id,
            "is_reply": is_reply,
        }

    except Exception as e:
        logger.error(f"Error extracting threading info: {str(e)}")
        return {
            "message_id": "",
            "in_reply_to": "",
            "references": "",
            "thread_topic": "",
            "thread_index": "",
            "conversation_id": "",
            "is_reply": False,
        }


def parse_email_thread(body, html_body=""):
    """
    Parse email thread from body content to separate new content from quoted replies.

    Args:
        body (str): Plain text email body
        html_body (str): HTML email body (optional)

    Returns:
        dict: Parsed thread data with new content and quoted messages
    """

    try:
        # Common patterns that indicate quoted content
        quote_patterns = [
            r"^>.*$",  # Lines starting with >
            r"^On .* wrote:.*$",  # "On [date] [person] wrote:"
            r"^From:.*$",  # Email headers in quoted content
            r"^Sent:.*$",
            r"^To:.*$",
            r"^Subject:.*$",
            r"^\s*-----Original Message-----.*$",  # Outlook style
            r"^\s*________________________________.*$",  # Outlook separator
            r"^.*<.*@.*>.*wrote:.*$",  # Gmail/other style
        ]

        lines = body.split("\n")
        new_content_lines = []
        quoted_content_lines = []
        in_quoted_section = False

        for line in lines:
            # Check if this line indicates start of quoted content
            is_quote_indicator = any(
                re.match(pattern, line.strip(), re.IGNORECASE)
                for pattern in quote_patterns
            )

            if is_quote_indicator:
                in_quoted_section = True

            if in_quoted_section:
                quoted_content_lines.append(line)
            else:
                new_content_lines.append(line)

        new_content = "\n".join(new_content_lines).strip()
        quoted_content = "\n".join(quoted_content_lines).strip()

        # If we couldn't separate content, treat everything as new content
        if not new_content and quoted_content:
            new_content = body
            quoted_content = ""

        # Extract previous messages from quoted content
        previous_messages = extract_previous_messages(quoted_content)

        return {
            "new_content": new_content,
            "quoted_content": quoted_content,
            "previous_messages": previous_messages,
            "has_thread": bool(quoted_content),
            "message_count": len(previous_messages) + 1,  # +1 for current message
        }

    except Exception as e:
        logger.error(f"Error parsing email thread: {str(e)}")
        return {
            "new_content": body,
            "quoted_content": "",
            "previous_messages": [],
            "has_thread": False,
            "message_count": 1,
        }


def extract_previous_messages(quoted_content):
    """
    Extract individual previous messages from quoted content.

    Args:
        quoted_content (str): Quoted email content

    Returns:
        list: List of previous message dictionaries
    """

    try:
        messages = []

        # Split by common email separators
        separators = [
            r"-----Original Message-----",
            r"________________________________",
            r"On .* wrote:",
            r"From:.*\nSent:.*\nTo:.*\nSubject:.*\n",
        ]

        current_content = quoted_content

        for separator_pattern in separators:
            parts = re.split(
                separator_pattern, current_content, flags=re.IGNORECASE | re.MULTILINE
            )

            if len(parts) > 1:
                for i, part in enumerate(
                    parts[1:], 1
                ):  # Skip first part (current message)
                    if part.strip():
                        # Try to extract basic info from the message
                        message_info = extract_message_info(part.strip())
                        if message_info:
                            messages.append(message_info)
                break

        return messages

    except Exception as e:
        logger.error(f"Error extracting previous messages: {str(e)}")
        return []


def extract_message_info(message_text):
    """
    Extract basic information from a quoted message.

    Args:
        message_text (str): Text of a quoted message

    Returns:
        dict: Message information or None
    """

    try:
        lines = message_text.split("\n")

        # Look for email headers in the quoted content
        from_match = None
        sent_match = None
        to_match = None
        subject_match = None

        for line in lines[:10]:  # Check first 10 lines for headers
            line = line.strip()
            if line.startswith("From:"):
                from_match = line[5:].strip()
            elif line.startswith("Sent:"):
                sent_match = line[5:].strip()
            elif line.startswith("To:"):
                to_match = line[3:].strip()
            elif line.startswith("Subject:"):
                subject_match = line[8:].strip()

        # Extract the message body (skip header lines)
        body_lines = []
        skip_headers = True

        for line in lines:
            if (
                skip_headers
                and line.strip()
                and not any(
                    line.strip().startswith(header)
                    for header in ["From:", "Sent:", "To:", "Subject:", "Date:"]
                )
            ):
                skip_headers = False

            if not skip_headers:
                body_lines.append(line)

        body = "\n".join(body_lines).strip()

        # Only return if we found some useful information
        if from_match or subject_match or body:
            return {
                "from": from_match or "",
                "sent": sent_match or "",
                "to": to_match or "",
                "subject": subject_match or "",
                "body": (
                    body[:500] + "..." if len(body) > 500 else body
                ),  # Truncate long bodies
            }

        return None

    except Exception as e:
        logger.error(f"Error extracting message info: {str(e)}")
        return None


def invoke_agentcore_strands_agent(payload):
    """
    Invoke the AgentCore Strands agent.

    Args:
        payload (dict): Agent payload with parsed email data including subject, from, to, date, body, s3_bucket, s3_key

    Returns:
        dict: Agent response
    """

    try:
        region = os.environ.get('REGION', os.environ.get('AWS_DEFAULT_REGION', os.environ.get('AWS_REGION', 'us-east-1')))
        
        # Get AgentCore credentials and ARN
        ssm_client = boto3.client('ssm', region_name=region)
        secrets_client = boto3.client('secretsmanager', region_name=region)
        
        # Get Strands agent ARN
        agent_arn = ssm_client.get_parameter(Name='/sap_strands_agent/runtime/agent_arn')['Parameter']['Value']
        
        # Get fresh Cognito credentials with token refresh
        creds = get_fresh_cognito_token(secrets_client)
        
        # Build AgentCore URL
        escaped_agent_arn = urllib.parse.quote(agent_arn, safe='')
        agentcore_url = f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{escaped_agent_arn}/invocations?qualifier=DEFAULT"
        
        # Generate session ID that meets 33+ character requirement
        import uuid
        session_id = f"lambda-email-processor-{region}-{int(__import__('time').time())}-{uuid.uuid4().hex}"
        
        # Prepare headers with bearer token
        headers = {
            "Authorization": f"Bearer {creds['bearer_token']}",
            "Content-Type": "application/json",
            "User-Agent": "S3-Email-Processor-Lambda",
            "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id
        }

        logger.info(f"🎯 Invoking AgentCore Strands agent at: {agentcore_url}")
        logger.info(f"📦 Payload: {json.dumps(payload, indent=2)}")
        logger.info(f"🔑 Using bearer token: {creds['bearer_token'][:20]}...")

        # Make the request to AgentCore using direct HTTP (not boto3)
        # Send the payload directly without double-wrapping
        logger.info(f"🔑 Using bearer token authentication for AgentCore")
        response = requests.post(
            agentcore_url,
            headers=headers,
            json=payload,  # Use json parameter to automatically handle JSON serialization
            timeout=120,  # 2 minute timeout for AgentCore
            verify=True
        )

        if response.status_code == 200:
            logger.info(f"✅ AgentCore Strands agent invocation successful (200)")
            logger.info(f"📈 Response size: {len(response.text)} characters")
            logger.info(f"📄 Agent response: {response.text[:500]}...")
            try:
                return response.json()
            except:
                return {"response": response.text}
        else:
            error_msg = (
                f"❌ AgentCore agent returned status {response.status_code}: {response.text[:500]}..."
            )
            logger.error(error_msg)
            raise Exception(error_msg)

    except requests.exceptions.Timeout:
        error_msg = "AgentCore agent request timed out"
        logger.error(error_msg)
        raise Exception(error_msg)
    except requests.exceptions.ConnectionError:
        error_msg = "Could not connect to AgentCore agent"
        logger.error(error_msg)
        raise Exception(error_msg)
    except Exception as e:
        logger.error(f"Error invoking AgentCore agent: {str(e)}")
        raise


def get_fresh_cognito_token(secrets_client):
    """
    Get fresh Cognito token, refreshing if needed.
    """
    try:
        creds = json.loads(secrets_client.get_secret_value(SecretId='sap_cognito_config')['SecretString'])
        
        # Refresh token using Cognito
        
        cognito = boto3.client('cognito-idp', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
        
        message = 'demo-user' + creds['client_id']
        secret_hash = base64.b64encode(
            hmac.new(
                creds['client_secret'].encode(),
                message.encode(),
                digestmod=hashlib.sha256
            ).digest()
        ).decode()
        
        auth_response = cognito.admin_initiate_auth(
            UserPoolId=creds['user_pool_id'],
            ClientId=creds['client_id'],
            AuthFlow='ADMIN_NO_SRP_AUTH',
            AuthParameters={
                'USERNAME': 'demo-user',
                'PASSWORD': 'TempPass123!',
                'SECRET_HASH': secret_hash
            }
        )
        
        # Update with fresh token
        creds['bearer_token'] = auth_response['AuthenticationResult']['AccessToken']
        
        # Store updated credentials
        secrets_client.update_secret(
            SecretId='sap_cognito_config',
            SecretString=json.dumps(creds)
        )
        
        logger.info("🔄 Refreshed Cognito bearer token")
        return creds
        
    except Exception as e:
        logger.error(f"Failed to refresh Cognito token: {str(e)}")
        raise

def invoke_local_agent(payload):
    """
    Legacy function - now calls AgentCore Strands agent.
    """
    return invoke_agentcore_strands_agent(payload)