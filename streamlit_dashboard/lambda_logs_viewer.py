import streamlit as st
import boto3
import json
from datetime import datetime, timedelta
import time
from config import config

def show_lambda_logs_viewer():
    """Show real-time Lambda and AgentCore logs viewer"""
    st.title("📋 Lambda Email Processing Logs")
    
    # Header with refresh controls
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        if st.button("← Back to Dashboard", use_container_width=True):
            st.session_state['show_lambda_logs'] = False
            st.rerun()
    with col2:
        auto_refresh = st.checkbox("Auto-refresh (10s)", value=True)
    with col3:
        if st.button("🔄 Refresh", use_container_width=True):
            st.rerun()
    
    st.divider()
    
    # Time range selector
    col1, col2 = st.columns(2)
    with col1:
        time_range = st.selectbox(
            "Time Range",
            ["Last 5 minutes", "Last 15 minutes", "Last 30 minutes", "Last 1 hour"],
            index=1
        )
    with col2:
        log_level = st.selectbox(
            "Log Level",
            ["All", "INFO", "ERROR", "DEBUG"],
            index=0
        )
    
    # Calculate time range
    time_ranges = {
        "Last 5 minutes": 5,
        "Last 15 minutes": 15,
        "Last 30 minutes": 30,
        "Last 1 hour": 60
    }
    minutes = time_ranges[time_range]
    start_time = datetime.now() - timedelta(minutes=minutes)
    
    # Create tabs for different log sources
    tab1, tab2, tab3 = st.tabs(["🔥 Lambda Logs", "🤖 Strands Agent Logs", "🔧 MCP Server Logs"])
    
    with tab1:
        show_lambda_function_logs(start_time, log_level)
    
    with tab2:
        show_agentcore_logs("strands", start_time, log_level)
    
    with tab3:
        show_agentcore_logs("mcp", start_time, log_level)
    
    # Auto-refresh functionality
    if auto_refresh:
        time.sleep(10)
        st.rerun()

def show_lambda_function_logs(start_time, log_level):
    """Show Lambda function logs"""
    st.subheader("📧 S3 Email Processor Lambda")
    
    try:
        logs_client = boto3.client('logs', region_name=config.AWS_REGION)
        
        # Query Lambda logs - try both possible log groups
        log_groups_to_try = ['/aws/lambda/sap-email-processor', '/aws/lambda/s3-email-processor-dev']
        
        events = []
        for log_group in log_groups_to_try:
            try:
                response = logs_client.filter_log_events(
                    logGroupName=log_group,
                    startTime=int(start_time.timestamp() * 1000),
                    endTime=int(datetime.now().timestamp() * 1000)
                )
                events.extend(response.get('events', []))
                st.info(f"📍 Found logs in: `{log_group}`")
                break
            except logs_client.exceptions.ResourceNotFoundException:
                continue
        
        if not events:
            st.warning("No Lambda log groups found. Tried: " + ", ".join(log_groups_to_try))
            return
        
        # Events were already fetched above
        if not events:
            st.info("No Lambda logs found in the selected time range")
            return
        
        st.success(f"Found {len(events)} log entries")
        
        # Filter by log level if specified
        if log_level != "All":
            events = [e for e in events if log_level in e.get('message', '')]
        
        # Display logs in reverse chronological order
        for event in reversed(events[-50:]):  # Show last 50 entries
            timestamp = datetime.fromtimestamp(event['timestamp'] / 1000)
            message = event['message'].strip()
            
            # Color code based on content
            if any(keyword in message for keyword in ['ERROR', '❌', 'Failed']):
                st.error(f"**{timestamp.strftime('%H:%M:%S')}** - {message}")
            elif any(keyword in message for keyword in ['🚀', '✅', 'SUCCESS', 'Successful']):
                st.success(f"**{timestamp.strftime('%H:%M:%S')}** - {message}")
            elif any(keyword in message for keyword in ['🎯', '📄', 'INFO']):
                st.info(f"**{timestamp.strftime('%H:%M:%S')}** - {message}")
            else:
                st.text(f"{timestamp.strftime('%H:%M:%S')} - {message}")
    
    except Exception as e:
        st.error(f"Error fetching Lambda logs: {str(e)}")

