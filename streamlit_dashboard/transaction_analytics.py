import streamlit as st
import boto3
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import json
import numpy as np
from typing import Dict, List, Any

# Configure AWS
TABLE_NAME = "invoice-state-dev"
from config import config
REGION = config.AWS_REGION

@st.cache_data(ttl=300)
def get_all_transactions():
    """Fetch all transactions with caching"""
    try:
        dynamodb = boto3.resource("dynamodb", region_name=REGION)
        table = dynamodb.Table(TABLE_NAME)
        
        response = table.scan(Limit=1000)
        items = response["Items"]
        
        while "LastEvaluatedKey" in response and len(items) < 5000:
            response = table.scan(
                ExclusiveStartKey=response["LastEvaluatedKey"],
                Limit=1000
            )
            items.extend(response["Items"])
        
        return items
    except Exception as e:
        st.error(f"Error fetching data: {str(e)}")
        return []

def get_transaction_data(transaction_number):
    """Fetch specific transaction data"""
    try:
        dynamodb = boto3.resource("dynamodb", region_name=REGION)
        table = dynamodb.Table(TABLE_NAME)
        
        response = table.get_item(
            Key={"transaction_number": transaction_number},
            ConsistentRead=True
        )
        return response.get("Item")
    except Exception as e:
        st.error(f"Error fetching transaction: {str(e)}")
        return None

def process_transactions_data(transactions):
    """Process raw transaction data into analytics format"""
    processed = []
    
    for txn in transactions:
        # Parse timestamps and normalize timezone
        created_on = pd.to_datetime(txn.get('created_on', ''), errors='coerce', utc=True)
        last_modified = pd.to_datetime(txn.get('last_modified_at', ''), errors='coerce', utc=True)
        
        # Calculate processing metrics - handle Decimal types from DynamoDB
        processing_time_raw = txn.get('metrics', {}).get('processing_time', '0')
        processing_time = int(float(str(processing_time_raw))) if str(processing_time_raw).replace('.','').isdigit() else 0
        escalation_attempts = int(float(str(txn.get('escalation_attempts', 0))))
        
        # Email metrics
        escalation_history = txn.get('escalation_history', [])
        outbound_emails = len([e for e in escalation_history if e.get('email_type') == 'outbound'])
        inbound_emails = len([e for e in escalation_history if e.get('email_type') == 'inbound'])
        
        # Processing steps
        processing_history = txn.get('processing_history', [])
        total_steps = len(processing_history)
        
        processed.append({
            'transaction_number': txn.get('transaction_number', ''),
            'status': txn.get('status', ''),
            'amount': float(str(txn.get('amount', '0')).replace(',', '')) if txn.get('amount') else 0,
            'currency': txn.get('currency', ''),
            'supplier_number': txn.get('supplier_number', ''),
            'exception_type': txn.get('exception_type', ''),
            'transaction_type': txn.get('transaction_type', ''),
            'auto_resolved': txn.get('auto_resolved', False),
            'requires_human_review': txn.get('requires_human_review', False),
            'created_on': created_on,
            'last_modified_at': last_modified,
            'processing_time_hours': processing_time / 3600 if processing_time > 0 else 0,
            'escalation_attempts': escalation_attempts,
            'outbound_emails': outbound_emails,
            'inbound_emails': inbound_emails,
            'total_emails': outbound_emails + inbound_emails,
            'processing_steps': total_steps,
            'state_version': int(float(str(txn.get('state_version', 0)))),
            'external_reference': txn.get('external_reference', ''),
            'document_date': pd.to_datetime(txn.get('document_date', ''), errors='coerce', utc=True),
            'is_active': txn.get('is_active', True),
            'message_type': txn.get('message_type', ''),
            'max_escalation_rounds': int(float(str(txn.get('max_escalation_rounds', 3))))
        })
    
    return pd.DataFrame(processed)

