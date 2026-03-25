#!/usr/bin/env python3
"""
SAP Invoice Exception Handling - Deployment Script

This script deploys all AWS infrastructure for the SAP Invoice Exception Handling system.
It uses SSM Parameter Store for configuration and Secrets Manager for sensitive data.

All resource creation is idempotent - resources are created if they don't exist,
updated if they do, or skipped if no changes are needed.
"""

import os
import sys
import json
import subprocess

# Install required dependencies first
print("📦 Installing required dependencies...")
required_packages = [
    'boto3',
    'python-dotenv',
    'bedrock-agentcore-starter-toolkit',
    'strands-agents',
    'requests'
]

for package in required_packages:
    try:
        subprocess.run(
            [sys.executable, '-m', 'pip', 'install', '--quiet', package],
            check=True,
            capture_output=True
        )
    except subprocess.CalledProcessError as e:
        print(f"  ⚠️  Warning: Could not install {package}: {e}")

print("  ✅ Dependencies installed\n")

import boto3
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# AWS clients
session = boto3.Session(region_name=os.getenv('AWS_REGION', 'us-east-1'))
s3 = session.client('s3')
dynamodb = session.client('dynamodb')
secretsmanager = session.client('secretsmanager')
ssm = session.client('ssm')
sts = session.client('sts')

# Get AWS account ID
account_id = sts.get_caller_identity()['Account']

def get_config(key, default=None):
    """Get configuration value from environment or use default."""
    value = os.getenv(key)
    if value:
        return value
    if default:
        # Replace {account_id} and {environment} in defaults
        default = default.replace('{account_id}', account_id)
        default = default.replace('{environment}', os.getenv('ENVIRONMENT', 'dev'))
        return default
    return None

def validate_required_config():
    """Validate that all required configuration is present."""
    required = ['AWS_REGION', 'AWS_ACCOUNT_ID', 'SAP_BASE_URL', 'SAP_USERNAME', 'SAP_PASSWORD']
    missing = [key for key in required if not os.getenv(key)]
    
    if missing:
        print(f"❌ Missing required environment variables: {', '.join(missing)}")
        print("Please copy .env.example to .env and fill in the required values.")
        sys.exit(1)
    
    print("✅ Configuration validated")

def store_ssm_parameter(name, value, description=""):
    """Store a parameter in SSM Parameter Store (idempotent)."""
    try:
        ssm.put_parameter(
            Name=name,
            Value=value,
            Description=description,
            Type='String',
            Overwrite=True
        )
        print(f"  ✅ Stored SSM parameter: {name}")
    except Exception as e:
        print(f"  ❌ Failed to store SSM parameter {name}: {e}")
        raise

def get_ssm_parameter(name):
    """Retrieve a parameter from SSM Parameter Store."""
    try:
        response = ssm.get_parameter(Name=name)
        return response['Parameter']['Value']
    except ssm.exceptions.ParameterNotFound:
        raise Exception(f"Parameter {name} not found in SSM")
    except Exception as e:
        raise Exception(f"Failed to retrieve SSM parameter {name}: {e}")

def create_s3_bucket(bucket_name, description):
    """Create S3 bucket with versioning (idempotent)."""
    try:
        # Check if bucket exists
        try:
            s3.head_bucket(Bucket=bucket_name)
            print(f"  ℹ️  Bucket already exists: {bucket_name}")
            
            # Update versioning if needed
            s3.put_bucket_versioning(
                Bucket=bucket_name,
                VersioningConfiguration={'Status': 'Enabled'}
            )
            print(f"  ✅ Versioning enabled on: {bucket_name}")
            
        except s3.exceptions.ClientError as e:
            if e.response['Error']['Code'] == '404':
                # Bucket doesn't exist, create it
                region = os.getenv('AWS_REGION', 'us-east-1')
                
                if region == 'us-east-1':
                    s3.create_bucket(Bucket=bucket_name)
                else:
                    s3.create_bucket(
                        Bucket=bucket_name,
                        CreateBucketConfiguration={'LocationConstraint': region}
                    )
                
                print(f"  ✅ Created bucket: {bucket_name}")
                
                # Enable versioning
                s3.put_bucket_versioning(
                    Bucket=bucket_name,
                    VersioningConfiguration={'Status': 'Enabled'}
                )
                print(f"  ✅ Versioning enabled on: {bucket_name}")
            else:
                raise
        
        # Store bucket name in SSM Parameter Store
        param_name = f"/sap-invoice-exception/s3/{description}"
        store_ssm_parameter(param_name, bucket_name, f"S3 bucket for {description}")
        
        return bucket_name
        
    except Exception as e:
        print(f"  ❌ Failed to create bucket {bucket_name}: {e}")
        raise

def create_secret(secret_name, secret_value, description):
    """Create or update secret in Secrets Manager (idempotent)."""
    try:
        # Try to describe the secret
        try:
            secretsmanager.describe_secret(SecretId=secret_name)
            print(f"  ℹ️  Secret already exists: {secret_name}")
            
            # Update the secret value
            secretsmanager.put_secret_value(
                SecretId=secret_name,
                SecretString=secret_value
            )
            print(f"  ✅ Updated secret: {secret_name}")
            
        except secretsmanager.exceptions.ResourceNotFoundException:
            # Secret doesn't exist, create it
            response = secretsmanager.create_secret(
                Name=secret_name,
                Description=description,
                SecretString=secret_value
            )
            print(f"  ✅ Created secret: {secret_name}")
        
        # Get secret ARN and store in SSM
        secret_info = secretsmanager.describe_secret(SecretId=secret_name)
        secret_arn = secret_info['ARN']
        
        param_name = f"/sap-invoice-exception/secrets/{secret_name.split('/')[-1]}-arn"
        store_ssm_parameter(param_name, secret_arn, f"ARN for {secret_name}")
        
        return secret_arn
        
    except Exception as e:
        print(f"  ❌ Failed to create/update secret {secret_name}: {e}")
        raise

def create_dynamodb_table(table_name):
    """Create DynamoDB table with single key (idempotent)."""
    try:
        # Check if table exists
        try:
            dynamodb.describe_table(TableName=table_name)
            print(f"  ℹ️  Table already exists: {table_name}")
            
            # Update TTL if needed
            try:
                dynamodb.update_time_to_live(
                    TableName=table_name,
                    TimeToLiveSpecification={
                        'Enabled': True,
                        'AttributeName': 'ttl'
                    }
                )
                print(f"  ✅ TTL enabled on: {table_name}")
            except Exception as e:
                if 'TimeToLive is already enabled' in str(e):
                    print(f"  ℹ️  TTL already enabled on: {table_name}")
                else:
                    raise
            
        except dynamodb.exceptions.ResourceNotFoundException:
            # Table doesn't exist, create it with single key
            dynamodb.create_table(
                TableName=table_name,
                KeySchema=[
                    {'AttributeName': 'transaction_number', 'KeyType': 'HASH'}
                ],
                AttributeDefinitions=[
                    {'AttributeName': 'transaction_number', 'AttributeType': 'S'},
                    {'AttributeName': 'status', 'AttributeType': 'S'}
                ],
                GlobalSecondaryIndexes=[
                    {
                        'IndexName': 'status-index',
                        'KeySchema': [
                            {'AttributeName': 'status', 'KeyType': 'HASH'}
                        ],
                        'Projection': {'ProjectionType': 'ALL'},
                        'ProvisionedThroughput': {
                            'ReadCapacityUnits': 5,
                            'WriteCapacityUnits': 5
                        }
                    }
                ],
                ProvisionedThroughput={
                    'ReadCapacityUnits': 5,
                    'WriteCapacityUnits': 5
                }
            )
            print(f"  ✅ Created table with single key (transaction_number): {table_name}")
            
            # Wait for table to be active
            print(f"  ⏳ Waiting for table to be active...")
            waiter = dynamodb.get_waiter('table_exists')
            waiter.wait(TableName=table_name)
            print(f"  ✅ Table is active: {table_name}")
            
            # Enable TTL
            dynamodb.update_time_to_live(
                TableName=table_name,
                TimeToLiveSpecification={
                    'Enabled': True,
                    'AttributeName': 'ttl'
                }
            )
            print(f"  ✅ TTL enabled on: {table_name}")
        
        # Store table name in SSM
        param_name = "/sap-invoice-exception/dynamodb/state-table"
        store_ssm_parameter(param_name, table_name, "DynamoDB table for invoice exception state")
        
        return table_name
        
    except Exception as e:
        print(f"  ❌ Failed to create table {table_name}: {e}")
        raise

def upload_files_to_s3(bucket_name, local_dir, prefix=""):
    """Upload all files from local directory to S3."""
    import os
    uploaded_files = []
    
    if not os.path.exists(local_dir):
        print(f"  ⚠️  Directory not found: {local_dir}")
        return uploaded_files
    
    for filename in os.listdir(local_dir):
        if filename.startswith('.'):
            continue
        
        filepath = os.path.join(local_dir, filename)
        if os.path.isfile(filepath):
            s3_key = f"{prefix}{filename}" if prefix else filename
            try:
                s3.upload_file(filepath, bucket_name, s3_key)
                uploaded_files.append(filename)
                print(f"    ✅ Uploaded: {filename}")
            except Exception as e:
                print(f"    ❌ Failed to upload {filename}: {e}")
    
    return uploaded_files