def show_agentcore_logs(agent_type, start_time, log_level):
    """Show AgentCore logs for Strands agent or MCP server"""
    agent_name = "Strands Agent" if agent_type == "strands" else "MCP Server"
    st.subheader(f"🤖 {agent_name}")
    
    try:
        ssm_client = boto3.client('ssm', region_name=config.AWS_REGION)
        logs_client = boto3.client('logs', region_name=config.AWS_REGION)
        
        # Get agent ARN from SSM
        param_name = f'/sap_{agent_type}_agent/runtime/agent_arn' if agent_type == 'strands' else '/sap_mcp_server/runtime/agent_arn'
        
        with st.spinner(f"Getting {agent_name} ARN..."):
            try:
                agent_arn = ssm_client.get_parameter(Name=param_name)['Parameter']['Value']
                
                # Extract agent ID from ARN for log group name
                agent_id = agent_arn.split('/')[-1]
                log_group = f'/aws/bedrock-agentcore/runtime/{agent_id}'
                
                st.info(f"📍 Log Group: `{log_group}`")
                
            except ssm_client.exceptions.ParameterNotFound:
                st.warning(f"Agent ARN not found in SSM parameter: {param_name}")
                return
        
        with st.spinner(f"Fetching {agent_name} logs..."):
            try:
                response = logs_client.filter_log_events(
                    logGroupName=log_group,
                    startTime=int(start_time.timestamp() * 1000),
                    endTime=int(datetime.now().timestamp() * 1000)
                )
                
                events = response.get('events', [])
                
            except logs_client.exceptions.ResourceNotFoundException:
                st.warning(f"Log group not found: {log_group}")
                st.info("This might mean the agent hasn't been invoked yet or logs haven't been created.")
                return
        
        if not events:
            st.info(f"No {agent_name} logs found in the selected time range")
            return
        
        st.success(f"Found {len(events)} log entries")
        
        # Filter by log level if specified
        if log_level != "All":
            events = [e for e in events if log_level in e.get('message', '')]
        
        # Display logs with enhanced formatting for MCP server actions
        for event in reversed(events[-50:]):  # Show last 50 entries
            timestamp = datetime.fromtimestamp(event['timestamp'] / 1000)
            message = event['message'].strip()
            
            # Enhanced formatting for MCP server tool calls
            if agent_type == "mcp" and any(keyword in message for keyword in ['SAP OData API', 'DynamoDB', 'SES', 'Bedrock']):
                st.info(f"**{timestamp.strftime('%H:%M:%S')}** 🔧 **MCP Tool**: {message}")
            elif any(keyword in message for keyword in ['ERROR', '❌', 'Failed']):
                st.error(f"**{timestamp.strftime('%H:%M:%S')}** - {message}")
            elif any(keyword in message for keyword in ['🚀', '✅', 'SUCCESS', 'Successful']):
                st.success(f"**{timestamp.strftime('%H:%M:%S')}** - {message}")
            elif any(keyword in message for keyword in ['🎯', '📄', 'INFO']):
                st.info(f"**{timestamp.strftime('%H:%M:%S')}** - {message}")
            else:
                st.text(f"{timestamp.strftime('%H:%M:%S')} - {message}")
    
    except Exception as e:
        st.error(f"Error fetching {agent_name} logs: {str(e)}")

def get_recent_lambda_executions():
    """Get recent Lambda execution summaries"""
    try:
        logs_client = boto3.client('logs', region_name=config.AWS_REGION)
        
        # Get logs from last hour
        start_time = datetime.now() - timedelta(hours=1)
        
        response = logs_client.filter_log_events(
            logGroupName='/aws/lambda/sap-email-processor',
            startTime=int(start_time.timestamp() * 1000),
            filterPattern='[timestamp, requestId="START", ...]'
        )
        
        executions = []
        for event in response.get('events', []):
            if 'START RequestId:' in event['message']:
                timestamp = datetime.fromtimestamp(event['timestamp'] / 1000)
                request_id = event['message'].split('RequestId: ')[1].split(' ')[0]
                executions.append({
                    'timestamp': timestamp,
                    'request_id': request_id
                })
        
        return executions[-10:]  # Return last 10 executions
        
    except Exception as e:
        st.error(f"Error getting Lambda executions: {str(e)}")
        return []