def create_advanced_filters(df):
    """Create comprehensive filter sidebar"""
    st.sidebar.header("🔍 Advanced Filters")
    
    filters = {}
    
    # Date range filter
    st.sidebar.subheader("📅 Date Range")
    date_col = st.sidebar.selectbox("Date Field", ["created_on", "last_modified_at", "document_date"])
    
    if not df[date_col].isna().all():
        min_date = df[date_col].min().date()
        max_date = df[date_col].max().date()
        
        date_range = st.sidebar.date_input(
            "Select Date Range",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date
        )
        
        if len(date_range) == 2:
            filters['date_range'] = (pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1]))
            filters['date_column'] = date_col
    
    # Status filters
    st.sidebar.subheader("📊 Status & Type")
    status_options = ['All'] + sorted(df['status'].dropna().unique().tolist())
    filters['status'] = st.sidebar.multiselect("Status", status_options)
    
    exception_options = ['All'] + sorted(df['exception_type'].dropna().unique().tolist())
    filters['exception_type'] = st.sidebar.multiselect("Exception Type", exception_options)
    
    # Amount filters
    st.sidebar.subheader("💰 Amount Range")
    if df['amount'].max() > 0:
        amount_range = st.sidebar.slider(
            "Amount Range ($)",
            min_value=float(df['amount'].min()),
            max_value=float(df['amount'].max()),
            value=(float(df['amount'].min()), float(df['amount'].max())),
            format="$%.2f"
        )
        filters['amount_range'] = amount_range
    
    # Processing metrics
    st.sidebar.subheader("⚡ Performance Metrics")
    
    if df['processing_time_hours'].max() > 0:
        time_range = st.sidebar.slider(
            "Processing Time (hours)",
            min_value=0.0,
            max_value=float(df['processing_time_hours'].max()),
            value=(0.0, float(df['processing_time_hours'].max())),
            format="%.1f"
        )
        filters['processing_time_range'] = time_range
    
    escalation_range = st.sidebar.slider(
        "Escalation Attempts",
        min_value=0,
        max_value=int(df['escalation_attempts'].max()) if df['escalation_attempts'].max() > 0 else 5,
        value=(0, int(df['escalation_attempts'].max()) if df['escalation_attempts'].max() > 0 else 5)
    )
    filters['escalation_range'] = escalation_range
    
    # Supplier filter
    st.sidebar.subheader("🏢 Supplier")
    supplier_options = ['All'] + sorted(df['supplier_number'].dropna().unique().tolist())
    filters['suppliers'] = st.sidebar.multiselect("Suppliers", supplier_options)
    
    # Boolean filters
    st.sidebar.subheader("✅ Flags")
    filters['auto_resolved'] = st.sidebar.checkbox("Auto Resolved Only")
    filters['requires_review'] = st.sidebar.checkbox("Requires Human Review")
    filters['is_active'] = st.sidebar.checkbox("Active Only", value=False)
    
    # Advanced text search
    st.sidebar.subheader("🔎 Text Search")
    filters['search_text'] = st.sidebar.text_input("Search in transaction number, reference")
    
    return filters

def apply_filters(df, filters):
    """Apply all filters to dataframe"""
    filtered_df = df.copy()
    
    # Date range filter - only apply if user changed from default range
    if 'date_range' in filters and 'date_column' in filters:
        date_col = filters['date_column']
        start_date, end_date = filters['date_range']
        
        # Check if this is different from the full range
        if not df[date_col].isna().all():
            df_min_date = df[date_col].min().date()
            df_max_date = df[date_col].max().date()
            
            # Only filter if user selected a different range
            if start_date.date() != df_min_date or end_date.date() != df_max_date:
                # Convert to timezone-aware if needed
                if filtered_df[date_col].dt.tz is not None:
                    start_date = pd.Timestamp(start_date).tz_localize('UTC')
                    end_date = pd.Timestamp(end_date).tz_localize('UTC')
                filtered_df = filtered_df[
                    (filtered_df[date_col] >= start_date) & 
                    (filtered_df[date_col] <= end_date)
                ]
    
    # Only apply filters if they are actually selected
    # Status filter
    if filters.get('status'):
        if 'All' not in filters['status']:
            filtered_df = filtered_df[filtered_df['status'].isin(filters['status'])]
    
    # Exception type filter
    if filters.get('exception_type'):
        if 'All' not in filters['exception_type']:
            filtered_df = filtered_df[filtered_df['exception_type'].isin(filters['exception_type'])]
    
    # Amount range - only if different from default
    if 'amount_range' in filters:
        min_amt, max_amt = filters['amount_range']
        df_min, df_max = df['amount'].min(), df['amount'].max()
        if min_amt != df_min or max_amt != df_max:
            filtered_df = filtered_df[
                (filtered_df['amount'] >= min_amt) & 
                (filtered_df['amount'] <= max_amt)
            ]
    
    # Processing time range - only if different from default
    if 'processing_time_range' in filters:
        min_time, max_time = filters['processing_time_range']
        df_min, df_max = 0.0, df['processing_time_hours'].max()
        if min_time != df_min or max_time != df_max:
            filtered_df = filtered_df[
                (filtered_df['processing_time_hours'] >= min_time) & 
                (filtered_df['processing_time_hours'] <= max_time)
            ]
    
    # Escalation range - only if different from default
    if 'escalation_range' in filters:
        min_esc, max_esc = filters['escalation_range']
        df_min = 0
        df_max = int(df['escalation_attempts'].max()) if df['escalation_attempts'].max() > 0 else 5
        if min_esc != df_min or max_esc != df_max:
            filtered_df = filtered_df[
                (filtered_df['escalation_attempts'] >= min_esc) & 
                (filtered_df['escalation_attempts'] <= max_esc)
            ]
    
    # Supplier filter
    if filters.get('suppliers'):
        if 'All' not in filters['suppliers']:
            filtered_df = filtered_df[filtered_df['supplier_number'].isin(filters['suppliers'])]
    
    # Boolean filters - only if checked
    if filters.get('auto_resolved'):
        filtered_df = filtered_df[filtered_df['auto_resolved'] == True]
    
    if filters.get('requires_review'):
        filtered_df = filtered_df[filtered_df['requires_human_review'] == True]
    
    if filters.get('is_active'):
        filtered_df = filtered_df[filtered_df['is_active'] == True]
    
    # Text search
    if filters.get('search_text'):
        search_text = filters['search_text'].lower()
        mask = (
            filtered_df['transaction_number'].str.lower().str.contains(search_text, na=False) |
            filtered_df['external_reference'].str.lower().str.contains(search_text, na=False) |
            filtered_df['supplier_number'].str.lower().str.contains(search_text, na=False)
        )
        filtered_df = filtered_df[mask]
    
    return filtered_df

