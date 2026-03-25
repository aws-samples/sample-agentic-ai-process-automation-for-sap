import json
import os
import boto3
from datetime import datetime
import requests
from botocore.exceptions import ClientError
from decimal import Decimal

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
secrets_client = boto3.client('secretsmanager', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

def lambda_handler(event, context):
    try:
        response = query_odata_api()
        sap_exceptions = response['d']['results']
        
        for exception in sap_exceptions:
            create_or_update_dynamodb_entry(exception)
        
        return {'statusCode': 200, 'body': 'Processing complete'}
    except Exception as error:
        print(f'Error processing exceptions: {error}')
        raise error

def query_odata_api():
    try:
        # Get SAP credentials from Secrets Manager
        response = secrets_client.get_secret_value(SecretId='sap_credentials')
        credentials = json.loads(response['SecretString'])
        sap_username = credentials['username']
        sap_password = credentials['password']
    except Exception as error:
        print(f'Failed to retrieve SAP credentials: {error}')
        raise Exception("SAP credentials must be available in Secrets Manager")
    
    base_url = os.environ['SAP_BASE_URL']
    # Construct full OData endpoint URL
    odata_path = "/sap/opu/odata/sap/FAP_VENDOR_LINE_ITEMS_SRV/Items"
    query_params = "$filter=PaymentBlockingReason ne ''&$format=json&$select=AccountingDocument,AccountingDocumentItem,DocumentDate,DocumentReferenceID,Supplier,AmountInTransactionCurrency,TransactionCurrency,PaymentBlockingReason,ReferenceDocumentTypeName,PostingDate,NetDueDate,OriginalReferenceDocument"
    
    url = f"{base_url}{odata_path}?{query_params}"
    
    response = requests.get(
        url,
        auth=(sap_username, sap_password),
        headers={'Accept': 'application/json'},
        timeout=30
    )
    
    response.raise_for_status()
    return response.json()

def create_or_update_dynamodb_entry(exception):
    timestamp = datetime.utcnow().isoformat()
    
    original_ref = exception.get('OriginalReferenceDocument') or exception.get('AccountingDocument')
    if not original_ref:
        raise Exception('Missing required document reference fields')
    
    transaction_number = original_ref[:-4] if len(original_ref) > 4 else original_ref
    document_date = parse_sap_date(exception.get('DocumentDate'))
    
    table = dynamodb.Table(os.environ['STATE_TABLE'])
    
    # Check if item exists
    try:
        response = table.get_item(Key={'transaction_number': transaction_number})
        existing_item = response.get('Item')
    except Exception:
        existing_item = None
    
    if existing_item:
        current_exception_type = exception.get('PaymentBlockingReason')
        # Convert negative amounts to positive - correcting bad dummy data in SAP
        current_amount = Decimal(str(abs(float(exception.get('AmountInTransactionCurrency', 0)))))
        
        if (existing_item.get('exception_type') != current_exception_type or 
            existing_item.get('amount') != current_amount):
            
            updated_history = existing_item.get('processing_history', [])
            updated_history.append({
                'processor': 'ODataPoller',
                'action': 'update',
                'timestamp': timestamp,
                'result': 'pending',
                'details': {
                    'changes': {
                        'exception_type': {
                            'from': existing_item.get('exception_type'),
                            'to': current_exception_type
                        } if existing_item.get('exception_type') != current_exception_type else None,
                        'amount': {
                            'from': existing_item.get('amount'),
                            'to': current_amount
                        } if existing_item.get('amount') != current_amount else None
                    }
                }
            })
            
            table.update_item(
                Key={'transaction_number': transaction_number},
                UpdateExpression='SET exception_type = :et, amount = :amt, last_modified_at = :lm, processing_history = :ph, #ts = :ts, document_date = :dd',
                ExpressionAttributeNames={'#ts': 'timestamp'},
                ExpressionAttributeValues={
                    ':et': current_exception_type,
                    ':amt': current_amount,
                    ':lm': timestamp,
                    ':ph': updated_history,
                    ':ts': timestamp,
                    ':dd': document_date
                }
            )
        return
    
    # Create new item
    new_item = {
        'transaction_number': transaction_number,
        'document_date': document_date,
        'status': 'pending',
        'message_type': 'INVOICE_EXCEPTION',
        'exception_type': exception.get('PaymentBlockingReason'),
        'transaction_type': exception.get('ReferenceDocumentTypeName', 'INVOICE'),
        'supplier_number': exception.get('Supplier'),
        # Convert negative amounts to positive - correcting bad dummy data in SAP
        'amount': Decimal(str(abs(float(exception.get('AmountInTransactionCurrency', 0))))),
        'currency': exception.get('TransactionCurrency'),
        'external_reference': exception.get('DocumentReferenceID'),
        'created_on': timestamp,
        'timestamp': timestamp,
        'state_version': 1,
        'processing_history': [{
            'processor': 'ODataPoller',
            'action': 'create',
            'timestamp': timestamp,
            'result': 'pending',
            'details': {'initialState': True}
        }],
        'auto_resolved': False,
        'is_active': True,
        'requires_human_review': False,
        'last_modified_at': timestamp,
        'metrics': {'processing_time': '0', 'retryCount': '0'},
        'escalation_history': [],
        'escalation_attempts': 0,
        'max_escalation_rounds': 3,
        'ttl': int(datetime.utcnow().timestamp()) + (90 * 24 * 60 * 60)  # 90 days TTL
    }
    
    table.put_item(Item=new_item)

def parse_sap_date(sap_date_string):
    if isinstance(sap_date_string, str) and sap_date_string.startswith('/Date(') and sap_date_string.endswith(')/'):
        timestamp = int(sap_date_string[6:-2])
        return datetime.fromtimestamp(timestamp / 1000).isoformat()
    
    if isinstance(sap_date_string, str) and 'T' in sap_date_string:
        return sap_date_string
    
    if isinstance(sap_date_string, (int, float)):
        return datetime.fromtimestamp(sap_date_string / 1000).isoformat()
    
    print(f'Unable to parse SAP date: {sap_date_string}, using current timestamp')
    return datetime.utcnow().isoformat()