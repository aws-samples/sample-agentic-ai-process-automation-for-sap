# SAP API Integration Guide

## Invoice Exception Handling Process

This guide covers the essential SAP API calls needed for the invoice exception handling automation process based on our working scripts.

## CRITICAL: SAP Base URL Configuration

**SAP System Base URL**: `https://your-sap-system.com`

**IMPORTANT URL CONSTRUCTION RULES:**

1. **Always use COMPLETE URLs** when calling SAP OData APIs
2. **Format**: `https://your-sap-system.com/sap/opu/odata/sap/[SERVICE_NAME]/[ENTITY]`
3. **NEVER use relative paths** (e.g., `/sap/opu/odata/...`) - always include the full `https://` URL
4. **NEVER add trailing slashes** after query parameters
5. **Query parameters** should use `&$format=json` (no trailing slash)

**Correct Examples:**
- ✅ `https://your-sap-system.com/sap/opu/odata/sap/API_SUPPLIERINVOICE_PROCESS_SRV/A_SupplierInvoice('1900000002')?$format=json`
- ✅ `https://your-sap-system.com/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder?$filter=PurchaseOrder eq '4500002163'&$format=json`

**Incorrect Examples:**
- ❌ `/sap/opu/odata/sap/API_SUPPLIERINVOICE_PROCESS_SRV/A_SupplierInvoice('1900000002')?$format=json` (missing base URL)
- ❌ `https://your-sap-system.com/sap/opu/odata/sap/API_SUPPLIERINVOICE_PROCESS_SRV/A_SupplierInvoice('1900000002')?$format=json/` (trailing slash)

## 1. Get Blocked Invoice Details

**Purpose**: Retrieve blocked supplier invoice details for exception handling

**API**: `API_SUPPLIERINVOICE_PROCESS_SRV`

**Working Example**:
```http
GET https://your-sap-system.com/sap/opu/odata/sap/API_SUPPLIERINVOICE_PROCESS_SRV/A_SupplierInvoice('1900000002')?$format=json
```

**Key Fields**:
- `SupplierInvoice`: Invoice number
- `FiscalYear`: Fiscal year
- `DocumentDate`: Invoice document date
- `PostingDate`: Posting date
- `SupplierInvoiceIDByInvcgParty`: External invoice reference
- `InvoicingParty`: Supplier number
- `DocumentCurrency`: Currency
- `InvoiceGrossAmount`: Total invoice amount
- `PaymentBlockingReason`: Blocking reason code (e.g., "A", "B", "C")
- `SupplierInvoiceStatus`: Invoice status

**Sample Response**:
```json
{
  "d": {
    "SupplierInvoice": "1900000002",
    "FiscalYear": "2021",
    "DocumentDate": "/Date(1636070400000)/",
    "PostingDate": "/Date(1636070400000)/",
    "SupplierInvoiceIDByInvcgParty": "INV2022",
    "InvoicingParty": "17300081",
    "DocumentCurrency": "USD",
    "InvoiceGrossAmount": "200.00",
    "PaymentBlockingReason": "A",
    "SupplierInvoiceStatus": "Blocked"
  }
}
```

## 2. Get Purchase Order Details

**Purpose**: Retrieve PO details for 3-way matching validation

**API**: `API_PURCHASEORDER_PROCESS_SRV`

**Working Example**:
```http
GET https://your-sap-system.com/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder('4500002162')?$expand=to_PurchaseOrderItem&$format=json
```

**Key Fields**:
- `PurchaseOrder`: PO Number
- `PurchaseOrderDate`: Creation date
- `Supplier`: Supplier number
- `to_PurchaseOrderItem.results[].NetPriceAmount`: Item amount
- `to_PurchaseOrderItem.results[].OrderQuantity`: Item quantity
- `to_PurchaseOrderItem.results[].PurchaseOrderQuantityUnit`: Unit of measure

**Sample Response**:
```json
{
  "d": {
    "PurchaseOrder": "4500002162",
    "PurchaseOrderDate": "/Date(1700697600000)/",
    "Supplier": "17300081",
    "to_PurchaseOrderItem": {
      "results": [
        {
          "PurchaseOrderItem": "10",
          "Material": "TG11",
          "NetPriceAmount": "200.00",
          "OrderQuantity": "1.000",
          "PurchaseOrderQuantityUnit": "PC"
        }
      ]
    }
  }
}
```

## 3. Get Goods Receipt Details

**Purpose**: Retrieve goods receipt information for 3-way matching

**API**: `API_MATERIAL_DOCUMENT`

**Working Example**:
```http
GET https://your-sap-system.com/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV/A_MaterialDocumentHeader?$filter=PurchaseOrder eq '4500002162'&$expand=to_MaterialDocumentItem&$format=json
```