def create_executive_dashboard(df):
    """Create executive summary dashboard"""
    st.header("📊 Invoice Exceptions Dashboard")
    
    # Key metrics
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric("Total Transactions", len(df))
    with col2:
        resolved_pct = (df['status'] == 'resolved').mean() * 100
        st.metric("Resolution Rate", f"{resolved_pct:.1f}%")
    with col3:
        avg_time = df['processing_time_hours'].mean()
        st.metric("Avg Processing Time", f"{avg_time:.1f}h")
    with col4:
        auto_resolved_pct = df['auto_resolved'].mean() * 100
        st.metric("Auto-Resolution Rate", f"{auto_resolved_pct:.1f}%")
    with col5:
        total_value = df['amount'].sum()
        st.metric("Total Value", f"${total_value:,.0f}")
    
    # Charts row 1
    col1, col2 = st.columns(2)
    
    with col1:
        # Status distribution
        status_counts = df['status'].value_counts()
        fig = px.pie(values=status_counts.values, names=status_counts.index, 
                     title="Transaction Status Distribution")
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        # Processing time distribution
        fig = px.histogram(df, x='processing_time_hours', nbins=20,
                          title="Processing Time Distribution (Hours)")
        fig.update_layout(xaxis_title="Processing Time (Hours)", yaxis_title="Count")
        st.plotly_chart(fig, use_container_width=True)
    
    # Charts row 2
    col1, col2 = st.columns(2)
    
    with col1:
        # Daily transaction volume
        if not df['created_on'].isna().all():
            daily_volume = df.groupby(df['created_on'].dt.date).size().reset_index()
            daily_volume.columns = ['date', 'count']
            fig = px.line(daily_volume, x='date', y='count', 
                         title="Daily Transaction Volume")
            st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        # Exception type analysis
        exception_counts = df['exception_type'].value_counts().head(10)
        fig = px.bar(x=exception_counts.values, y=exception_counts.index, 
                     orientation='h', title="Top Exception Types")
        st.plotly_chart(fig, use_container_width=True)

