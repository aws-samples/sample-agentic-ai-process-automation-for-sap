<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# SAP API Integration Guide
## Tooling Accrual Process

This guide covers the essential SAP API calls needed for the tooling accrual automation process based on our working scripts.

## CRITICAL: SAP Base URL Configuration

**SAP System Base URL**: Configured via `sap.base_url` in `cdk/config.yaml` (referred to as `{BASE_URL}` below)

**IMPORTANT URL CONSTRUCTION RULES:**
1. **Always use COMPLETE URLs** when calling SAP OData APIs
2. **Format**: `{BASE_URL}/sap/opu/odata/sap/[SERVICE_NAME]/[ENTITY]`
3. **NEVER use relative paths** (e.g., `/sap/opu/odata/...`) - always include the full `https://` URL
4. **NEVER add trailing slashes** after query parameters
5. **Query parameters** should use `&$format=json` (no trailing slash)

**Correct Examples:**
- ✅ `{BASE_URL}/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder('4500002163')?$format=json`
- ✅ `{BASE_URL}/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrderScheduleLine?$filter=PurchasingDocument eq '4500002163'&$format=json`

**Incorrect Examples:**
- ❌ `/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder('4500002163')?$format=json` (missing base URL)
- ❌ `{BASE_URL}/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder('4500002163')?$format=json/` (trailing slash)
- ❌ `https://s4hana.example.com/sap/opu/odata/...` (wrong hostname)

## 1. Get PO Master Data

**Purpose**: Retrieve PO details (amount, creation date)

**API**: `API_PURCHASEORDER_PROCESS_SRV`

**Working Example**:
```http
GET {BASE_URL}/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder('4500002162')?$expand=to_PurchaseOrderItem&$format=json
```

**Key Fields**:
- `PurchaseOrder`: PO Number
- `PurchaseOrderDate`: Creation date in `/Date(timestamp)/` format
- `to_PurchaseOrderItem.results[].NetPriceAmount`: Item amount
- `to_PurchaseOrderItem.results[].OrderQuantity`: Item quantity

**Sample Response**:
```json
{
  "d": {
    "PurchaseOrder": "4500002162",
    "PurchaseOrderDate": "/Date(1700697600000)/",
    "to_PurchaseOrderItem": {
      "results": [{
        "PurchaseOrderItem": "10",
        "NetPriceAmount": "400000.00",
        "OrderQuantity": "1.000",
        "PurchaseOrderQuantityUnit": "PC"
      }]
    }
  }
}
```

## 2. Get Schedule Line Details

**Purpose**: Retrieve delivery dates from PO schedule lines

**API**: `API_PURCHASEORDER_PROCESS_SRV`

**Sample Call**:
```http
GET {BASE_URL}/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrderScheduleLine?$filter=PurchasingDocument eq '4500002068'&$format=json
```

**Key Fields**:
- `PurchasingDocument`: PO Number
- `PurchasingDocumentItem`: Line item
- `ScheduleLineDeliveryDate`: Scheduled delivery date
- `ScheduleLineOrderQuantity`: Quantity

**Sample Response**:
```json
{
  "results": [{
    "PurchasingDocument": "4500002068",
    "PurchasingDocumentItem": "10",
    "ScheduleLineDeliveryDate": "/Date(1703289600000)/",
    "ScheduleLineOrderQuantity": "1.000"
  }]
}
```

## 3. Update Delivery Date

**Purpose**: Update delivery date in schedule lines after PO owner response

**API**: `API_PURCHASEORDER_PROCESS_SRV`

**Sample Call**:
```http
PATCH /sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrderScheduleLine(PurchasingDocument='4500002068',PurchasingDocumentItem='10',ScheduleLine='0001')

Content-Type: application/json
X-CSRF-Token: {csrf_token}

{
  "ScheduleLineDeliveryDate": "/Date(1735689600000)/"
}
```

**Process**:
1. Get CSRF token first
2. Get schedule lines using `PurchasingDocument` filter
3. Parse new date from email (YYYY-MM-DD)
4. Convert to SAP date format: `/Date(timestamp)/`
5. Update schedule line using correct field names

