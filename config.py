"""
Centralized configuration management for SAP Agentic AI Demo
Loads configuration from environment variables with validation
"""

import os
import sys
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Centralized configuration class"""
    
    def __init__(self):
        self._validate_required_vars()
    
    # AWS Configuration
    AWS_REGION: str = os.getenv('AWS_REGION', 'us-east-1')
    AWS_ACCOUNT_ID: str = os.getenv('AWS_ACCOUNT_ID', '')
    
    # SAP Configuration
    SAP_BASE_URL: str = os.getenv('SAP_BASE_URL', '')
    SAP_USERNAME: str = os.getenv('SAP_USERNAME', '')
    SAP_PASSWORD: str = os.getenv('SAP_PASSWORD', '')
    
    # Project Configuration
    PROJECT_NAME: str = os.getenv('PROJECT_NAME', 'sap-agentic-ai')
    ENVIRONMENT: str = os.getenv('ENVIRONMENT', 'dev')
    
    # AWS Resource Names
    @property
    def S3_BUCKET_NAME(self) -> str:
        return os.getenv('S3_BUCKET_NAME', f'sap-sops-{self.AWS_ACCOUNT_ID}')
    
    @property
    def DYNAMODB_TABLE_NAME(self) -> str:
        return os.getenv('DYNAMODB_TABLE_NAME', f'invoice-state-{self.ENVIRONMENT}')
    
    SECRETS_SAP_NAME: str = os.getenv('SECRETS_SAP_NAME', 'sap_credentials')
    SECRETS_COGNITO_NAME: str = os.getenv('SECRETS_COGNITO_NAME', 'sap_cognito_config')
    
    @property
    def EMAIL_BUCKET_NAME(self) -> str:
        return os.getenv('EMAIL_BUCKET_NAME', f'sap-email-{self.AWS_ACCOUNT_ID}')
    
    # Email Configuration
    SES_DOMAIN: str = os.getenv('SES_DOMAIN', '')
    AGENT_EMAIL: str = os.getenv('AGENT_EMAIL', '')
    
    # Bedrock Configuration
    MODEL_ID: str = os.getenv('MODEL_ID', 'us.anthropic.claude-3-7-sonnet-20250219-v1:0')
    
    # Cognito Configuration
    COGNITO_USERNAME: str = os.getenv('COGNITO_USERNAME', 'demo-user')
    COGNITO_TEMP_PASSWORD: str = os.getenv('COGNITO_TEMP_PASSWORD', '')
    COGNITO_PERMANENT_PASSWORD: str = os.getenv('COGNITO_PERMANENT_PASSWORD', '')
    
    # Knowledge Base Configuration
    KNOWLEDGE_BASE_ID: Optional[str] = os.getenv('KNOWLEDGE_BASE_ID') or None
    DATA_SOURCE_ID: Optional[str] = os.getenv('DATA_SOURCE_ID') or None
    
    # SAP API Knowledge Base Configuration
    SAP_API_KNOWLEDGE_BASE_ID: Optional[str] = os.getenv('SAP_API_KNOWLEDGE_BASE_ID') or None
    SAP_API_DATA_SOURCE_ID: Optional[str] = os.getenv('SAP_API_DATA_SOURCE_ID') or None
    
    # Lambda Configuration
    @property
    def LAMBDA_ODATA_POLLER_NAME(self) -> str:
        return os.getenv('LAMBDA_ODATA_POLLER_NAME', f'invoice-odata-poller-{self.ENVIRONMENT}')
    
    @property
    def LAMBDA_EMAIL_PROCESSOR_NAME(self) -> str:
        return os.getenv('LAMBDA_EMAIL_PROCESSOR_NAME', f's3-email-processor-{self.ENVIRONMENT}')
    
    # Security Configuration
    KMS_KEY_ID: Optional[str] = os.getenv('KMS_KEY_ID') or None
    
    # SOP Configuration
    SOP_FILES: Optional[str] = os.getenv('SOP_FILES') or None
    SOP_DIRECTORY: str = os.getenv('SOP_DIRECTORY', 'sops/')
    
    # SAP API Documentation Configuration
    SAP_API_FILES: Optional[str] = os.getenv('SAP_API_FILES') or None
    SAP_API_DIRECTORY: str = os.getenv('SAP_API_DIRECTORY', 'sap-api-docs/')
    
    @property
    def SAP_API_BUCKET_NAME(self) -> str:
        return os.getenv('SAP_API_BUCKET_NAME', f'sap-api-docs-{self.AWS_ACCOUNT_ID}')
    
    def _validate_required_vars(self):
        """Validate that all required environment variables are set"""
        required_vars = [
            ('AWS_ACCOUNT_ID', self.AWS_ACCOUNT_ID),
            ('SAP_BASE_URL', self.SAP_BASE_URL),
            ('SAP_USERNAME', self.SAP_USERNAME),
            ('SAP_PASSWORD', self.SAP_PASSWORD),
            ('COGNITO_TEMP_PASSWORD', self.COGNITO_TEMP_PASSWORD),
            ('COGNITO_PERMANENT_PASSWORD', self.COGNITO_PERMANENT_PASSWORD),
        ]
        
        # Email configuration is optional but recommended
        email_vars = [
            ('SES_DOMAIN', self.SES_DOMAIN),
            ('AGENT_EMAIL', self.AGENT_EMAIL),
        ]
        
        missing_email_vars = [var_name for var_name, var_value in email_vars if not var_value]
        if missing_email_vars:
            print("⚠️  Optional email configuration missing (email functionality will be limited):")
            for var in missing_email_vars:
                print(f"   - {var}")
            print("💡 Set these variables in .env for full email functionality\n")
        
        missing_vars = []
        for var_name, var_value in required_vars:
            if not var_value:
                missing_vars.append(var_name)
        
        if missing_vars:
            print("❌ Missing required environment variables:")
            for var in missing_vars:
                print(f"   - {var}")
            print("\n💡 Please copy .env.example to .env and fill in your values")
            sys.exit(1)
    
    def get_sap_credentials(self) -> dict:
        """Get SAP credentials as dictionary"""
        return {
            'username': self.SAP_USERNAME,
            'password': self.SAP_PASSWORD
        }
    
    def get_cognito_config(self) -> dict:
        """Get Cognito configuration as dictionary"""
        return {
            'username': self.COGNITO_USERNAME,
            'temp_password': self.COGNITO_TEMP_PASSWORD,
            'permanent_password': self.COGNITO_PERMANENT_PASSWORD
        }
    
    def get_sop_files(self) -> list:
        """Get list of SOP files to upload"""
        import os
        import glob
        
        # If specific files are configured
        if self.SOP_FILES:
            return [f.strip() for f in self.SOP_FILES.split(',')]
        
        # Look for PDFs in SOP directory
        if os.path.exists(self.SOP_DIRECTORY):
            return glob.glob(os.path.join(self.SOP_DIRECTORY, '*.pdf'))
        
        # Fallback: look for any PDF in current directory
        pdf_files = glob.glob('*.pdf')
        return pdf_files
    
    def get_sap_api_files(self) -> list:
        """Get list of SAP API documentation files to upload"""
        import os
        import glob
        
        # If specific files are configured
        if self.SAP_API_FILES:
            return [f.strip() for f in self.SAP_API_FILES.split(',')]
        
        # Look for all files in SAP API directory
        if os.path.exists(self.SAP_API_DIRECTORY):
            files = []
            files.extend(glob.glob(os.path.join(self.SAP_API_DIRECTORY, '*.pdf')))
            files.extend(glob.glob(os.path.join(self.SAP_API_DIRECTORY, '*.yaml')))
            files.extend(glob.glob(os.path.join(self.SAP_API_DIRECTORY, '*.yml')))
            return files
        
        return []

# Global configuration instance
config = Config()