def create_operational_dashboard(df):
    """Create operational metrics dashboard"""
    st.header("⚙️ Operational Analytics")
    
    # Performance metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        avg_escalations = df['escalation_attempts'].mean()
        st.metric("Avg Escalations", f"{avg_escalations:.1f}")
    with col2:
        email_efficiency = df['total_emails'].sum() / len(df) if len(df) > 0 else 0
        st.metric("Emails per Transaction", f"{email_efficiency:.1f}")
    with col3:
        complex_cases = (df['escalation_attempts'] > 2).sum()
        st.metric("Complex Cases", complex_cases)
    with col4:
        sla_breaches = (df['processing_time_hours'] > 24).sum()
        st.metric("SLA Breaches (>24h)", sla_breaches)
    
    # Advanced charts
    col1, col2 = st.columns(2)
    
    with col1:
        # Escalation vs Processing Time - remove size parameter to avoid negative values
        fig = px.scatter(df, x='escalation_attempts', y='processing_time_hours',
                        color='status',
                        title="Escalation Attempts vs Processing Time",
                        hover_data=['transaction_number', 'amount'])
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        # Supplier performance
        supplier_metrics = df.groupby('supplier_number').agg({
            'processing_time_hours': 'mean',
            'escalation_attempts': 'mean',
            'auto_resolved': 'mean',
            'transaction_number': 'count'
        }).reset_index()
        supplier_metrics = supplier_metrics[supplier_metrics['transaction_number'] >= 3]  # Min 3 transactions
        
        fig = px.scatter(supplier_metrics, x='processing_time_hours', y='escalation_attempts',
                        size='transaction_number', color='auto_resolved',
                        hover_data=['supplier_number'],
                        title="Supplier Performance Matrix",
                        size_max=20)
        st.plotly_chart(fig, use_container_width=True)
    
    # Heatmaps
    col1, col2 = st.columns(2)
    
    with col1:
        # Hour of day analysis
        if not df['created_on'].isna().all():
            hourly_data = df.groupby([df['created_on'].dt.hour, df['status']]).size().unstack(fill_value=0)
            fig = px.imshow(hourly_data.T, title="Transaction Status by Hour of Day",
                           labels=dict(x="Hour", y="Status", color="Count"))
            st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        # Exception type vs Status
        exception_status = pd.crosstab(df['exception_type'], df['status'])
        fig = px.imshow(exception_status, title="Exception Type vs Status Matrix",
                       labels=dict(x="Status", y="Exception Type", color="Count"))
        st.plotly_chart(fig, use_container_width=True)

def create_detailed_transaction_view(df):
    """Create detailed transaction analysis"""
    st.header("🔍 Detailed Transaction Analysis")
    
    # Transaction selector with search - sort by creation date descending
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        df_sorted = df.sort_values('created_on', ascending=False)
        search_txn = st.text_input("Search Transaction Number:", placeholder="Enter transaction number or select from dropdown")
        
        if search_txn:
            # Filter transactions based on search
            matching_txns = df_sorted[df_sorted['transaction_number'].str.contains(search_txn, case=False, na=False)]['transaction_number'].tolist()
            if matching_txns:
                selected_txn = st.selectbox("Matching Transactions:", matching_txns)
            else:
                st.warning(f"No transactions found matching '{search_txn}'")
                selected_txn = None
        else:
            selected_txn = st.selectbox("Select Transaction:", df_sorted['transaction_number'].tolist())
    with col2:
        if st.button("🔄 Refresh Data"):
            st.cache_data.clear()
            st.rerun()
    with col3:
        export_data = st.button("📊 Export Analysis")
    
    if selected_txn:
        # Get detailed transaction data
        txn_data = get_transaction_data(selected_txn)
        if txn_data:
            # Transaction overview
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Status", txn_data.get('status', 'N/A'))
            with col2:
                amount_raw = txn_data.get('amount', '0')
                amount = float(str(amount_raw).replace(',', '')) if amount_raw else 0
                st.metric("Amount", f"${amount:,.2f}")
            with col3:
                escalations = int(txn_data.get('escalation_attempts', 0))
                st.metric("Escalations", escalations)
            with col4:
                metrics = txn_data.get('metrics', {})
                processing_time_raw = metrics.get('processing_time', '0')
                processing_time = int(float(str(processing_time_raw))) if str(processing_time_raw).replace('.','').isdigit() else 0
                hours = processing_time / 3600 if processing_time > 0 else 0
                st.metric("Processing Time", f"{hours:.1f}h")
            

            
            # Complete audit trail combining processing and email history
            st.subheader("📋 Complete Audit Trail")
            
            # Get processing history
            processing_history = txn_data.get('processing_history', [])
            
            # Combine processing and escalation history
            audit_events = []
            
            # Add processing events
            for entry in processing_history:
                audit_events.append({
                    'timestamp': pd.to_datetime(entry['timestamp']),
                    'type': 'processing',
                    'processor': entry['processor'],
                    'action': entry['action'],
                    'result': entry['result'],
                    'details': entry.get('details', {}),
                    'content': f"{entry['processor']}: {entry['action']} → {entry['result']}"
                })
            
            # Add email events
            escalation_history = txn_data.get('escalation_history', [])
            for entry in escalation_history:
                audit_events.append({
                    'timestamp': pd.to_datetime(entry['timestamp']),
                    'type': 'email',
                    'email_type': entry['email_type'],
                    'attempt': entry['attempt_number'],
                    'sender': entry['sender'],
                    'recipient': entry['recipient'],
                    'content': entry['email_content'][:100] + '...' if len(entry['email_content']) > 100 else entry['email_content']
                })
            
            # Sort by timestamp
            audit_events.sort(key=lambda x: x['timestamp'])
            
            if audit_events:
                # Timeline visualization
                audit_df = pd.DataFrame(audit_events)
                fig = px.scatter(audit_df, x='timestamp', y='type',
                               color='type', size_max=15,
                               title="Complete Transaction Timeline",
                               hover_data=['content'])
                st.plotly_chart(fig, use_container_width=True)
                
                # Detailed audit trail
                st.subheader("🔍 Detailed Audit Trail")
                
                for i, event in enumerate(audit_events):
                    with st.container():
                        col1, col2 = st.columns([1, 4])
                        
                        with col1:
                            # Event type icon and timestamp
                            if event['type'] == 'email':
                                icon = "📤" if event.get('email_type') == 'outbound' else "📥"
                                st.write(f"{icon} **Email**")
                            else:
                                st.write("⚙️ **Processing**")
                            
                            st.write(event['timestamp'].strftime("%m/%d %H:%M:%S"))
                        
                        with col2:
                            if event['type'] == 'email':
                                # Email event details
                                st.write(f"**{event['email_type'].title()} Email - Attempt {event['attempt']}**")
                                st.write(f"From: {event['sender']} → To: {event['recipient']}")
                                
                                # Get full content from escalation_history
                                full_entry = next((e for e in escalation_history if e['timestamp'] == event['timestamp'].isoformat()), None)
                                if full_entry:
                                    # Show email content directly (not in expander)
                                    st.write("**📧 Email Content:**")
                                    st.text_area("", full_entry['email_content'], 
                                               height=150, key=f"email_content_{i}", disabled=True)
                            else:
                                # Processing event details
                                st.write(f"**{event['processor']}**: {event['action']} → {event['result']}")
                                
                                # Show processing details if available
                                if event['details']:
                                    with st.expander(f"⚙️ Processing Details - {event['timestamp'].strftime('%H:%M:%S')}"):
                                        st.json(event['details'])
                        
                        st.divider()
            else:
                st.info("No audit trail available for this transaction")
                
                # Debug: Show raw escalation history if no audit events
                if escalation_history:
                    st.write("**Debug - Raw Escalation History:**")
                    for i, entry in enumerate(escalation_history):
                        st.write(f"Entry {i+1}: {entry.get('email_type', 'N/A')} - {entry.get('timestamp', 'N/A')}")
                        if 'email_content' in entry:
                            st.text_area(f"Email {i+1} Content:", entry['email_content'], height=100, key=f"debug_email_{i}")
                        st.divider()