def create_knowledge_base(kb_name, bucket_name, description):
    """Create Bedrock Knowledge Base with OpenSearch Serverless (idempotent)."""
    import time
    
    bedrock_agent = session.client('bedrock-agent')
    aoss = session.client('opensearchserverless')
    iam = session.client('iam')
    
    try:
        # Check if KB already exists
        try:
            kbs = bedrock_agent.list_knowledge_bases()
            existing_kb = next((kb for kb in kbs.get('knowledgeBaseSummaries', []) 
                              if kb['name'] == kb_name), None)
            
            if existing_kb:
                kb_id = existing_kb['knowledgeBaseId']
                print(f"  ℹ️  Knowledge Base already exists: {kb_name} ({kb_id})")
                return kb_id
        except Exception as e:
            print(f"  ℹ️  Checking existing KBs: {e}")
        
        # Create OpenSearch Serverless collection
        collection_name = kb_name.lower().replace('_', '-').replace(' ', '-')
        print(f"  📦 Creating OpenSearch Serverless collection: {collection_name}")
        
        try:
            collection_response = aoss.create_collection(
                name=collection_name,
                type='VECTORSEARCH',
                description=f"Vector store for {kb_name}"
            )
            collection_id = collection_response['createCollectionDetail']['id']
            print(f"    ✅ Collection created: {collection_id}")
            
            # Wait for collection to be active
            print(f"    ⏳ Waiting for collection to be active...")
            time.sleep(30)  # OpenSearch Serverless takes time to provision
            
        except aoss.exceptions.ConflictException:
            print(f"    ℹ️  Collection already exists: {collection_name}")
            collections = aoss.list_collections(collectionFilters={'name': collection_name})
            collection_id = collections['collectionSummaries'][0]['id']
        
        # Create IAM role for Knowledge Base
        role_name = f"AmazonBedrockExecutionRoleForKnowledgeBase_{kb_name.replace(' ', '_')}"
        
        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "bedrock.amazonaws.com"},
                "Action": "sts:AssumeRole"
            }]
        }
        
        try:
            role_response = iam.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=str(trust_policy).replace("'", '"'),
                Description=f"Execution role for Bedrock Knowledge Base {kb_name}"
            )
            role_arn = role_response['Role']['Arn']
            print(f"    ✅ IAM role created: {role_name}")
            
            # Attach policies
            iam.attach_role_policy(
                RoleName=role_name,
                PolicyArn='arn:aws:iam::aws:policy/AmazonBedrockFullAccess'
            )
            
            time.sleep(10)  # Wait for role to propagate
            
        except iam.exceptions.EntityAlreadyExistsException:
            role_response = iam.get_role(RoleName=role_name)
            role_arn = role_response['Role']['Arn']
            print(f"    ℹ️  IAM role already exists: {role_name}")
        
        # Create Knowledge Base
        print(f"  🧠 Creating Bedrock Knowledge Base: {kb_name}")
        
        kb_config = {
            'type': 'VECTOR',
            'vectorKnowledgeBaseConfiguration': {
                'embeddingModelArn': f'arn:aws:bedrock:{os.getenv("AWS_REGION")}::foundation-model/amazon.titan-embed-text-v2:0'
            }
        }
        
        storage_config = {
            'type': 'OPENSEARCH_SERVERLESS',
            'opensearchServerlessConfiguration': {
                'collectionArn': f'arn:aws:aoss:{os.getenv("AWS_REGION")}:{account_id}:collection/{collection_id}',
                'vectorIndexName': 'bedrock-knowledge-base-default-index',
                'fieldMapping': {
                    'vectorField': 'bedrock-knowledge-base-default-vector',
                    'textField': 'AMAZON_BEDROCK_TEXT_CHUNK',
                    'metadataField': 'AMAZON_BEDROCK_METADATA'
                }
            }
        }
        
        kb_response = bedrock_agent.create_knowledge_base(
            name=kb_name,
            description=description,
            roleArn=role_arn,
            knowledgeBaseConfiguration=kb_config,
            storageConfiguration=storage_config
        )
        
        kb_id = kb_response['knowledgeBase']['knowledgeBaseId']
        print(f"    ✅ Knowledge Base created: {kb_id}")
        
        # Create Data Source
        print(f"  📂 Creating S3 data source...")
        
        ds_response = bedrock_agent.create_data_source(
            knowledgeBaseId=kb_id,
            name=f"{kb_name}-s3-source",
            description=f"S3 data source for {kb_name}",
            dataSourceConfiguration={
                'type': 'S3',
                's3Configuration': {
                    'bucketArn': f'arn:aws:s3:::{bucket_name}'
                }
            }
        )
        
        ds_id = ds_response['dataSource']['dataSourceId']
        print(f"    ✅ Data source created: {ds_id}")
        
        # Start ingestion job
        print(f"  🔄 Starting ingestion job...")
        bedrock_agent.start_ingestion_job(
            knowledgeBaseId=kb_id,
            dataSourceId=ds_id
        )
        print(f"    ✅ Ingestion job started")
        
        return kb_id, ds_id
        
    except Exception as e:
        print(f"  ❌ Failed to create Knowledge Base: {e}")
        raise

def deploy_phase_3_knowledge_bases():
    """Phase 3: Create Bedrock Knowledge Bases."""
    print("\n" + "=" * 80)
    print("PHASE 3: Creating Bedrock Knowledge Bases")
    print("=" * 80)
    print()
    
    # Get bucket names from SSM
    sop_bucket = ssm.get_parameter(Name='/sap-invoice-exception/s3/sops-bucket')['Parameter']['Value']
    api_docs_bucket = ssm.get_parameter(Name='/sap-invoice-exception/s3/api-docs-bucket')['Parameter']['Value']
    
    # Upload SOP files
    print("📤 Uploading SOP documents to S3...")
    sop_files = upload_files_to_s3(sop_bucket, 'sops')
    print(f"  ✅ Uploaded {len(sop_files)} SOP files")
    print()
    
    # Upload SAP API docs
    print("📤 Uploading SAP API documentation to S3...")
    api_files = upload_files_to_s3(api_docs_bucket, 'sap-api-docs')
    print(f"  ✅ Uploaded {len(api_files)} API documentation files")
    print()
    
    # Create SOP Knowledge Base
    print("🧠 Creating SOP Knowledge Base...")
    kb_sop_id, ds_sop_id = create_knowledge_base(
        'sap_invoice_exception_sops',
        sop_bucket,
        'Standard Operating Procedures for SAP Invoice Exception Handling Processing'
    )
    store_ssm_parameter('/sap-invoice-exception/bedrock/sops-kb-id', kb_sop_id, 'SOP Knowledge Base ID')
    store_ssm_parameter('/sap-invoice-exception/bedrock/sops-ds-id', ds_sop_id, 'SOP Data Source ID')
    print()
    
    # Create API Docs Knowledge Base
    print("🧠 Creating SAP API Documentation Knowledge Base...")
    kb_api_id, ds_api_id = create_knowledge_base(
        'sap_invoice_exception_api_docs',
        api_docs_bucket,
        'SAP API Documentation for Invoice Exception Handling Processing'
    )
    store_ssm_parameter('/sap-invoice-exception/bedrock/api-docs-kb-id', kb_api_id, 'API Docs Knowledge Base ID')
    store_ssm_parameter('/sap-invoice-exception/bedrock/api-docs-ds-id', ds_api_id, 'API Docs Data Source ID')
    print()
    
    print("✅ Phase 3 Complete: Knowledge Bases created")
    print()
    print("📋 Resources Created:")
    print(f"  • OpenSearch Collection: sap-invoice-exception-sops")
    print(f"  • Knowledge Base: sap_invoice_exception_sops ({kb_sop_id})")
    print(f"  • OpenSearch Collection: sap-invoice-exception-api-docs")
    print(f"  • Knowledge Base: sap_invoice_exception_api_docs ({kb_api_id})")
    print(f"  • SSM Parameters: /sap-invoice-exception/bedrock/*")
    print()
    print("🔍 Please verify in AWS Console:")
    print("  1. Go to Bedrock > Knowledge bases")
    print("  2. Verify both knowledge bases exist and ingestion jobs completed")
    print("  3. Go to OpenSearch Service > Serverless collections")
    print("  4. Verify both collections are active")
    print()

def upload_files_to_s3(local_dir, bucket_name, prefix=""):
    """Upload all files from local directory to S3."""
    import glob
    
    files_uploaded = []
    for filepath in glob.glob(f"{local_dir}/*"):
        if os.path.isfile(filepath):
            filename = os.path.basename(filepath)
            s3_key = f"{prefix}{filename}" if prefix else filename
            
            try:
                s3.upload_file(filepath, bucket_name, s3_key)
                print(f"    ✅ Uploaded: {filename}")
                files_uploaded.append(filename)
            except Exception as e:
                print(f"    ❌ Failed to upload {filename}: {e}")
    
    return files_uploaded

def create_knowledge_base(kb_name, description, bucket_name, embedding_model="amazon.titan-embed-text-v2:0"):
    """Create Bedrock Knowledge Base with OpenSearch Serverless (idempotent)."""
    bedrock_agent = session.client('bedrock-agent')
    aoss = session.client('opensearchserverless')
    iam = session.client('iam')
    
    try:
        # Check if KB already exists
        try:
            kbs = bedrock_agent.list_knowledge_bases()
            for kb in kbs.get('knowledgeBaseSummaries', []):
                if kb['name'] == kb_name:
                    print(f"  ℹ️  Knowledge Base already exists: {kb_name}")
                    kb_id = kb['knowledgeBaseId']
                    
                    # Sync the data source
                    data_sources = bedrock_agent.list_data_sources(knowledgeBaseId=kb_id)
                    if data_sources.get('dataSourceSummaries'):
                        ds_id = data_sources['dataSourceSummaries'][0]['dataSourceId']
                        print(f"  🔄 Syncing data source...")
                        bedrock_agent.start_ingestion_job(
                            knowledgeBaseId=kb_id,
                            dataSourceId=ds_id
                        )
                        print(f"  ✅ Data source sync started")
                    
                    return kb_id
        except Exception as e:
            print(f"  ℹ️  No existing KB found, will create new one")
        
        # Create OpenSearch Serverless collection
        collection_name = kb_name.replace('_', '-').lower()
        print(f"  📦 Creating OpenSearch Serverless collection: {collection_name}")
        
        try:
            collection = aoss.create_collection(
                name=collection_name,
                type='VECTORSEARCH',
                description=f"Vector store for {kb_name}"
            )
            collection_id = collection['createCollectionDetail']['id']
            print(f"  ✅ Created collection: {collection_name}")
            
            # Wait for collection to be active
            import time
            print(f"  ⏳ Waiting for collection to be active...")
            for i in range(30):
                coll_status = aoss.batch_get_collection(ids=[collection_id])
                if coll_status['collectionDetails'][0]['status'] == 'ACTIVE':
                    break
                time.sleep(10)
            print(f"  ✅ Collection is active")
            
        except aoss.exceptions.ConflictException:
            print(f"  ℹ️  Collection already exists: {collection_name}")
            collections = aoss.list_collections(collectionFilters={'name': collection_name})
            collection_id = collections['collectionSummaries'][0]['id']
        
        # Get collection endpoint
        collection_details = aoss.batch_get_collection(ids=[collection_id])
        collection_endpoint = collection_details['collectionDetails'][0]['collectionEndpoint']
        
        # Create IAM role for Knowledge Base
        role_name = f"{kb_name}-kb-role"
        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "bedrock.amazonaws.com"},
                "Action": "sts:AssumeRole"
            }]
        }
        
        try:
            role_response = iam.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description=f"Role for {kb_name} Knowledge Base"
            )
            role_arn = role_response['Role']['Arn']
            print(f"  ✅ Created IAM role: {role_name}")
            
            # Attach policies
            policy_doc = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["s3:GetObject", "s3:ListBucket"],
                        "Resource": [f"arn:aws:s3:::{bucket_name}/*", f"arn:aws:s3:::{bucket_name}"]
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["bedrock:InvokeModel"],
                        "Resource": f"arn:aws:bedrock:*::foundation-model/{embedding_model}"
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["aoss:APIAccessAll"],
                        "Resource": f"arn:aws:aoss:{os.getenv('AWS_REGION')}:{account_id}:collection/{collection_id}"
                    }
                ]
            }
            
            iam.put_role_policy(
                RoleName=role_name,
                PolicyName=f"{kb_name}-policy",
                PolicyDocument=json.dumps(policy_doc)
            )
            print(f"  ✅ Attached policies to role")
            
            # Wait for role to propagate
            import time
            time.sleep(10)
            
        except iam.exceptions.EntityAlreadyExistsException:
            role_arn = iam.get_role(RoleName=role_name)['Role']['Arn']
            print(f"  ℹ️  IAM role already exists: {role_name}")
        
        # Create Knowledge Base
        print(f"  📚 Creating Knowledge Base: {kb_name}")
        
        kb_response = bedrock_agent.create_knowledge_base(
            name=kb_name,
            description=description,
            roleArn=role_arn,
            knowledgeBaseConfiguration={
                'type': 'VECTOR',
                'vectorKnowledgeBaseConfiguration': {
                    'embeddingModelArn': f"arn:aws:bedrock:{os.getenv('AWS_REGION')}::foundation-model/{embedding_model}"
                }
            },
            storageConfiguration={
                'type': 'OPENSEARCH_SERVERLESS',
                'opensearchServerlessConfiguration': {
                    'collectionArn': f"arn:aws:aoss:{os.getenv('AWS_REGION')}:{account_id}:collection/{collection_id}",
                    'vectorIndexName': 'bedrock-knowledge-base-default-index',
                    'fieldMapping': {
                        'vectorField': 'bedrock-knowledge-base-default-vector',
                        'textField': 'AMAZON_BEDROCK_TEXT_CHUNK',
                        'metadataField': 'AMAZON_BEDROCK_METADATA'
                    }
                }
            }
        )
        
        kb_id = kb_response['knowledgeBase']['knowledgeBaseId']
        print(f"  ✅ Created Knowledge Base: {kb_id}")
        
        # Create Data Source
        print(f"  📂 Creating S3 data source...")
        
        ds_response = bedrock_agent.create_data_source(
            knowledgeBaseId=kb_id,
            name=f"{kb_name}-s3-source",
            description=f"S3 data source for {kb_name}",
            dataSourceConfiguration={
                'type': 'S3',
                's3Configuration': {
                    'bucketArn': f"arn:aws:s3:::{bucket_name}"
                }
            }
        )
        
        ds_id = ds_response['dataSource']['dataSourceId']
        print(f"  ✅ Created data source: {ds_id}")
        
        # Start ingestion
        print(f"  🔄 Starting data ingestion...")
        bedrock_agent.start_ingestion_job(
            knowledgeBaseId=kb_id,
            dataSourceId=ds_id
        )
        print(f"  ✅ Data ingestion started")
        
        return kb_id
        
    except Exception as e:
        print(f"  ❌ Failed to create Knowledge Base {kb_name}: {e}")
        raise

