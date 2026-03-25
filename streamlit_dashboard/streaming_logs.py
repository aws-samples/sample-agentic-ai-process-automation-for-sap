import streamlit as st
import requests
import time
import re

def show_streaming_logs():
    """Show streaming logs with real-time updates and better UI"""
    st.title("📋 Live Processing Logs")
    
    transaction_id = st.session_state.get('current_transaction', 'Unknown')
    
    # Header with back button
    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("← Back", use_container_width=True):
            st.session_state['show_logs'] = False
            st.rerun()
    with col2:
        st.info(f"🔍 **Transaction:** {transaction_id}")
    
    st.divider()
    
    # Get request data
    agent_url = st.session_state.get('agent_url')
    headers = st.session_state.get('headers')
    payload = st.session_state.get('payload')
    
    if not all([agent_url, headers, payload]):
        st.error("❌ Missing request configuration")
        return
    
    # Status and progress
    status_placeholder = st.empty()
    progress_bar = st.progress(0)
    
    # Content area
    st.markdown("### 🤖 Agent Response")
    content_placeholder = st.empty()
    
    try:
        status_placeholder.info("🚀 Connecting to AgentCore...")
        
        response = requests.post(
            agent_url, 
            headers=headers, 
            json=payload, 
            timeout=180, 
            stream=True
        )
        
        # Handle token expiration
        if response.status_code == 403 and "expired" in response.text.lower():
            status_placeholder.info("🔄 Token expired, refreshing...")
            
            # Import refresh function
            import sys
            import os
            sys.path.append(os.path.dirname(__file__))
            from app import refresh_cognito_token
            
            new_token = refresh_cognito_token()
            if new_token:
                headers["authorization"] = f"Bearer {new_token}"
                response = requests.post(
                    agent_url, 
                    headers=headers, 
                    json=payload, 
                    timeout=180, 
                    stream=True
                )
            else:
                status_placeholder.error("❌ Failed to refresh token")
                return
        
        if response.status_code != 200:
            status_placeholder.error(f"❌ HTTP {response.status_code}")
            content_placeholder.error(response.text[:500])
            return
        
        status_placeholder.success("✅ Streaming response...")
        
        full_response = ""
        chunk_count = 0
        start_time = time.time()
        
        # Handle Server-Sent Events
        if "text/event-stream" in response.headers.get("content-type", ""):
            for line in response.iter_lines(decode_unicode=True):
                if line and line.startswith("data: "):
                    chunk = line[6:].strip()
                    if chunk and chunk != "[DONE]":
                        full_response += chunk + " "
                        chunk_count += 1
                        
                        # Update progress
                        progress = min(chunk_count * 2, 100)
                        progress_bar.progress(progress)
                        
                        # Update content periodically with formatting
                        if chunk_count % 5 == 0:
                            formatted_response = format_streaming_text(full_response)
                            content_placeholder.markdown(
                                f"```\n{formatted_response}\n```",
                                unsafe_allow_html=True
                            )
        else:
            # Regular streaming
            for chunk in response.iter_content(chunk_size=512, decode_unicode=True):
                if chunk:
                    full_response += chunk
                    chunk_count += 1
                    
                    progress = min(chunk_count * 3, 100)
                    progress_bar.progress(progress)
                    
                    formatted_response = format_streaming_text(full_response)
                    content_placeholder.markdown(
                        f"```\n{formatted_response}\n```",
                        unsafe_allow_html=True
                    )
        
        # Final update
        progress_bar.progress(100)
        elapsed_time = time.time() - start_time
        
        status_placeholder.success(f"✅ Completed in {elapsed_time:.1f}s")
        
        # Final formatted response
        if full_response.strip():
            st.markdown("### 📄 Formatted Response")
            final_formatted = format_final_response(full_response)
            st.markdown(final_formatted)
        
    except requests.exceptions.Timeout:
        status_placeholder.error("⏰ Request timed out")
    except Exception as e:
        status_placeholder.error(f"❌ Error: {str(e)}")


def format_streaming_text(text):
    """Format streaming text with proper gaps and structure"""
    if not text:
        return ""
    
    import html
    
    # Decode HTML entities first
    formatted = html.unescape(text)
    formatted = formatted.replace('&quot;', '"').replace('&#39;', "'")
    
    # Convert \n to actual line breaks
    formatted = formatted.replace('\\n', '\n')
    
    # Add line breaks after sentences and tool calls
    formatted = formatted.replace(". ", ".\n\n")
    formatted = formatted.replace("🔧", "\n\n🔧")
    formatted = formatted.replace("✅", "\n\n✅")
    formatted = formatted.replace("❌", "\n\n❌")
    
    # Clean up excessive newlines
    formatted = re.sub(r'\n{4,}', '\n\n\n', formatted)
    
    return formatted.strip()


def format_final_response(text):
    """Format final response with proper sections and readability"""
    if not text:
        return "No response received."
    
    import html
    
    # Decode HTML entities and fix line breaks
    formatted = html.unescape(text)
    formatted = formatted.replace('&quot;', '"').replace('&#39;', "'")
    formatted = formatted.replace('\\n', '\n')
    
    # Split into logical sections
    sections = []
    current_section = []
    
    lines = formatted.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Start new section on tool calls or major transitions
        if any(marker in line for marker in ['🔧', '✅', '❌', 'Based on', 'According to']):
            if current_section:
                sections.append('\n'.join(current_section))
                current_section = []
        
        current_section.append(line)
    
    # Add final section
    if current_section:
        sections.append('\n'.join(current_section))
    
    # Format sections with proper spacing
    formatted_sections = []
    for i, section in enumerate(sections):
        if section.strip():
            formatted_sections.append(f"**Section {i+1}:**\n\n{section}")
    
    return '\n\n---\n\n'.join(formatted_sections)