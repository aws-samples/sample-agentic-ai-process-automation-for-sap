import boto3
import streamlit as st
from datetime import datetime, timedelta
import json

def show_agentcore_logs_viewer():
    """Show AgentCore runtime logs viewer"""
    st.title("🔍 AgentCore Runtime Logs")
    
    # Back button
    if st.button("← Back to Dashboard"):
        st.session_state['show_agentcore_logs'] = False
        st.rerun()
    
    # Log source selection
    col1, col2 = st.columns(2)
    with col1:
        log_source = st.selectbox(
            "Select Log Source:",
            ["Strands Agent", "MCP Server"],
            key="agentcore_log_source"
        )
    
    with col2:
        time_range = st.selectbox(
            "Time Range:",
            ["Last 10 minutes", "Last 30 minutes", "Last 1 hour", "Last 2 hours"],
            key="agentcore_time_range"
        )
    
    # Map selections to log groups
    if log_source == "Strands Agent":
        log_group = "/aws/bedrock-agentcore/runtimes/sap_strands_agent-sL8nKv3Zvs-DEFAULT"
    else:
        log_group = "/aws/bedrock-agentcore/runtimes/sap_mcp_server-k3GSC92W5n-DEFAULT"
    
    # Map time range
    time_map = {
        "Last 10 minutes": "10m",
        "Last 30 minutes": "30m", 
        "Last 1 hour": "1h",
        "Last 2 hours": "2h"
    }
    since_time = time_map[time_range]
    
    # Auto-refresh toggle
    auto_refresh = st.checkbox("Auto-refresh (30s)", value=True)
    
    # Manual refresh button
    if st.button("🔄 Refresh Logs"):
        st.rerun()
    
    # Fetch and display logs
    try:
        logs_client = boto3.client('logs', region_name=config.AWS_REGION)
        
        with st.spinner(f"Fetching {log_source} logs..."):
            # Get log events
            response = logs_client.filter_log_events(
                logGroupName=log_group,
                startTime=int((datetime.now() - timedelta(hours=2)).timestamp() * 1000),
                endTime=int(datetime.now().timestamp() * 1000),
                limit=100
            )
            
            events = response.get('events', [])
            
        if events:
            st.success(f"Found {len(events)} log entries")
            
            # Display logs in reverse chronological order
            for event in reversed(events[-50:]):  # Show last 50 events
                timestamp = datetime.fromtimestamp(event['timestamp'] / 1000)
                message = event['message']
                
                # Color code based on log level
                if 'ERROR' in message:
                    st.error(f"**{timestamp.strftime('%H:%M:%S')}** - {message}")
                elif 'WARNING' in message or 'WARN' in message:
                    st.warning(f"**{timestamp.strftime('%H:%M:%S')}** - {message}")
                elif 'INFO' in message and any(keyword in message for keyword in ['SAP OData', 'Sending escalation', 'Processing request']):
                    st.info(f"**{timestamp.strftime('%H:%M:%S')}** - {message}")
                else:
                    st.text(f"{timestamp.strftime('%H:%M:%S')} - {message}")
                    
        else:
            st.info("No recent log entries found")
            
    except Exception as e:
        st.error(f"Error fetching logs: {e}")
    
    # Auto-refresh
    if auto_refresh:
        import time
        time.sleep(30)
        st.rerun()