def show_transaction_analytics():
    """Main analytics application"""
    st.set_page_config(
        page_title="SAP Transaction Analytics",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    st.title("📊 SAP Transaction Analytics Platform")
    st.markdown("*Analytics for invoice exception management*")
    
    # Load data
    with st.spinner("Loading transaction data..."):
        raw_transactions = get_all_transactions()
    
    if not raw_transactions:
        st.error("No transaction data available")
        return
    

    
    # Process data
    df = process_transactions_data(raw_transactions)
    
    # Create filters
    filters = create_advanced_filters(df)
    
    # Apply filters
    filtered_df = apply_filters(df, filters)
    
    # Show filter results with details
    if len(filtered_df) < len(df):
        st.warning(f"Showing {len(filtered_df)} of {len(df)} transactions (filters applied)")
        st.write(f"**Filtered out:** {len(df) - len(filtered_df)} transactions")
    else:
        st.info(f"Showing all {len(df)} transactions")
    
    # Dashboard tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Accounts Payable", "⚙️ Operations", "🔍 Detailed", "📋 Data Export"])
    
    with tab1:
        create_executive_dashboard(filtered_df)
    
    with tab2:
        create_operational_dashboard(filtered_df)
    
    with tab3:
        create_detailed_transaction_view(filtered_df)
    
    with tab4:
        st.header("📋 Data Export & Reports")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("📊 Download Filtered Data (CSV)"):
                csv = filtered_df.to_csv(index=False)
                st.download_button("Download CSV", csv, "transactions.csv", "text/csv")
        
        with col2:
            if st.button("📈 Generate Executive Report"):
                st.success("Executive report generated! (Feature coming soon)")
        
        # Data preview
        st.subheader("📋 Filtered Data Preview")
        st.dataframe(
            filtered_df[['transaction_number', 'status', 'amount', 'supplier_number', 
                        'escalation_attempts', 'processing_time_hours', 'created_on']],
            use_container_width=True
        )

if __name__ == "__main__":
    show_transaction_analytics()