**Key Fields**:
- `MaterialDocument`: Goods receipt number
- `MaterialDocumentYear`: Fiscal year
- `PostingDate`: GR posting date
- `to_MaterialDocumentItem.results[].PurchaseOrder`: PO number
- `to_MaterialDocumentItem.results[].QuantityInEntryUnit`: Received quantity
- `to_MaterialDocumentItem.results[].Material`: Material number

**Sample Response**:
```json
{
  "d": {
    "results": [
      {
        "MaterialDocument": "4900000123",
        "MaterialDocumentYear": "2021",
        "PostingDate": "/Date(1636070400000)/",
        "to_MaterialDocumentItem": {
          "results": [
            {
              "PurchaseOrder": "4500002162",
              "PurchaseOrderItem": "10",
              "Material": "TG11",
              "QuantityInEntryUnit": "1.000",
              "EntryUnit": "PC"
            }
          ]
        }
      }
    ]
  }
}
```

## 4. Create Goods Receipt (Missing GR Scenario)

**Purpose**: Create goods receipt when invoice is received but GR is missing

**API**: `API_MATERIAL_DOCUMENT_SRV`

**✅ VERIFIED WORKING EXAMPLE**:
```http
POST https://your-sap-system.com/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV/A_MaterialDocumentHeader
Content-Type: application/json
X-CSRF-Token: {csrf_token}

{
  "GoodsMovementCode": "01",
  "PostingDate": "/Date(1731628800000)/",
  "DocumentDate": "/Date(1731628800000)/",
  "MaterialDocumentHeaderText": "GR for PO 4500002254",
  "to_MaterialDocumentItem": {
    "results": [
      {
        "Material": "MZ-RM-R300-01",
        "Plant": "1710",
        "StorageLocation": "171C",
        "GoodsMovementType": "101",
        "PurchaseOrder": "4500002254",
        "PurchaseOrderItem": "10",
        "GoodsMovementRefDocType": "B",
        "QuantityInEntryUnit": "1",
        "EntryUnit": "PC"
      }
    ]
  }
}
```

**Key Fields**:
- `GoodsMovementCode`: "01" for goods receipt
- `GoodsMovementType`: "101" for GR for purchase order
- `GoodsMovementRefDocType`: "B" for purchase order reference (REQUIRED)
- `PostingDate` and `DocumentDate`: SAP date format `/Date(milliseconds)/` - use allowed posting periods
- `to_MaterialDocumentItem.results`: Array of line items

**IMPORTANT NOTES**:
- **Date Format**: Must use `/Date(milliseconds)/` format (not ISO 8601)
- **Posting Period**: Ensure date falls within allowed posting periods (check SAP fiscal calendar)
- **GoodsMovementRefDocType**: Field "B" is REQUIRED for PO-based goods receipts
- **Wait Time**: Allow 2-3 seconds after PO creation before creating GR

**Process**:
1. Get CSRF token first
2. Validate PO exists and has open quantity
3. Ensure posting date is within allowed period
4. Create goods receipt with movement type 101
5. Extract material document number from response

**Sample Success Response**:
```json
{
  "d": {
    "MaterialDocument": "5000002852",
    "MaterialDocumentYear": "2025",
    "PostingDate": "/Date(1731628800000)/",
    "MaterialDocumentHeaderText": "GR for PO 4500002254"
  }
}
```

## 5. Release Blocked Invoice

**Purpose**: Remove payment block from supplier invoice after validation

**API**: `API_SUPPLIERINVOICE_PROCESS_SRV`

**Standard API Call (may require additional parameters)**:
```http
POST https://your-sap-system.com/sap/opu/odata/sap/API_SUPPLIERINVOICE_PROCESS_SRV/Release?SupplierInvoice='5100000131'&FiscalYear='2025'
X-CSRF-Token: {csrf_token}
```

**Important Notes**:
- This is a **Function Import** operation (POST method with query parameters)
- **NOT a PATCH operation** on the entity
- Query parameters must be enclosed in single quotes
- No request body required for standard implementation


**Process**:
1. Get CSRF token
2. Validate 3-way match is complete
3. Attempt Release function import with invoice number and fiscal year
4. If successful, verify Success=true in response
5. If failed, fall back to manual process or workflow

**Sample Success Response** (if Release works):
```json
{
  "d": {
    "Release": {
      "__metadata": {
        "type": "API_SUPPLIERINVOICE_PROCESS_SRV.ReleaseInvoiceExportParameters"
      },
      "Success": true
    }
  }
}
```

## 6. Query Invoice Line Items

**Purpose**: Get detailed line item information for invoice validation

**API**: `API_SUPPLIERINVOICE_PROCESS_SRV`

