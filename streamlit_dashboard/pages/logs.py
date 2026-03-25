import streamlit as st
import html
import re
import requests

def clean_agent_response(text):
    """Clean up agent response text for better readability"""
    if not text:
        return "No response received."
    
    # Decode HTML entities
    text = html.unescape(text)
    
    # Remove excessive quotes and escape characters
    text = text.replace('&quot;', '"').replace('&amp;', '&').replace('&#39;', "'")
    text = text.replace('\\"', '"').replace('\\\\n', '\n')
    
    # Clean up excessive quotes
    text = re.sub(r'""([^"]+)""', r'\1', text)
    text = re.sub(r'"([^"]+)"', r'\1', text)
    
    # Fix line breaks
    text = text.replace('\\n', '\n\n')
    
    # Remove excessive newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()

st.set_page_config(
    page_title="Processing Logs",
    page_icon="📋",
    layout="wide"
)

st.title("📋 Processing Logs")

# Get transaction info from session state
transaction_id = st.session_state.get('current_transaction', 'Unknown')
agent_url = st.session_state.get('agent_url')
headers = st.session_state.get('headers')
payload = st.session_state.get('payload')

st.subheader(f"Transaction: {transaction_id}")

# Back button
if st.button("← Back to Dashboard"):
    st.switch_page("app.py")

st.divider()

# Streaming content area
status_container = st.empty()
content_container = st.empty()

if agent_url and headers and payload:
    # Make the streaming request on this page
    try:
        response = requests.post(
            agent_url,
            headers=headers,
            json=payload,
            timeout=180,
            stream=True
        )
        
        if response.status_code == 200:
            status_container.info("🔄 Streaming response...")
            
            full_response = ""
            
            if "text/event-stream" in response.headers.get("content-type", ""):
                # Handle streaming response
                for line in response.iter_lines(decode_unicode=True):
                    if line and line.startswith("data: "):
                        chunk = line[6:]  # Remove "data: " prefix
                        if chunk.strip():
                            full_response += chunk
                            # Update content in real-time
                            cleaned_content = clean_agent_response(full_response)
                            content_container.markdown(f"""
**🤖 Agent Response:**

{cleaned_content}

---
*Last updated: Now*
                            """)
            else:
                # Handle non-streaming response
                full_response = response.text
                cleaned_content = clean_agent_response(full_response)
                content_container.markdown(f"""
**🤖 Agent Response:**

{cleaned_content}

---
*Processing completed*
                """)
            
            status_container.success("✅ Processing completed successfully")
        else:
            status_container.error(f"❌ HTTP Error: {response.status_code}")
            content_container.error(f"Response: {response.text[:500]}...")
            
    except Exception as e:
        status_container.error(f"❌ Connection error: {str(e)}")
        content_container.error("Failed to connect to AgentCore")

else:
    st.warning("No request data available")
    if st.button("Return to Dashboard"):
        st.switch_page("app.py")