**For example Reliable Python Implementation with Error Handling**:
```python
def update_delivery_date_reliable(po_number, new_date_str, max_retries=3):
    """Reliable delivery date update with error handling and retries"""
    
    for attempt in range(max_retries):
        try:
            # Step 1: Get fresh CSRF token
            csrf_token, cookies = get_csrf_token(base_url, auth)
            if not csrf_token:
                print(f"Attempt {attempt + 1}: Failed to get CSRF token")
                continue
            
            # Step 2: Query schedule lines to get actual data
            query_url = f"{base_url}/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrderScheduleLine"
            params = {'$filter': f"PurchasingDocument eq '{po_number}'", '$format': 'json'}
            
            response = requests.get(query_url, auth=auth, params=params, timeout=15)
            
            if response.status_code != 200:
                print(f"Attempt {attempt + 1}: Failed to query schedule lines: {response.status_code}")
                continue
            
            schedule_lines = response.json()['d']['results']
            if not schedule_lines:
                print(f"No schedule lines found for PO {po_number}")
                return False
            
            # Step 3: Extract schedule line details
            schedule_line = schedule_lines[0]
            po_item = schedule_line['PurchasingDocumentItem']
            schedule_line_num = schedule_line['ScheduleLine']
            
            # Step 4: Convert date to timestamp
            new_date = datetime.strptime(new_date_str, '%Y-%m-%d')
            timestamp = int(new_date.timestamp() * 1000)
            
            # Step 5: Build update URL with proper encoding
            update_url = f"{base_url}/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrderScheduleLine(PurchasingDocument='{po_number}',PurchasingDocumentItem='{po_item}',ScheduleLine='{schedule_line_num}')"
            
            update_data = {"ScheduleLineDeliveryDate": f"/Date({timestamp})/"}
            
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-CSRF-Token': csrf_token
            }
            
            # Step 6: Execute update with timeout
            update_response = requests.patch(update_url, auth=auth, json=update_data, 
                                           headers=headers, cookies=cookies, timeout=30)
            
            if update_response.status_code == 204:
                print(f"✅ Successfully updated delivery date to {new_date_str}")
                return True
            else:
                print(f"Attempt {attempt + 1}: Update failed - {update_response.status_code}")
                if "Malformed URI" in update_response.text:
                    print("URI encoding issue - manual intervention required")
                    return False
                    
        except requests.exceptions.Timeout:
            print(f"Attempt {attempt + 1}: Request timeout")
        except Exception as e:
            print(f"Attempt {attempt + 1}: Error: {e}")
        
        # Wait before retry
        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)
    
    return False

def get_csrf_token(base_url, auth):
    """Get fresh CSRF token"""
    try:
        url = f"{base_url}/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/"
        headers = {'X-CSRF-Token': 'Fetch', 'Accept': 'application/json'}
        response = requests.get(url, auth=auth, headers=headers, timeout=10)
        
        if response.status_code == 200:
            return response.headers.get('X-CSRF-Token'), response.cookies
        return None, None
    except Exception:
        return None, None
```

## 4. Get Invoice Details

**Purpose**: Retrieve invoiced amounts for accrual calculation

**API**: `API_SUPPLIERINVOICE_PROCESS_SRV`

**Working Example**:
```http
GET /sap/opu/odata/sap/API_SUPPLIERINVOICE_PROCESS_SRV/A_SuplrInvcItemPurOrdRef?$filter=PurchaseOrder eq '4500002162'&$format=json
```

**Key Fields**:
- `PurchaseOrder`: PO Number
- `SupplierInvoice`: Invoice number
- `SupplierInvoiceItemAmount`: Invoiced amount
- `DocumentCurrency`: Currency

**Sample Response**:
```json
{
  "d": {
    "results": [{
      "PurchaseOrder": "4500002162",
      "SupplierInvoice": "5100001548",
      "SupplierInvoiceItem": "1",
      "SupplierInvoiceItemAmount": "240000.00",
      "DocumentCurrency": "USD"
    }]
  }
}
```