def store_kb_ids_if_provided():
    """Store Knowledge Base IDs from environment variables if provided."""
    sop_kb_id = os.getenv('SOP_KB_ID')
    api_kb_id = os.getenv('API_DOCS_KB_ID')
    
    if sop_kb_id:
        store_ssm_parameter('/sap-invoice-exception/bedrock/sops-kb-id', sop_kb_id, 'Bedrock Knowledge Base ID for SOPs')
        print(f"  ✅ Stored SOP KB ID in SSM: {sop_kb_id}")
    
    if api_kb_id:
        store_ssm_parameter('/sap-invoice-exception/bedrock/api-docs-kb-id', api_kb_id, 'Bedrock Knowledge Base ID for API docs')
        print(f"  ✅ Stored API Docs KB ID in SSM: {api_kb_id}")

def sync_knowledge_base(kb_id, kb_name):
    """Sync Knowledge Base data source after files are uploaded."""
    bedrock_agent = session.client('bedrock-agent')
    
    try:
        # Get data sources for this KB
        data_sources = bedrock_agent.list_data_sources(knowledgeBaseId=kb_id)
        
        if not data_sources.get('dataSourceSummaries'):
            print(f"  ⚠️  No data sources found for KB: {kb_name}")
            return
        
        # Sync the first data source (should be the S3 source)
        ds_id = data_sources['dataSourceSummaries'][0]['dataSourceId']
        
        print(f"  🔄 Starting ingestion job for {kb_name}...")
        bedrock_agent.start_ingestion_job(
            knowledgeBaseId=kb_id,
            dataSourceId=ds_id
        )
        print(f"  ✅ Ingestion job started for {kb_name}")
        
    except Exception as e:
        print(f"  ⚠️  Could not sync {kb_name}: {e}")
        print(f"     You can manually sync in the Bedrock console")

def deploy_phase_3_knowledge_bases():
    """Phase 3: Upload files to S3 for Knowledge Bases (manual KB creation in console)."""
    print("\n" + "=" * 80)
    print("PHASE 3: Uploading Files for Knowledge Bases")
    print("=" * 80)
    print()
    
    # Get bucket names from SSM
    sop_bucket = ssm.get_parameter(Name='/sap-invoice-exception/s3/sops-bucket')['Parameter']['Value']
    api_docs_bucket = ssm.get_parameter(Name='/sap-invoice-exception/s3/api-docs-bucket')['Parameter']['Value']
    
    # Upload SOP files (always sync - idempotent)
    print("�  Syncing SOP documents to S3...")
    sop_files = upload_files_to_s3('sops', sop_bucket)
    print(f"  ✅ Synced {len(sop_files)} SOP file(s)")
    print()
    
    # Upload API documentation files (always sync - idempotent)
    print("📤 Syncing SAP API documentation to S3...")
    api_files = upload_files_to_s3('sap-api-docs', api_docs_bucket)
    print(f"  ✅ Synced {len(api_files)} API documentation file(s)")
    print()
    
    # Store KB IDs if provided in environment
    print("📝 Storing Knowledge Base IDs...")
    store_kb_ids_if_provided()
    print()
    
    # Check if KB IDs are already stored and sync them
    try:
        sop_kb_id = ssm.get_parameter(Name='/sap-invoice-exception/bedrock/sops-kb-id')['Parameter']['Value']
        api_kb_id = ssm.get_parameter(Name='/sap-invoice-exception/bedrock/api-docs-kb-id')['Parameter']['Value']
        
        # Sync Knowledge Bases after uploading files
        print("🔄 Syncing Knowledge Bases...")
        sync_knowledge_base(sop_kb_id, "SOP Knowledge Base")
        sync_knowledge_base(api_kb_id, "API Docs Knowledge Base")
        print()
        
        print("✅ Phase 3 Complete: Files synced and Knowledge Bases updated")
        print()
        print("📋 Resources:")
        print(f"  • SOP files synced to: {sop_bucket}")
        print(f"  • API docs synced to: {api_docs_bucket}")
        print(f"  • SOP Knowledge Base ID: {sop_kb_id}")
        print(f"  • API Docs Knowledge Base ID: {api_kb_id}")
        print()
        
    except ssm.exceptions.ParameterNotFound:
        print("✅ Phase 3 Complete: Files synced to S3")
        print()
        print("📋 Resources Created:")
        print(f"  • Synced {len(sop_files)} SOP files to: {sop_bucket}")
        print(f"  • Synced {len(api_files)} API documentation files to: {api_docs_bucket}")
        print()
        print("⚠️  MANUAL STEP REQUIRED - Create Knowledge Bases in Console:")
        print()
        print("  1. Go to Bedrock > Knowledge Bases: https://console.aws.amazon.com/bedrock/home#/knowledge-bases")
        print()
        print("  2. Create SOP Knowledge Base:")
        print(f"     - Name: SOP-PO-Accrual-KB")
        print(f"     - Description: Standard Operating Procedures for SAP Invoice Exception Handling Processing")
        print(f"     - Embedding model: Titan Text Embeddings V2")
        print(f"     - Vector store: Quick create OpenSearch Serverless (recommended)")
        print(f"     - Data source: S3, bucket = {sop_bucket}")
        print(f"     - Copy the Knowledge Base ID after creation")
        print()
        print("  3. Create API Documentation Knowledge Base:")
        print(f"     - Name: API-Docs-PO-Accrual-KB")
        print(f"     - Description: SAP API Documentation for Invoice Exception Handling Processing")
        print(f"     - Embedding model: Titan Text Embeddings V2")
        print(f"     - Vector store: Quick create OpenSearch Serverless (recommended)")
        print(f"     - Data source: S3, bucket = {api_docs_bucket}")
        print(f"     - Copy the Knowledge Base ID after creation")
        print()
        print("  4. After creating both KBs, add them to .env file:")
        print(f"     SOP_KB_ID=YOUR_SOP_KB_ID")
        print(f"     API_DOCS_KB_ID=YOUR_API_DOCS_KB_ID")
        print()
        print("  5. Then re-run the deployment script to store the IDs in SSM")
        print()

def deploy_phase_2_secrets_dynamodb():
    """Phase 2: Create Secrets Manager and DynamoDB."""
    print("\n" + "=" * 80)
    print("PHASE 2: Creating Secrets Manager and DynamoDB")
    print("=" * 80)
    print()
    
    # Create SAP credentials secret
    print("🔐 Creating Secrets Manager secrets...")
    print()
    
    secret_name = get_config('SAP_SECRET_NAME', 'sap-invoice-exception/sap-credentials')
    print(f"1. SAP Credentials Secret: {secret_name}")
    
    import json
    sap_credentials = json.dumps({
        'username': os.getenv('SAP_USERNAME'),
        'password': os.getenv('SAP_PASSWORD'),
        'base_url': os.getenv('SAP_BASE_URL')
    })
    
    create_secret(secret_name, sap_credentials, "SAP system credentials for PO accrual automation")
    print()
    
    # Create DynamoDB table
    print("🗄️  Creating DynamoDB table...")
    print()
    
    table_name = get_config('DYNAMODB_TABLE_NAME', 'sap-invoice-exception-cases-{environment}')
    print(f"1. Cases Table: {table_name}")
    print(f"   Schema:")
    print(f"     • Primary Key: case_id (String)")
    print(f"     • GSI: status-index on status")
    print(f"     • TTL: ttl attribute")
    print(f"   Attributes:")
    print(f"     • po_number, line_item, gl_account, cost_center")
    print(f"     • open_balance, need_by_date, status")
    print(f"     • determined_end_date, end_date_source, profit_center")
    print(f"     • wbs_element, accrual_amount, processing_history")
    print(f"     • created_at, updated_at, ttl")
    
    create_dynamodb_table(table_name)
    print()
    
    print("✅ Phase 2 Complete: Secrets and DynamoDB created")
    print()
    print("📋 Resources Created:")
    print(f"  • Secret: {secret_name}")
    print(f"  • DynamoDB Table: {table_name}")
    print(f"  • SSM Parameter: /sap-invoice-exception/secrets/sap-credentials-arn")
    print(f"  • SSM Parameter: /sap-invoice-exception/dynamodb/cases-table")
    print()
    print("🔍 Please verify in AWS Console:")
    print("  1. Go to Secrets Manager: https://console.aws.amazon.com/secretsmanager/listsecrets")
    print("  2. Verify the SAP credentials secret exists")
    print("  3. Go to DynamoDB: https://console.aws.amazon.com/dynamodbv2/home#tables")
    print(f"  4. Verify table '{table_name}' exists with status-index GSI")
    print("  5. Go to Systems Manager > Parameter Store")
    print("  6. Verify the 2 new SSM parameters exist")
    print()