**Working Example**:
```http
GET https://your-sap-system.com/sap/opu/odata/sap/API_SUPPLIERINVOICE_PROCESS_SRV/A_SuplrInvcItemPurOrdRef?$filter=SupplierInvoice eq '1900000002'&$format=json
```

**Key Fields**:
- `SupplierInvoice`: Invoice number
- `FiscalYear`: Fiscal year
- `SupplierInvoiceItem`: Line item number
- `PurchaseOrder`: Referenced PO
- `PurchaseOrderItem`: Referenced PO item
- `QuantityInPurchaseOrderUnit`: Invoiced quantity
- `SupplierInvoiceItemAmount`: Line item amount
- `DocumentCurrency`: Currency

**Sample Response**:
```json
{
  "d": {
    "results": [
      {
        "SupplierInvoice": "1900000002",
        "FiscalYear": "2021",
        "SupplierInvoiceItem": "1",
        "PurchaseOrder": "4500002162",
        "PurchaseOrderItem": "10",
        "QuantityInPurchaseOrderUnit": "1.000",
        "SupplierInvoiceItemAmount": "200.00",
        "DocumentCurrency": "USD"
      }
    ]
  }
}
```

## Business Logic Implementation

### Exception Type Handling

**Payment Blocking Reasons**:
- **"A"**: Price variance - Invoice amount doesn't match PO
- **"B"**: Quantity variance - Invoice quantity doesn't match GR
- **"C"**: Missing goods receipt - Invoice received before GR
- **"D"**: Duplicate invoice - Same invoice number already exists

### 3-Way Matching Validation

**Validation Steps**:
1. **PO Validation**: Verify PO exists and is not closed
2. **GR Validation**: Check if goods receipt exists for PO
3. **Price Match**: Compare invoice amount with PO amount (tolerance: ±5%)
4. **Quantity Match**: Compare invoice quantity with GR quantity
5. **Supplier Match**: Verify invoice supplier matches PO supplier

**Tolerance Rules**:
- Price variance ≤ 5%: Auto-release
- Price variance > 5%: Escalate to procurement
- Quantity variance: Escalate to receiving dock
- Missing GR: Create GR if delivery confirmed

### Resolution Workflows

**Scenario 1: Missing Goods Receipt**
1. Query PO to verify order details
2. Send email to receiving dock for delivery confirmation
3. If confirmed: Create goods receipt via API
4. Release invoice after GR creation

**Scenario 2: Price Variance**
1. Calculate variance percentage
2. If ≤ 5%: Auto-release with justification
3. If > 5%: Escalate to procurement for approval
4. Update invoice after approval

**Scenario 3: Quantity Variance**
1. Compare invoice quantity with GR quantity
2. Send email to receiving dock for verification
3. If partial delivery: Adjust invoice or create additional GR
4. Release invoice after resolution

### Date Handling

- **SAP Format**: `/Date(timestamp)/`
- **Input Format**: YYYY-MM-DD or ISO 8601
- **Convert timestamp to milliseconds** for SAP

### Error Handling

**Common Error Scenarios & Solutions**:

| Error | Cause | Solution |
|-------|-------|----------|
| **HTTP 400 "Malformed URI"** | Single quotes in URL not encoded | Use proper URL encoding |
| **HTTP 403 CSRF Token** | Expired or missing token | Get fresh token before each operation |
| **HTTP 404 Entity Not Found** | Wrong invoice/PO number | Validate entity exists first |
| **HTTP 500 SAP System Error** | SAP system overload | Implement retry with backoff |
| **Timeout Errors** | SAP system slow response | Increase timeout to 30+ seconds |
| **Payment block not cleared** | Workflow approval pending | Check approval status in SAP |

**AI Agent Reliability Tips**:
- Always get fresh CSRF token before updates
- Query entities first to validate they exist
- Implement retry logic with exponential backoff
- Use 30+ second timeouts for SAP API calls
- Validate responses before processing
- Handle URI encoding issues properly
- Log all API calls for audit trail

## CSRF Token Management

**Get CSRF Token**:
```http
GET https://your-sap-system.com/sap/opu/odata/sap/API_SUPPLIERINVOICE_PROCESS_SRV/
Authorization: Basic {credentials}
X-CSRF-Token: Fetch
```

**Response Headers**:
```
X-CSRF-Token: {csrf_token_value}
Set-Cookie: {session_cookies}
```

**Python Implementation**:
```python
def get_csrf_token(base_url, auth):
    """Get fresh CSRF token"""
    try:
        url = f"{base_url}/sap/opu/odata/sap/API_SUPPLIERINVOICE_PROCESS_SRV/"
        headers = {
            'X-CSRF-Token': 'Fetch',
            'Accept': 'application/json'
        }
        response = requests.get(url, auth=auth, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.headers.get('X-CSRF-Token'), response.cookies
        return None, None
    except Exception:
        return None, None
```