## 5. Get Account Assignment (WBS/Cost Center)

**Purpose**: Retrieve WBS elements and cost centers for workflow decisions

**API**: `API_PURCHASEORDER_PROCESS_SRV`

**Working Example**:
```http
GET /sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurOrdAccountAssignment?$filter=PurchaseOrder eq '4500002162'&$format=json
```

**Key Fields**:
- `PurchaseOrder`: PO Number
- `WBSElement`: Project WBS (for PROJECT_MILESTONE workflow)
- `CostCenter`: Cost center assignment
- `GLAccount`: GL account assignment

**Sample Response**:
```json
{
  "d": {
    "results": [{
      "PurchaseOrder": "4500002162",
      "PurchaseOrderItem": "10",
      "WBSElement": "ONG.004",
      "CostCenter": "17100100",
      "GLAccount": "1011000"
    }]
  }
}
```





## Business Logic Implementation

### Workflow Decision Logic
- PO > $300K → EMAIL_INQUIRY
- PO ≥ $150K with WBS → PROJECT_MILESTONE
- PO ≥ $150K without WBS → EMAIL_INQUIRY
- PO < $150K → DELIVERY_DATE

### Accrual Calculation Formula
- Monthly Rate = PO Amount / Duration Months
- Accrual Balance = Invoiced Amount - Paid Amount
- Duration calculated from start date to end date

### Date Handling
- SAP Format: `/Date(timestamp)/`
- Input Format: YYYY-MM-DD
- Convert timestamp to milliseconds for SAP

### Error Handling
- Always check for HTTP status codes
- Handle SAP-specific error responses
- Include error details in email notifications
- Validate date formats before API calls
- Handle JSON parsing errors for empty responses
- Use correct field names (PurchasingDocument, not PurchaseOrder)
- Add timeout handling for API calls
- Include CSRF token refresh logic for long-running processes
- Implement retry mechanisms for transient failures
- Use proper URL encoding for OData entity keys
- Validate schedule line data exists before updates

**Common Error Scenarios & Solutions**:

| Error | Cause | Solution |
|-------|-------|----------|
| **HTTP 400 "Malformed URI"** | Single quotes in URL not encoded | Use proper URL encoding |
| **HTTP 403 CSRF Token** | Expired or missing token | Get fresh token before each operation |
| **HTTP 404 Entity Not Found** | Wrong PO/Item/ScheduleLine values | Query schedule lines first |
| **HTTP 500 SAP System Error** | SAP system overload | Implement retry with backoff |
| **Timeout Errors** | SAP system slow response | Increase timeout to 30+ seconds |
| **Empty Schedule Lines** | PO has no delivery schedule | Validate PO creation included schedules |

**AI Agent Reliability Tips**:
- Always get fresh CSRF token before updates
- Query schedule lines first to get actual values
- Implement retry logic with exponential backoff
- Use 30+ second timeouts for SAP API calls
- Validate responses before processing
- Handle URI encoding issues properly



## 6. Park Document (Tooling Accrual)

**Purpose**: Create parked journal entries for tooling accruals

**API**: `ZACC_DOC_SRV` (Custom OData Service)

**Service URL**: `/sap/opu/odata/sap/ZACC_DOC_SRV`

### Authentication & CSRF Token

**Step 1: Get CSRF Token**
```http
GET /sap/opu/odata/sap/ZACC_DOC_SRV/$metadata
Authorization: Basic {credentials}
X-CSRF-Token: Fetch
```

**Response Headers**:
```
X-CSRF-Token: {csrf_token_value}
Set-Cookie: {session_cookies}
```

### Service Metadata

**Entity**: `parkDocument`

**Required Fields**:
- `amt_doccur`: Amount (string) - **REQUIRED**
- `ref_doc_no`: Reference PO number (string) - **REQUIRED**