def deploy_phase_1_s3():
    """Phase 1: Create S3 buckets."""
    print("\n" + "=" * 80)
    print("PHASE 1: Creating S3 Buckets")
    print("=" * 80)
    print()
    
    # Get bucket names from config or use defaults
    sop_bucket = get_config('SOP_BUCKET_NAME', 'sap-invoice-exception-sops-{account_id}')
    api_docs_bucket = get_config('API_DOCS_BUCKET_NAME', 'sap-invoice-exception-api-docs-{account_id}')
    data_bucket = get_config('DATA_BUCKET_NAME', 'sap-invoice-exception-data-{account_id}')
    
    print("📦 Creating S3 buckets...")
    print()
    
    # Create SOP bucket
    print(f"1. SOP Documents Bucket: {sop_bucket}")
    create_s3_bucket(sop_bucket, "sops-bucket")
    print()
    
    # Create API docs bucket
    print(f"2. SAP API Documentation Bucket: {api_docs_bucket}")
    create_s3_bucket(api_docs_bucket, "api-docs-bucket")
    print()
    
    # Create data bucket
    print(f"3. Data Persistence Bucket: {data_bucket}")
    create_s3_bucket(data_bucket, "data-bucket")
    print()
    
    print("✅ Phase 1 Complete: S3 buckets created")
    print()
    print("📋 Resources Created:")
    print(f"  • S3 Bucket: {sop_bucket}")
    print(f"  • S3 Bucket: {api_docs_bucket}")
    print(f"  • S3 Bucket: {data_bucket}")
    print(f"  • SSM Parameter: /sap-invoice-exception/s3/sops-bucket")
    print(f"  • SSM Parameter: /sap-invoice-exception/s3/api-docs-bucket")
    print(f"  • SSM Parameter: /sap-invoice-exception/s3/data-bucket")
    print()
    print("🔍 Please verify in AWS Console:")
    print("  1. Go to S3 console: https://s3.console.aws.amazon.com/s3/buckets")
    print("  2. Verify all 3 buckets exist with versioning enabled")
    print("  3. Go to Systems Manager > Parameter Store")
    print("  4. Verify the 3 SSM parameters exist")
    print()