**Optional Fields** (with defaults):
- `currency`: Currency code (default: "USD")
- `curr_type`: Currency type (default: "00")
- `itemno_acc`: Line item number (default: "0001")
- `doc_status`: Document status (default: "2" = Parked)
- `doc_type`: Document type (default: "KR" = Vendor Invoice)
- `pstng_date`: Posting date (default: current date)
- `trans_date`: Transaction date (default: current date)
- `doc_date`: Document date (default: current date)
- `comp_code`: Company code (default: "1710")
- `header_txt`: Header text (default: "Tooling Accrual")
- `username`: User name (default: current user)
- `vendor_no`: Vendor number (default: "USSU-VSF04")
- `bus_act`: Business activity (default: "RFBV")

### API Call Examples

**Minimal Call** (Required fields only):
```http
POST /sap/opu/odata/sap/ZACC_DOC_SRV/parkDocumentSet
Content-Type: application/json
Authorization: Basic {credentials}
X-CSRF-Token: {csrf_token}
Cookie: {session_cookies}

{
  "amt_doccur": "100000.00",
  "ref_doc_no": "4500002068"
}
```

**Full Call** (All fields specified):
```http
POST /sap/opu/odata/sap/ZACC_DOC_SRV/parkDocumentSet
Content-Type: application/json
Authorization: Basic {credentials}
X-CSRF-Token: {csrf_token}
Cookie: {session_cookies}

{
  "amt_doccur": "100000.00",
  "currency": "USD",
  "curr_type": "00",
  "itemno_acc": "0001",
  "doc_status": "2",
  "ref_doc_no": "4500002068",
  "doc_type": "KR",
  "pstng_date": "2025-01-15",
  "trans_date": "2025-01-15",
  "doc_date": "2025-01-15",
  "comp_code": "1710",
  "header_txt": "Tooling Accrual - PO 4500002068",
  "vendor_no": "USSU-VSF04",
  "bus_act": "RFBV"
}
```

### Response Handling

**Success Response** (HTTP 201):
```json
{
  "d": {
    "__metadata": {
      "id": "https://...parkDocumentSet(itemno_acc='0001',ref_doc_no='4500002068')",
      "uri": "https://...parkDocumentSet(itemno_acc='0001',ref_doc_no='4500002068')",
      "type": "ZACC_DOC_SRV.parkDocument"
    },
    "amt_doccur": "100000.00",
    "currency": "USD",
    "curr_type": "00",
    "itemno_acc": "0001",
    "doc_status": "2",
    "ref_doc_no": "4500002068",
    "doc_type": "KR",
    "pstng_date": "2025-01-15",
    "trans_date": "2025-01-15",
    "doc_date": "2025-01-15",
    "comp_code": "1710",
    "header_txt": "Tooling Accrual - PO 4500002068",
    "username": "SAP_SERVICE_USER",
    "vendor_no": "USSU-VSF04",
    "message": "Document parked: 1900000001",
    "bus_act": "RFBV"
  }
}
```

**Error Response** (HTTP 400):
```json
{
  "d": {
    "amt_doccur": "100000.00",
    "ref_doc_no": "",
    "message": "ERROR: Reference document number is required"
  }
}
```

### Extract Document Number

Extract document number from response message: "Document parked: 1900000001"

### Error Handling

**Validation Errors**:
- Missing `amt_doccur`: "ERROR: Amount is required"
- Missing `ref_doc_no`: "ERROR: Reference document number is required"

**SAP BAPI Errors**:
- GL Account issues: "ERROR: G/L account not defined in chart of accounts"
- Vendor issues: "ERROR: Vendor does not exist"
- Authorization issues: "ERROR: No authorization for transaction"

**HTTP Status Codes**:
- `201`: Success - Document parked
- `400`: Bad Request - Validation error
- `403`: Forbidden - CSRF token or authorization error
- `500`: Internal Server Error - SAP system error

### Integration Process

1. Get CSRF token from metadata endpoint
2. POST to parkDocumentSet with required fields
3. Extract document number from response message
4. Handle success/error responses appropriately

### Journal Entry Created

The service creates the following accounting entry:
- **Dr. 11001000** (Tooling Asset): Amount
- **Cr. Vendor Account** (USSU-VSF04): Amount
- **Cost Center**: 17100100
- **Reference**: PO Number
- **Status**: Parked (ready for approval)