def deploy_phase_4_lambda_eventbridge():
    """Phase 4: Deploy Lambda poller and EventBridge rule."""
    print("\n" + "=" * 80)
    print("PHASE 4: Deploying Lambda and EventBridge")
    print("=" * 80)
    print()
    
    lambda_client = session.client('lambda')
    events = session.client('events')
    iam = session.client('iam')
    
    # Create IAM role for Lambda
    lambda_role_name = 'sap-invoice-exception-lambda-role'
    print(f"🔐 Creating IAM role for Lambda: {lambda_role_name}")
    
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }
    
    try:
        role_response = iam.create_role(
            RoleName=lambda_role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="Execution role for SAP Invoice Exception Handling Lambda poller"
        )
        lambda_role_arn = role_response['Role']['Arn']
        print(f"  ✅ Created IAM role: {lambda_role_name}")
        
        # Attach policies
        policy_doc = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                    "Resource": "arn:aws:logs:*:*:*"
                },
                {
                    "Effect": "Allow",
                    "Action": ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query"],
                    "Resource": f"arn:aws:dynamodb:{os.getenv('AWS_REGION')}:{account_id}:table/*"
                },
                {
                    "Effect": "Allow",
                    "Action": ["ssm:GetParameter"],
                    "Resource": f"arn:aws:ssm:{os.getenv('AWS_REGION')}:{account_id}:parameter/sap-invoice-exception/*"
                },
                {
                    "Effect": "Allow",
                    "Action": ["secretsmanager:GetSecretValue"],
                    "Resource": f"arn:aws:secretsmanager:{os.getenv('AWS_REGION')}:{account_id}:secret:sap-invoice-exception/*"
                }
            ]
        }
        
        iam.put_role_policy(
            RoleName=lambda_role_name,
            PolicyName='sap-invoice-exception-lambda-policy',
            PolicyDocument=json.dumps(policy_doc)
        )
        print(f"  ✅ Attached policies to role")
        
        # Wait for role to propagate
        print(f"  ⏳ Waiting for IAM role to propagate...")
        import time
        time.sleep(15)
        
    except iam.exceptions.EntityAlreadyExistsException:
        lambda_role_arn = iam.get_role(RoleName=lambda_role_name)['Role']['Arn']
        print(f"  ℹ️  IAM role already exists: {lambda_role_name}")
    
    # Package Lambda code with dependencies
    print(f"\n📦 Packaging Lambda code with dependencies...")
    import zipfile
    import tempfile
    import shutil
    import subprocess
    import sys
    
    # Create temporary package directory
    package_dir = tempfile.mkdtemp()
    # Use secure temporary file creation
    zip_file = tempfile.NamedTemporaryFile(suffix='.zip', delete=False)
    zip_path = zip_file.name
    zip_file.close()
    
    try:
        # Install requests library to package directory
        print(f"  ⏳ Installing requests library...")
        subprocess.run(
            [sys.executable, '-m', 'pip', 'install', 'requests', '-t', package_dir],
            check=True,
            capture_output=True
        )
        
        # Copy Lambda function
        shutil.copy('lambda/odata_poller.py', os.path.join(package_dir, 'odata_poller.py'))
        
        # Create zip file
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(package_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arc_name = os.path.relpath(file_path, package_dir)
                    zipf.write(file_path, arc_name)
        
        with open(zip_path, 'rb') as f:
            zip_content = f.read()
        
        print(f"  ✅ Lambda code packaged with dependencies")
        
    except Exception as e:
        print(f"  ❌ Failed to package Lambda: {e}")
        raise
    finally:
        # Clean up package directory
        if os.path.exists(package_dir):
            shutil.rmtree(package_dir)
        if os.path.exists(zip_path):
            os.remove(zip_path)
    
    # Deploy Lambda function
    lambda_name = get_config('LAMBDA_POLLER_NAME', 'sap-invoice-exception-odata-poller')
    print(f"\n🚀 Deploying Lambda function: {lambda_name}")
    
    try:
        lambda_response = lambda_client.create_function(
            FunctionName=lambda_name,
            Runtime='python3.13',
            Role=lambda_role_arn,
            Handler='odata_poller.lambda_handler',
            Code={'ZipFile': zip_content},
            Timeout=300,
            MemorySize=512,
            Description='SAP OData poller for PO accrual automation'
        )
        lambda_arn = lambda_response['FunctionArn']
        print(f"  ✅ Created Lambda function: {lambda_name}")
        
    except lambda_client.exceptions.ResourceConflictException:
        print(f"  ℹ️  Lambda function already exists, updating...")
        
        # Wait for any pending updates to complete
        print(f"  ⏳ Waiting for Lambda to be ready for updates...")
        waiter = lambda_client.get_waiter('function_updated')
        waiter.wait(
            FunctionName=lambda_name,
            WaiterConfig={'Delay': 5, 'MaxAttempts': 60}
        )
        
        # Update code
        lambda_client.update_function_code(
            FunctionName=lambda_name,
            ZipFile=zip_content
        )
        
        # Wait for code update to complete
        waiter.wait(
            FunctionName=lambda_name,
            WaiterConfig={'Delay': 5, 'MaxAttempts': 60}
        )
        
        lambda_arn = lambda_client.get_function(FunctionName=lambda_name)['Configuration']['FunctionArn']
        print(f"  ✅ Updated Lambda function: {lambda_name}")
    
    store_ssm_parameter('/sap-invoice-exception/lambda/poller-arn', lambda_arn, 'Lambda function ARN for OData poller')
    
    # Create EventBridge rule
    rule_name = get_config('EVENTBRIDGE_RULE_NAME', 'sap-invoice-exception-polling-rule')
    print(f"\n⏰ Creating EventBridge rule: {rule_name}")
    
    try:
        rule_response = events.put_rule(
            Name=rule_name,
            ScheduleExpression='rate(5 minutes)',
            State='ENABLED',
            Description='Trigger SAP OData polling every 5 minutes'
        )
        rule_arn = rule_response['RuleArn']
        print(f"  ✅ Created EventBridge rule: {rule_name}")
        
    except Exception as e:
        print(f"  ℹ️  EventBridge rule exists or error: {e}")
        rule_arn = f"arn:aws:events:{os.getenv('AWS_REGION')}:{account_id}:rule/{rule_name}"
    
    # Add Lambda permission for EventBridge
    try:
        lambda_client.add_permission(
            FunctionName=lambda_name,
            StatementId='AllowEventBridgeInvoke',
            Action='lambda:InvokeFunction',
            Principal='events.amazonaws.com',
            SourceArn=rule_arn
        )
        print(f"  ✅ Added EventBridge permission to Lambda")
    except lambda_client.exceptions.ResourceConflictException:
        print(f"  ℹ️  EventBridge permission already exists")
    
    # Add Lambda as target
    events.put_targets(
        Rule=rule_name,
        Targets=[{
            'Id': '1',
            'Arn': lambda_arn
        }]
    )
    print(f"  ✅ Added Lambda as EventBridge target")
    
    store_ssm_parameter('/sap-invoice-exception/eventbridge/rule-arn', rule_arn, 'EventBridge rule ARN for polling')
    
    # Get table name for verification instructions
    table_name = get_config('DYNAMODB_TABLE_NAME', 'sap-invoice-exception-cases-{environment}')
    
    print("\n✅ Phase 4 Complete: Lambda and EventBridge deployed")
    print()
    print("📋 Resources Created:")
    print(f"  • IAM Role: {lambda_role_name}")
    print(f"  • Lambda Function: {lambda_name}")
    print(f"  • EventBridge Rule: {rule_name} (triggers every 5 minutes)")
    print(f"  • SSM Parameter: /sap-invoice-exception/lambda/poller-arn")
    print(f"  • SSM Parameter: /sap-invoice-exception/eventbridge/rule-arn")
    print()
    print("🔍 Please verify in AWS Console:")
    print("  1. Go to Lambda: https://console.aws.amazon.com/lambda/home#/functions")
    print(f"  2. Verify function '{lambda_name}' exists and can be invoked manually")
    print("  3. Go to EventBridge: https://console.aws.amazon.com/events/home#/rules")
    print(f"  4. Verify rule '{rule_name}' exists and is enabled")
    print("  5. Manually invoke the Lambda function to test it immediately")
    print("  6. Go to DynamoDB: https://console.aws.amazon.com/dynamodbv2/home#tables")
    print(f"  7. Open table '{table_name}' and verify cases are being created")
    print("  8. Check CloudWatch Logs for Lambda execution logs")
    print()
    print("⏸️  STOP HERE - Verify everything works before proceeding to Phase 5")
    print()


def deploy_phase_5_email_processor():
    """Phase 6: Deploy Email Processor Lambda and S3 bucket for SES."""
    print("\n" + "=" * 80)
    print("PHASE 6: Deploying Email Processor Lambda and S3 Bucket")
    print("=" * 80)
    print()
    
    lambda_client = session.client('lambda')
    s3_client = session.client('s3')
    iam = session.client('iam')
    
    # Create S3 bucket for email storage
    email_bucket_name = get_config('EMAIL_BUCKET_NAME', f'sap-invoice-exception-emails-{account_id}')
    print(f"📦 Creating S3 bucket for email storage: {email_bucket_name}")
    
    try:
        region = os.getenv('AWS_REGION', 'us-east-1')
        if region == 'us-east-1':
            s3_client.create_bucket(Bucket=email_bucket_name)
        else:
            s3_client.create_bucket(
                Bucket=email_bucket_name,
                CreateBucketConfiguration={'LocationConstraint': region}
            )
        print(f"  ✅ Created S3 bucket: {email_bucket_name}")
    except s3_client.exceptions.BucketAlreadyOwnedByYou:
        print(f"  ℹ️  S3 bucket already exists: {email_bucket_name}")
    except Exception as e:
        print(f"  ❌ Failed to create S3 bucket: {e}")
        raise
    
    # Add bucket policy to allow SES to write emails
    bucket_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowSESPuts",
                "Effect": "Allow",
                "Principal": {
                    "Service": "ses.amazonaws.com"
                },
                "Action": "s3:PutObject",
                "Resource": f"arn:aws:s3:::{email_bucket_name}/*",
                "Condition": {
                    "StringEquals": {
                        "AWS:SourceAccount": account_id
                    }
                }
            }
        ]
    }
    
    try:
        s3_client.put_bucket_policy(
            Bucket=email_bucket_name,
            Policy=json.dumps(bucket_policy)
        )
        print(f"  ✅ Added bucket policy to allow SES writes")
    except Exception as e:
        print(f"  ⚠️  Warning: Could not set bucket policy: {e}")
    
    store_ssm_parameter('/sap-invoice-exception/s3/email-bucket', email_bucket_name, 'S3 bucket for SES email storage')
    
    # Create IAM role for Email Processor Lambda
    email_lambda_role_name = 'sap-invoice-exception-email-processor-role'
    print(f"\n🔐 Creating IAM role for Email Processor Lambda: {email_lambda_role_name}")
    
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }
    
    try:
        role_response = iam.create_role(
            RoleName=email_lambda_role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="Execution role for SAP Invoice Exception Handling Email Processor Lambda"
        )
        email_lambda_role_arn = role_response['Role']['Arn']
        print(f"  ✅ Created IAM role: {email_lambda_role_name}")
        
        # Attach policies
        policy_doc = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                    "Resource": "arn:aws:logs:*:*:*"
                },
                {
                    "Effect": "Allow",
                    "Action": ["s3:GetObject"],
                    "Resource": f"arn:aws:s3:::{email_bucket_name}/*"
                },
                {
                    "Effect": "Allow",
                    "Action": ["ssm:GetParameter"],
                    "Resource": f"arn:aws:ssm:{os.getenv('AWS_REGION')}:{account_id}:parameter/sap-invoice-exception/*"
                },
                {
                    "Effect": "Allow",
                    "Action": ["secretsmanager:GetSecretValue"],
                    "Resource": f"arn:aws:secretsmanager:{os.getenv('AWS_REGION')}:{account_id}:secret:sap-invoice-exception/*"
                },
                {
                    "Effect": "Allow",
                    "Action": ["cognito-idp:AdminInitiateAuth", "cognito-idp:AdminGetUser"],
                    "Resource": "*"
                }
            ]
        }
        
        iam.put_role_policy(
            RoleName=email_lambda_role_name,
            PolicyName='sap-invoice-exception-email-processor-policy',
            PolicyDocument=json.dumps(policy_doc)
        )
        print(f"  ✅ Attached policies to role")
        
        # Wait for role to propagate
        print(f"  ⏳ Waiting for IAM role to propagate...")
        import time
        time.sleep(15)
        
    except iam.exceptions.EntityAlreadyExistsException:
        email_lambda_role_arn = iam.get_role(RoleName=email_lambda_role_name)['Role']['Arn']
        print(f"  ℹ️  IAM role already exists: {email_lambda_role_name}")
    
    # Package Lambda code with dependencies
    print(f"\n📦 Packaging Email Processor Lambda code with dependencies...")
    import zipfile
    import tempfile
    import shutil
    import subprocess
    import sys
    
    # Create temporary package directory
    package_dir = tempfile.mkdtemp()
    # Use secure temporary file creation
    zip_file = tempfile.NamedTemporaryFile(suffix='.zip', delete=False)
    zip_path = zip_file.name
    zip_file.close()
    
    try:
        # Install requests library to package directory
        print(f"  ⏳ Installing requests library...")
        subprocess.run(
            [sys.executable, '-m', 'pip', 'install', 'requests', '-t', package_dir],
            check=True,
            capture_output=True
        )
        
        # Copy Lambda function
        shutil.copy('lambda/s3_email_processor.py', os.path.join(package_dir, 's3_email_processor.py'))
        
        # Create zip file
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(package_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arc_name = os.path.relpath(file_path, package_dir)
                    zipf.write(file_path, arc_name)
        
        with open(zip_path, 'rb') as f:
            zip_content = f.read()
        
        print(f"  ✅ Lambda code packaged with dependencies")
        
    except Exception as e:
        print(f"  ❌ Failed to package Lambda: {e}")
        raise
    finally:
        # Clean up package directory
        if os.path.exists(package_dir):
            shutil.rmtree(package_dir)
        if os.path.exists(zip_path):
            os.remove(zip_path)
    
    # Deploy Email Processor Lambda function
    email_lambda_name = get_config('LAMBDA_EMAIL_PROCESSOR_NAME', 'sap-invoice-exception-email-processor')
    print(f"\n🚀 Deploying Email Processor Lambda function: {email_lambda_name}")
    
    try:
        lambda_response = lambda_client.create_function(
            FunctionName=email_lambda_name,
            Runtime='python3.13',
            Role=email_lambda_role_arn,
            Handler='email_processor.lambda_handler',
            Code={'ZipFile': zip_content},
            Timeout=300,
            MemorySize=512,
            Description='SAP Invoice Exception Handling email processor for SES replies'
        )
        email_lambda_arn = lambda_response['FunctionArn']
        print(f"  ✅ Created Lambda function: {email_lambda_name}")
        
    except lambda_client.exceptions.ResourceConflictException:
        print(f"  ℹ️  Lambda function already exists, updating...")
        
        # Wait for any pending updates to complete
        print(f"  ⏳ Waiting for Lambda to be ready for updates...")
        waiter = lambda_client.get_waiter('function_updated')
        waiter.wait(
            FunctionName=email_lambda_name,
            WaiterConfig={'Delay': 5, 'MaxAttempts': 60}
        )
        
        # Update code
        lambda_client.update_function_code(
            FunctionName=email_lambda_name,
            ZipFile=zip_content
        )
        
        # Wait for code update to complete
        waiter.wait(
            FunctionName=email_lambda_name,
            WaiterConfig={'Delay': 5, 'MaxAttempts': 60}
        )
        
        # Configuration already updated with code
        
        email_lambda_arn = lambda_client.get_function(FunctionName=email_lambda_name)['Configuration']['FunctionArn']
        print(f"  ✅ Updated Lambda function: {email_lambda_name}")
    
    store_ssm_parameter('/sap-invoice-exception/lambda/email-processor-arn', email_lambda_arn, 'Lambda function ARN for email processor')
    
    # Add Lambda permission for S3 to invoke the function
    print(f"\n🔐 Adding S3 permission to invoke Lambda...")
    try:
        lambda_client.add_permission(
            FunctionName=email_lambda_name,
            StatementId='AllowS3Invoke',
            Action='lambda:InvokeFunction',
            Principal='s3.amazonaws.com',
            SourceArn=f"arn:aws:s3:::{email_bucket_name}"
        )
        print(f"  ✅ Added S3 permission to Lambda")
        # Wait for permission to propagate
        print(f"  ⏳ Waiting for permission to propagate...")
        import time
        time.sleep(5)
    except lambda_client.exceptions.ResourceConflictException:
        print(f"  ℹ️  S3 permission already exists")
    
    # Configure S3 bucket notification to trigger Lambda
    print(f"\n🔔 Configuring S3 bucket notification to trigger Lambda...")
    try:
        s3_client.put_bucket_notification_configuration(
            Bucket=email_bucket_name,
            NotificationConfiguration={
                'LambdaFunctionConfigurations': [
                    {
                        'Id': 'EmailProcessorTrigger',
                        'LambdaFunctionArn': email_lambda_arn,
                        'Events': ['s3:ObjectCreated:*']
                    }
                ]
            }
        )
        print(f"  ✅ Configured S3 bucket notification")
    except Exception as e:
        print(f"  ⚠️  Warning: Could not configure S3 notification: {e}")
    
    print("\n✅ Phase 6 Complete: Email Processor Lambda and S3 bucket deployed")
    print()
    print("📋 Resources Created:")
    print(f"  • S3 Bucket: {email_bucket_name}")
    print(f"  • IAM Role: {email_lambda_role_name}")
    print(f"  • Lambda Function: {email_lambda_name}")
    print(f"  • S3 Notification: Triggers Lambda on email arrival")
    print(f"  • SES Rule Set: sap-invoice-exception-rule-set")
    print(f"  • SES Receipt Rule: invoice-exception-email-rule")
    print(f"  • SSM Parameter: /sap-invoice-exception/s3/email-bucket")
    print(f"  • SSM Parameter: /sap-invoice-exception/lambda/email-processor-arn")
    print()
    print("📧 Manual SES Configuration Required:")
    print("  1. Go to SES Console: https://console.aws.amazon.com/ses/home#/verified-identities")
    print("  2. Verify your email address for receiving emails")
    print("  3. Configure SES receipt rule to route to S3 bucket")
    print()


def deploy_phase_7_ses_receipt_rule():
    """Phase 7: Configure SES receipt rule for email replies (idempotent)."""
    print("\n" + "=" * 80)
    print("PHASE 7: Configuring SES Receipt Rule")
    print("=" * 80)
    print()
    
    ses_client = session.client('ses')
    
    # Read from SSM (created in Phase 6)
    try:
        email_bucket_name = get_ssm_parameter('/sap-invoice-exception/s3/email-bucket')
        print(f"  ✅ Retrieved S3 bucket from SSM: {email_bucket_name}")
    except Exception as e:
        print(f"  ❌ Could not retrieve S3 bucket from SSM: {e}")
        print(f"  ℹ️  Skipping SES configuration - run Phase 6 first")
        return
    
    # Get agent email from env
    agent_email = get_config('AGENT_EMAIL', 'invoice-exception@abhijgm.people.aws.dev')
    
    print(f"📧 Configuring SES to route emails to S3...")
    print(f"  Recipient: {agent_email}")
    print(f"  Target: s3://{email_bucket_name}")
    print()
    
    try:
        # Get or create receipt rule set
        rule_set_name = 'sap-invoice-exception-rule-set'
        try:
            ses_client.describe_receipt_rule_set(RuleSetName=rule_set_name)
            print(f"  ℹ️  Rule set already exists: {rule_set_name}")
        except ses_client.exceptions.RuleSetDoesNotExistException:
            ses_client.create_receipt_rule_set(RuleSetName=rule_set_name)
            print(f"  ✅ Created rule set: {rule_set_name}")
        
        # Set as active rule set (idempotent)
        try:
            ses_client.set_active_receipt_rule_set(RuleSetName=rule_set_name)
            print(f"  ✅ Activated rule set: {rule_set_name}")
        except Exception as e:
            print(f"  ℹ️  Rule set activation: {e}")
        
        # Create or update receipt rule
        rule_name = 'invoice-exception-email-rule'
        rule_config = {
            'Name': rule_name,
            'Enabled': True,
            'TlsPolicy': 'Optional',
            'Recipients': [agent_email],
            'Actions': [
                {
                    'S3Action': {
                        'BucketName': email_bucket_name
                    }
                }
            ],
            'ScanEnabled': True
        }
        
        try:
            # Try to describe the rule first
            ses_client.describe_receipt_rule(RuleSetName=rule_set_name, RuleName=rule_name)
            # Rule exists, update it
            ses_client.update_receipt_rule(
                RuleSetName=rule_set_name,
                Rule=rule_config
            )
            print(f"  ✅ Updated SES receipt rule: {rule_name}")
        except ses_client.exceptions.RuleDoesNotExistException:
            # Rule doesn't exist, create it
            ses_client.create_receipt_rule(
                RuleSetName=rule_set_name,
                Rule=rule_config
            )
            print(f"  ✅ Created SES receipt rule: {rule_name}")
        
        print()
        print("✅ Phase 7 Complete: SES receipt rule configured")
        print()
        print("📋 SES Configuration:")
        print(f"  • Rule Set: {rule_set_name} (active)")
        print(f"  • Receipt Rule: {rule_name}")
        print(f"  • Recipient: {agent_email}")
        print(f"  • S3 Bucket: {email_bucket_name}")
        print()
        print("📧 Next Steps:")
        print("  1. Verify email address in SES Console:")
        print("     https://console.aws.amazon.com/ses/home#/verified-identities")
        print(f"  2. Verify: {agent_email}")
        print("  3. Test by sending an email to that address")
        print()
    
    except Exception as e:
        print(f"  ⚠️  Warning: Could not configure SES receipt rule: {e}")
        print(f"  ℹ️  You may need to configure SES manually in the console")
        print()


def setup_cognito():
    """Create or reuse existing Cognito User Pool and generate JWT token."""
    print("\n" + "=" * 80)
    print("PHASE 5: Setting up Cognito Authentication")
    print("=" * 80)
    print()
    
    cognito = session.client('cognito-idp')
    
    try:
        secrets_cognito_name = get_config('SECRETS_COGNITO_NAME', 'sap-invoice-exception/cognito-config')
        username = get_config('COGNITO_USERNAME', 'admin')
        permanent_password = get_config('COGNITO_PERMANENT_PASSWORD')
        
        # Check if Cognito config already exists in Secrets Manager
        try:
            response = secretsmanager.get_secret_value(SecretId=secrets_cognito_name)
            existing_config = json.loads(response['SecretString'])
            print(f"  ℹ️  Using existing Cognito configuration from Secrets Manager")
            print(f"  ✅ User Pool ID: {existing_config['user_pool_id']}")
            print(f"  ✅ Client ID: {existing_config['client_id']}")
            
            # Refresh token even when reusing existing Cognito
            if permanent_password:
                print(f"  🔄 Refreshing Cognito bearer token...")
                import hmac
                import hashlib
                import base64
                
                message = username + existing_config['client_id']
                secret_hash = base64.b64encode(
                    hmac.new(
                        existing_config['client_secret'].encode(),
                        message.encode(),
                        digestmod=hashlib.sha256
                    ).digest()
                ).decode()
                
                auth_response = cognito.admin_initiate_auth(
                    UserPoolId=existing_config['user_pool_id'],
                    ClientId=existing_config['client_id'],
                    AuthFlow='ADMIN_NO_SRP_AUTH',
                    AuthParameters={
                        'USERNAME': username,
                        'PASSWORD': permanent_password,
                        'SECRET_HASH': secret_hash
                    }
                )
                
                # Update token and password in config
                existing_config['bearer_token'] = auth_response['AuthenticationResult']['AccessToken']
                existing_config['password'] = permanent_password  # Store password for agent runtime
                
                # Update Secrets Manager with new token and password
                secretsmanager.update_secret(
                    SecretId=secrets_cognito_name,
                    SecretString=json.dumps(existing_config)
                )
                print(f"  ✅ Token and password refreshed and updated in Secrets Manager")
            
            # Store SSM parameters even when reusing existing Cognito
            print(f"  📝 Storing SSM parameters for Streamlit dashboard...")
            store_ssm_parameter('/sap-invoice-exception/cognito/user-pool-id', existing_config['user_pool_id'], 'Cognito User Pool ID')
            store_ssm_parameter('/sap-invoice-exception/cognito/client-id', existing_config['client_id'], 'Cognito Client ID')
            store_ssm_parameter('/sap-invoice-exception/cognito/secret-name', secrets_cognito_name, 'Cognito Secrets Manager secret name')
            store_ssm_parameter('/sap-invoice-exception/cognito/username', username, 'Cognito admin username')
            
            return existing_config
        except secretsmanager.exceptions.ResourceNotFoundException:
            print(f"  ℹ️  Creating new Cognito configuration...")
        
        # Get configuration
        pool_name = get_config('COGNITO_USER_POOL_NAME', 'sap-invoice-exception-users')
        username = get_config('COGNITO_USERNAME', 'admin')
        temp_password = get_config('COGNITO_TEMP_PASSWORD')
        permanent_password = get_config('COGNITO_PERMANENT_PASSWORD')
        
        if not temp_password or not permanent_password:
            print("  ❌ COGNITO_TEMP_PASSWORD and COGNITO_PERMANENT_PASSWORD are required")
            print("  Please set them in your .env file")
            sys.exit(1)
        
        print(f"🔐 Creating Cognito User Pool: {pool_name}")
        
        # Create User Pool
        user_pool = cognito.create_user_pool(
            PoolName=pool_name,
            Policies={
                'PasswordPolicy': {
                    'MinimumLength': 8,
                    'RequireUppercase': False,
                    'RequireLowercase': False,
                    'RequireNumbers': False,
                    'RequireSymbols': False
                }
            }
        )
        user_pool_id = user_pool['UserPool']['Id']
        print(f"  ✅ Created User Pool: {user_pool_id}")
        
        # Create User Pool Client with secret
        client = cognito.create_user_pool_client(
            UserPoolId=user_pool_id,
            ClientName=f'{pool_name}-client',
            GenerateSecret=True,
            ExplicitAuthFlows=['ADMIN_NO_SRP_AUTH']
        )
        client_id = client['UserPoolClient']['ClientId']
        client_secret = client['UserPoolClient']['ClientSecret']
        print(f"  ✅ Created User Pool Client: {client_id}")
        
        # Create admin user
        print(f"  👤 Creating admin user: {username}")
        try:
            cognito.admin_create_user(
                UserPoolId=user_pool_id,
                Username=username,
                TemporaryPassword=temp_password,
                MessageAction='SUPPRESS'
            )
            
            # Set permanent password
            cognito.admin_set_user_password(
                UserPoolId=user_pool_id,
                Username=username,
                Password=permanent_password,
                Permanent=True
            )
            print(f"  ✅ Created user: {username}")
        except cognito.exceptions.UsernameExistsException:
            print(f"  ℹ️  User already exists: {username}")
        
        # Generate JWT token using Cognito authentication
        print(f"  🔑 Generating JWT bearer token...")
        import hmac
        import hashlib
        import base64
        
        message = username + client_id
        secret_hash = base64.b64encode(
            hmac.new(
                client_secret.encode(),
                message.encode(),
                digestmod=hashlib.sha256
            ).digest()
        ).decode()
        
        auth_response = cognito.admin_initiate_auth(
            UserPoolId=user_pool_id,
            ClientId=client_id,
            AuthFlow='ADMIN_NO_SRP_AUTH',
            AuthParameters={
                'USERNAME': username,
                'PASSWORD': permanent_password,
                'SECRET_HASH': secret_hash
            }
        )
        
        bearer_token = auth_response['AuthenticationResult']['AccessToken']
        print(f"  ✅ Generated JWT bearer token")
        
        # Create auth config (include password for agent runtime token refresh)
        auth_config = {
            'user_pool_id': user_pool_id,
            'client_id': client_id,
            'client_secret': client_secret,
            'discovery_url': f'https://cognito-idp.{os.getenv("AWS_REGION")}.amazonaws.com/{user_pool_id}/.well-known/openid-configuration',
            'bearer_token': bearer_token,
            'password': permanent_password  # Store password for agent runtime
        }
        
        # Store in Secrets Manager
        print(f"  💾 Storing Cognito configuration in Secrets Manager...")
        try:
            secretsmanager.create_secret(
                Name=secrets_cognito_name,
                SecretString=json.dumps(auth_config),
                Description='Cognito configuration for SAP Invoice Exception Handling AgentCore authentication'
            )
        except secretsmanager.exceptions.ResourceExistsException:
            secretsmanager.update_secret(
                SecretId=secrets_cognito_name,
                SecretString=json.dumps(auth_config)
            )
        print(f"  ✅ Stored Cognito config in: {secrets_cognito_name}")
        
        # Store in SSM Parameter Store (for Streamlit dashboard)
        store_ssm_parameter('/sap-invoice-exception/cognito/user-pool-id', user_pool_id, 'Cognito User Pool ID')
        store_ssm_parameter('/sap-invoice-exception/cognito/client-id', client_id, 'Cognito Client ID')
        store_ssm_parameter('/sap-invoice-exception/cognito/secret-name', secrets_cognito_name, 'Cognito Secrets Manager secret name')
        store_ssm_parameter('/sap-invoice-exception/cognito/username', username, 'Cognito admin username')
        
        print()
        print("✅ Phase 5 Complete: Cognito authentication configured")
        print()
        print("📋 Resources Created:")
        print(f"  • Cognito User Pool: {pool_name} ({user_pool_id})")
        print(f"  • Cognito Client: {client_id}")
        print(f"  • Admin User: {username}")
        print(f"  • Secret: {secrets_cognito_name}")
        print(f"  • SSM Parameters: /sap-invoice-exception/cognito/*")
        print()
        print("🔍 Please verify in AWS Console:")
        print("  1. Go to Cognito: https://console.aws.amazon.com/cognito/v2/idp/user-pools")
        print(f"  2. Verify User Pool '{pool_name}' exists")
        print(f"  3. Verify user '{username}' exists and is confirmed")
        print("  4. Go to Secrets Manager and verify the cognito-config secret")
        print()
        
        return auth_config
        
    except Exception as e:
        print(f"  ❌ Cognito setup failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

def deploy_mcp_server(auth_config):
    """Deploy MCP server to Bedrock AgentCore."""
    print("\n" + "=" * 80)
    print("PHASE 5.2: Deploying MCP Server to Bedrock AgentCore")
    print("=" * 80)
    print()
    
    try:
        # Import bedrock_agentcore_starter_toolkit
        try:
            from bedrock_agentcore_starter_toolkit import Runtime
        except ImportError:
            print("  ❌ bedrock_agentcore_starter_toolkit not installed")
            print("  Installing required package...")
            import subprocess
            subprocess.run([sys.executable, '-m', 'pip', 'install', 'bedrock-agentcore-starter-toolkit'], check=True)
            from bedrock_agentcore_starter_toolkit import Runtime
        
        mcp_server_name = get_config('MCP_SERVER_NAME', 'sap_mcp_server')
        
        print(f"🚀 Deploying MCP server: {mcp_server_name}")
        print(f"  Entrypoint: mcp_server/sap_mcp_server.py")
        print(f"  Protocol: MCP")
        print()
        
        # Configure MCP server runtime
        runtime = Runtime()
        
        # Configure JWT authorizer with Cognito
        auth_config_for_mcp = {
            'customJWTAuthorizer': {
                'allowedClients': [auth_config['client_id']],
                'discoveryUrl': auth_config['discovery_url'],
            }
        }
        
        runtime.configure(
            entrypoint='mcp_server/sap_mcp_server.py',
            auto_create_execution_role=True,
            auto_create_ecr=True,
            requirements_file='mcp_server/requirements.txt',
            region=os.getenv('AWS_REGION'),
            protocol='MCP',
            authorizer_configuration=auth_config_for_mcp,
            agent_name=mcp_server_name
        )
        
        print("  ⏳ Launching MCP server (this may take 5-10 minutes)...")
        print("     - Building Docker image")
        print("     - Pushing to ECR")
        print("     - Deploying to Bedrock AgentCore")
        print()
        
        result = runtime.launch(auto_update_on_conflict=True)
        
        print(f"  ✅ MCP server deployed successfully!")
        print(f"  Agent ARN: {result.agent_arn}")
        print()
        
        # Store MCP server ARN in SSM Parameter Store using ssm client directly
        ssm.put_parameter(
            Name='/sap-invoice-exception/agentcore/mcp-arn',
            Value=result.agent_arn,
            Type='String',
            Description='MCP Server Agent ARN',
            Overwrite=True
        )
        print(f"  ✅ Stored agent ARN in SSM: /sap-invoice-exception/agentcore/mcp-arn")
        
        # Wait for IAM role to be created and find it
        print(f"  ⏳ Waiting for IAM execution role to be created...")
        import time
        time.sleep(10)
        
        # Find the execution role created by AgentCore
        iam = session.client('iam')
        roles = iam.list_roles()['Roles']
        agent_role = None
        for role in roles:
            if f'AmazonBedrockAgentCoreSDKRuntime-{os.getenv("AWS_REGION")}' in role['RoleName']:
                # Check if this is the most recently created role (likely ours)
                if not agent_role or role['CreateDate'] > agent_role['CreateDate']:
                    agent_role = role
        
        if agent_role:
            role_arn = agent_role['Arn']
            role_name = agent_role['RoleName']
            print(f"  ✅ Found execution role: {role_name}")
            
            # Store role ARN in SSM
            ssm.put_parameter(
                Name='/sap-invoice-exception/agentcore/mcp-role-arn',
                Value=role_arn,
                Type='String',
                Description='MCP Server Execution Role ARN',
                Overwrite=True
            )
            print(f"  ✅ Stored role ARN in SSM: /sap-invoice-exception/agentcore/mcp-role-arn")
        else:
            print(f"  ⚠️  Could not find execution role automatically")
            print(f"     Role will be configured in the permissions phase")
        
        print()
        print("✅ Phase 5.2 Complete: MCP server deployed to AgentCore")
        print()
        print("📋 Resources Created:")
        print(f"  • MCP Server: {mcp_server_name}")
        print(f"  • Agent ARN: {result.agent_arn}")
        print(f"  • SSM Parameter: /sap-invoice-exception/agentcore/mcp-arn")
        if agent_role:
            print(f"  • SSM Parameter: /sap-invoice-exception/agentcore/mcp-role-arn")
            print(f"  • IAM Execution Role: {role_name}")
        print(f"  • ECR Repository: (auto-created)")
        print()
        print("🔍 Please verify in AWS Console:")
        print("  1. Go to Bedrock > AgentCore: https://console.aws.amazon.com/bedrock/home#/agentcore")
        print(f"  2. Verify MCP server '{mcp_server_name}' is deployed and active")
        print("  3. Check CloudWatch Logs for MCP server logs")
        print("  4. Go to ECR and verify the MCP server image was pushed")
        print()
        
        return result.agent_arn
        
    except Exception as e:
        print(f"  ❌ MCP server deployment failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

def add_agentcore_permissions(mcp_arn=None, strands_arn=None):
    """Add IAM permissions to AgentCore roles for accessing AWS resources.
    
    Args:
        mcp_arn: MCP server ARN to allow Strands agent to invoke
        strands_arn: Strands agent ARN (for reference)
    
    Returns:
        bool: True if permissions were added successfully, False otherwise
    """
    
    print("\n" + "=" * 80)
    print("PHASE 5.4: Adding IAM Permissions to AgentCore Roles")
    print("=" * 80)
    print()
    
    try:
        iam = session.client('iam')
        
        # Get MCP ARN from SSM if not provided
        if not mcp_arn:
            try:
                mcp_arn = ssm.get_parameter(Name='/sap-invoice-exception/agentcore/mcp-arn')['Parameter']['Value']
                print(f"  📡 Retrieved MCP ARN from SSM: {mcp_arn}")
            except:
                print(f"  ⚠️  Could not retrieve MCP ARN from SSM")
                mcp_arn = None
        
        # Find all AgentCore roles
        print("🔍 Finding AgentCore roles...")
        roles = iam.list_roles()['Roles']
        agentcore_roles = [role['RoleName'] for role in roles 
                          if f'AmazonBedrockAgentCoreSDKRuntime-{os.getenv("AWS_REGION")}' in role['RoleName']]
        
        if not agentcore_roles:
            print("  ⚠️  No AgentCore roles found yet")
            print("     Retrying in 5 seconds...")
            import time
            time.sleep(5)
            
            # Retry
            roles = iam.list_roles()['Roles']
            agentcore_roles = [role['RoleName'] for role in roles 
                              if f'AmazonBedrockAgentCoreSDKRuntime-{os.getenv("AWS_REGION")}' in role['RoleName']]
            
            if not agentcore_roles:
                print("  ⚠️  Still no AgentCore roles found")
                print("     Roles may need to be configured manually")
                return
        
        print(f"  Found {len(agentcore_roles)} AgentCore role(s)")
        
        # Clean up old duplicate policies first (to free up space)
        print("🧹 Cleaning up old policies...")
        duplicate_policies = ['SAP-Agent-DynamoDB-Access', 'SAP-Agent-Comprehensive-Permissions', 'SAP-PO-Accrual-Agent-Permissions-Old']
        cleaned_count = 0
        for role_name in agentcore_roles:
            for policy_name in duplicate_policies:
                try:
                    iam.delete_role_policy(RoleName=role_name, PolicyName=policy_name)
                    cleaned_count += 1
                except iam.exceptions.NoSuchEntityException:
                    pass
                except Exception:
                    pass
        
        if cleaned_count > 0:
            print(f"  ✅ Cleaned up {cleaned_count} old policy/policies")
        else:
            print(f"  ℹ️  No old policies to clean up")
        
        # Consolidated policy document
        policy_document = {
            'Version': '2012-10-17',
            'Statement': [
                {
                    'Effect': 'Allow',
                    'Action': [
                        'dynamodb:GetItem',
                        'dynamodb:PutItem',
                        'dynamodb:UpdateItem',
                        'dynamodb:Query',
                        'dynamodb:Scan',
                        'dynamodb:BatchGetItem',
                        'dynamodb:BatchWriteItem',
                        'dynamodb:DescribeTable'
                    ],
                    'Resource': [
                        f'arn:aws:dynamodb:{os.getenv("AWS_REGION")}:{account_id}:table/sap-invoice-exception-*',
                        f'arn:aws:dynamodb:{os.getenv("AWS_REGION")}:{account_id}:table/sap-invoice-exception-*/index/*'
                    ]
                },
                {
                    'Effect': 'Allow',
                    'Action': [
                        'bedrock:Retrieve',
                        'bedrock:InvokeModel',
                        'bedrock:InvokeModelWithResponseStream',
                        'bedrock-agent-runtime:Retrieve',
                        'bedrock-agent-runtime:InvokeAgent'
                    ],
                    'Resource': '*'
                },
                {
                    'Effect': 'Allow',
                    'Action': [
                        'ses:SendEmail',
                        'ses:SendRawEmail',
                        'ses:GetSendQuota',
                        'ses:GetSendStatistics'
                    ],
                    'Resource': '*'
                },
                {
                    'Effect': 'Allow',
                    'Action': [
                        'ssm:GetParameter',
                        'ssm:GetParameters',
                        'ssm:GetParametersByPath'
                    ],
                    'Resource': [
                        f'arn:aws:ssm:{os.getenv("AWS_REGION")}:{account_id}:parameter/sap-invoice-exception/*'
                    ]
                },
                {
                    'Effect': 'Allow',
                    'Action': [
                        'secretsmanager:GetSecretValue',
                        'secretsmanager:UpdateSecret',
                        'secretsmanager:DescribeSecret'
                    ],
                    'Resource': [
                        f'arn:aws:secretsmanager:{os.getenv("AWS_REGION")}:{account_id}:secret:sap-invoice-exception/*'
                    ]
                },
                {
                    'Effect': 'Allow',
                    'Action': [
                        's3:GetObject',
                        'S3:PutObject',
                        's3:DeleteObject',
                        's3:ListBucket'
                    ],
                    'Resource': [
                        f'arn:aws:s3:::sap-invoice-exception-*',
                        f'arn:aws:s3:::sap-invoice-exception-*/*'
                    ]
                },
                {
                    'Effect': 'Allow',
                    'Action': [
                        'lambda:InvokeFunction'
                    ],
                    'Resource': [
                        f'arn:aws:lambda:{os.getenv("AWS_REGION")}:{account_id}:function:sap-invoice-exception-*'
                    ]
                },
                {
                    'Effect': 'Allow',
                    'Action': [
                        'kms:Decrypt',
                        'kms:DescribeKey'
                    ],
                    'Resource': f'arn:aws:kms:{os.getenv("AWS_REGION")}:{account_id}:key/*'
                },
                {
                    'Effect': 'Allow',
                    'Action': [
                        'bedrock-agentcore:InvokeAgent',
                        'bedrock-agentcore:InvokeAgentRuntime'
                    ],
                    'Resource': f'arn:aws:bedrock-agentcore:{os.getenv("AWS_REGION")}:{account_id}:runtime/*'
                },
                {
                    'Effect': 'Allow',
                    'Action': [
                        'cognito-idp:AdminInitiateAuth',
                        'cognito-idp:AdminGetUser'
                    ],
                    'Resource': '*'  # Cognito requires wildcard for AdminInitiateAuth
                }
            ]
        }
        
        # Add specific permission for Strands agent to invoke MCP server
        if mcp_arn:
            print(f"  🔗 Adding specific permission for Strands agent to invoke MCP server")
            policy_document['Statement'].append({
                'Effect': 'Allow',
                'Action': [
                    'bedrock-agentcore:InvokeAgent',
                    'bedrock-agentcore:InvokeAgentRuntime'
                ],
                'Resource': [
                    mcp_arn,
                    f'{mcp_arn}/*'
                ]
            })
        
        # Apply policy to all AgentCore roles
        print("📝 Adding permissions to AgentCore roles...")
        success_count = 0
        failed_count = 0
        
        for role_name in agentcore_roles:
            try:
                iam.put_role_policy(
                    RoleName=role_name,
                    PolicyName='SAP-PO-Accrual-Agent-Permissions',
                    PolicyDocument=json.dumps(policy_document)
                )
                success_count += 1
            except iam.exceptions.LimitExceededException:
                # Role has too many policies (old role from other projects)
                failed_count += 1
            except Exception as e:
                print(f"  ⚠️  Unexpected error for {role_name}: {e}")
                failed_count += 1
        
        print(f"  ✅ Successfully added permissions to {success_count} role(s)")
        if failed_count > 0:
            print(f"  ℹ️  Skipped {failed_count} role(s) (policy size limit - likely old roles from other projects)")
        
        print()
        print("✅ Phase 5.4 Complete: IAM permissions configured")
        print()
        print("📋 Permissions Added:")
        print("  • DynamoDB: Read/Write access to sap-invoice-exception tables")
        print("  • Bedrock: Model invocation and knowledge base retrieval")
        print("  • SES: Email sending capabilities")
        print("  • SSM: Parameter Store read access")
        print("  • Secrets Manager: Secret read access")
        print("  • S3: Bucket access for sap-invoice-exception buckets")
        print("  • Lambda: Function invocation")
        print("  • KMS: Decryption for encrypted resources")
        print("  • AgentCore: Cross-agent invocation")
        print()
        
        return True
        
    except Exception as e:
        print(f"  ❌ Failed to add AgentCore permissions: {e}")
        print("     You may need to add permissions manually after agents are deployed")
        return False

def deploy_strands_agent(auth_config):
    """Deploy Strands agent to Bedrock AgentCore."""
    
    print("\n" + "=" * 80)
    print("PHASE 5.3: Deploying Strands Agent to Bedrock AgentCore")
    print("=" * 80)
    print()
    
    try:
        from bedrock_agentcore_starter_toolkit import Runtime
        
        strands_agent_name = get_config('STRANDS_AGENT_NAME', 'sap_strands_agent')
        
        print(f"🚀 Deploying Strands agent: {strands_agent_name}")
        print(f"  Entrypoint: strands_agent/strands_sap_agent_claude.py")
        print()
        
        # Configure Strands agent runtime
        runtime = Runtime()
        
        # Configure JWT authorizer with Cognito (same as MCP server)
        auth_config_for_agent = {
            'customJWTAuthorizer': {
                'allowedClients': [auth_config['client_id']],
                'discoveryUrl': auth_config['discovery_url'],
            }
        }
        
        runtime.configure(
            entrypoint='strands_agent/strands_sap_agent_claude.py',
            auto_create_execution_role=True,
            auto_create_ecr=True,
            requirements_file='strands_agent/requirements.txt',
            region=os.getenv('AWS_REGION'),
            authorizer_configuration=auth_config_for_agent,
            agent_name=strands_agent_name
        )
        
        print("  ⏳ Launching Strands agent (this may take 5-10 minutes)...")
        print("     - Building Docker image")
        print("     - Pushing to ECR")
        print("     - Deploying to Bedrock AgentCore")
        print()
        
        result = runtime.launch(auto_update_on_conflict=True)
        
        print(f"  ✅ Strands agent deployed successfully!")
        print(f"  Agent ARN: {result.agent_arn}")
        print()
        
        # Store Strands agent ARN in SSM Parameter Store using ssm client directly
        ssm.put_parameter(
            Name='/sap-invoice-exception/agentcore/strands-arn',
            Value=result.agent_arn,
            Type='String',
            Description='Strands Agent ARN',
            Overwrite=True
        )
        print(f"  ✅ Stored agent ARN in SSM: /sap-invoice-exception/agentcore/strands-arn")
        
        # Wait for IAM role to be created and find it
        print(f"  ⏳ Waiting for IAM execution role to be created...")
        import time
        time.sleep(10)
        
        # Find the execution role created by AgentCore
        iam = session.client('iam')
        roles = iam.list_roles()['Roles']
        agent_role = None
        for role in roles:
            if f'AmazonBedrockAgentCoreSDKRuntime-{os.getenv("AWS_REGION")}' in role['RoleName']:
                # Check if this is the most recently created role (likely ours)
                if not agent_role or role['CreateDate'] > agent_role['CreateDate']:
                    agent_role = role
        
        if agent_role:
            role_arn = agent_role['Arn']
            role_name = agent_role['RoleName']
            print(f"  ✅ Found execution role: {role_name}")
            
            # Store role ARN in SSM
            ssm.put_parameter(
                Name='/sap-invoice-exception/agentcore/strands-role-arn',
                Value=role_arn,
                Type='String',
                Description='Strands Agent Execution Role ARN',
                Overwrite=True
            )
            print(f"  ✅ Stored role ARN in SSM: /sap-invoice-exception/agentcore/strands-role-arn")
        else:
            print(f"  ⚠️  Could not find execution role automatically")
            print(f"     Role will be configured in the permissions phase")
        
        print()
        print("✅ Phase 5.3 Complete: Strands agent deployed to AgentCore")
        print()
        print("📋 Resources Created:")
        print(f"  • Strands Agent: {strands_agent_name}")
        print(f"  • Agent ARN: {result.agent_arn}")
        print(f"  • SSM Parameter: /sap-invoice-exception/agentcore/strands-arn")
        if agent_role:
            print(f"  • SSM Parameter: /sap-invoice-exception/agentcore/strands-role-arn")
            print(f"  • IAM Execution Role: {role_name}")
        print(f"  • ECR Repository: (auto-created)")
        print()
        print("🔍 Please verify in AWS Console:")
        print("  1. Go to Bedrock > AgentCore: https://console.aws.amazon.com/bedrock/home#/agentcore")
        print(f"  2. Verify Strands agent '{strands_agent_name}' is deployed and active")
        print("  3. Check CloudWatch Logs for Strands agent logs")
        print("  4. Go to ECR and verify the Strands agent image was pushed")
        print()
        
        return result.agent_arn
        
    except Exception as e:
        print(f"  ❌ Strands agent deployment failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

def main():
    """Main deployment function."""
    print("=" * 80)
    print("SAP Invoice Exception Handling Automation - Deployment Script")
    print("=" * 80)
    print()
    
    # Validate configuration
    validate_required_config()
    
    print(f"\n📋 Configuration:")
    print(f"  AWS Region: {os.getenv('AWS_REGION')}")
    print(f"  AWS Account: {account_id}")
    print(f"  Environment: {os.getenv('ENVIRONMENT', 'dev')}")
    print(f"  SAP Endpoint: {os.getenv('SAP_BASE_URL')}")
    print()
    
    print("🚀 Deployment will proceed in phases with console verification after each phase.")
    print()
    
    # Phase 1: S3 Buckets
    deploy_phase_1_s3()
    
    # Phase 2: Secrets Manager and DynamoDB
    deploy_phase_2_secrets_dynamodb()
    
    # Phase 3: Bedrock Knowledge Bases
    deploy_phase_3_knowledge_bases()
    
    # Phase 4: Lambda and EventBridge
    deploy_phase_4_lambda_eventbridge()
    
    # Phase 5: Cognito Authentication
    auth_config = setup_cognito()
    
    # Phase 5.2: Deploy MCP Server
    mcp_arn = deploy_mcp_server(auth_config)
    if not mcp_arn:
        print("\n❌ Deployment failed at Phase 5.2: MCP Server")
        sys.exit(1)
    
    # Phase 5.3: Deploy Strands Agent
    strands_arn = deploy_strands_agent(auth_config)
    if not strands_arn:
        print("\n❌ Deployment failed at Phase 5.3: Strands Agent")
        sys.exit(1)
    
    # Wait for IAM roles to propagate
    print("\n⏳ Waiting for IAM roles to propagate (15 seconds)...")
    import time
    time.sleep(15)
    
    # Phase 5.4: Add IAM Permissions to AgentCore Roles
    if not add_agentcore_permissions(mcp_arn, strands_arn):
        print("\n⚠️  Warning: Some permissions may not have been added")
        print("   You can re-run the deployment script to retry")
    
    # Phase 6: Email Processor Lambda and S3 (after Strands agent is deployed)
    deploy_phase_5_email_processor()
    
    # Phase 7: SES Receipt Rule (after S3 bucket and Lambda are created)
    deploy_phase_7_ses_receipt_rule()
    
    print("\n" + "=" * 80)
    print("🎉 DEPLOYMENT COMPLETE!")
    print("=" * 80)
    print()
    print("📋 All Resources Deployed:")
    print(f"  • MCP Server ARN: {mcp_arn}")
    print(f"  • Strands Agent ARN: {strands_arn}")
    print()
    print("✅ All ARNs saved to SSM Parameter Store:")
    print("  • /sap-invoice-exception/agentcore/mcp-arn")
    print("  • /sap-invoice-exception/agentcore/strands-arn")
    print()
    print("🔐 IAM Permissions configured for AgentCore roles")
    print()
    print("📝 Next Steps:")
    print("  1. Verify agents in Bedrock AgentCore console")
    print("  2. Test Strands agent: python3 test_agent.py")
    print("  3. Check CloudWatch logs for agent execution")
    print()
    print("🔧 Architecture:")
    print("   • Strands Agent → MCP Server → SAP/DynamoDB/SES")
    print("   • Full authentication with Cognito")
    print("   • All configuration in SSM/Secrets Manager")
    print()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Deployment interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Deployment failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
