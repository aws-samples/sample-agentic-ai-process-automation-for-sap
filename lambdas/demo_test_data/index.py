# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Test Data API Lambda

Creates AP three-way-match exception scenarios in SAP for testing the agent.
SAP-only — no DynamoDB writes. The odata_poller picks up created data naturally.

Routes:
  POST /test-data/ap-cases — create AP three-way match exception (PO + GR + blocked invoice)
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone

import boto3
import requests as http_requests

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ssm = boto3.client("ssm")
secretsmanager = boto3.client("secretsmanager")

ALLOWED_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:3000")
STACK_NAME = os.environ["STACK_NAME_BASE"]


def _cors_headers(origin: str) -> dict:
    allowed = [o.strip() for o in ALLOWED_ORIGINS.split(",")]
    if origin in allowed:
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
        }
    return {}


def _response(status_code: int, body: object, origin: str = "") -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json", **_cors_headers(origin)},
        "body": json.dumps(body),
    }


def _get_sap_config() -> tuple[str, tuple[str, str]]:
    """Return (base_url, (username, password)) from Secrets Manager."""
    secret_arn = ssm.get_parameter(Name=f"/{STACK_NAME}/secrets/sap-credentials-arn")[
        "Parameter"
    ]["Value"]
    creds = json.loads(
        secretsmanager.get_secret_value(SecretId=secret_arn)["SecretString"]
    )
    # Callers below append the OData service root, so strip it if the secret
    # carries it — otherwise every URL doubles the path. Mirrors the sap_auth
    # layer's normalize_base_url (not imported: this Lambda has no layer).
    base_url = re.sub(
        r"/sap/opu/odata/sap/?$", "", creds["base_url"].strip(), flags=re.IGNORECASE
    ).rstrip("/")
    return base_url, (creds["username"], creds["password"])


def _get_csrf_token(base_url: str, auth: tuple) -> tuple:
    """Fetch CSRF token from SAP."""
    url = f"{base_url}/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/"
    resp = http_requests.get(
        url,
        auth=auth,
        headers={"X-CSRF-Token": "Fetch", "Accept": "application/json"},
        timeout=15,
    )
    if resp.status_code == 200:
        return resp.headers.get("X-CSRF-Token"), resp.cookies
    raise RuntimeError(f"CSRF token fetch failed: {resp.status_code}")


def _safe_posting_date_ms() -> int:
    """Return last day of previous month as /Date(ms)/.

    SAP posting periods don't always include the current month — the previous
    month is the safest bet since it's almost always open for late postings.
    """
    first_of_month = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    last_of_prev = first_of_month - timedelta(days=1)
    return int(last_of_prev.timestamp() * 1000)


def _document_date_ms(days_ago: int = 30) -> int:
    """Return a realistic document date N days in the past."""
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(dt.timestamp() * 1000)


def _safe_fiscal_year() -> str:
    """Fiscal year matching the safe posting date (previous month)."""
    first_of_month = datetime.now(timezone.utc).replace(day=1)
    last_of_prev = first_of_month - timedelta(days=1)
    return str(last_of_prev.year)


def _create_po(base_url, auth, amount, quantity=1):
    """Create a cost-center PO in SAP. Returns po_number or raises."""
    csrf_token, cookies = _get_csrf_token(base_url, auth)
    unit_price = round(amount / quantity, 2)

    po_data = {
        "PurchaseOrderType": "NB",
        "Supplier": "USSU-VSF04",
        "PurchasingOrganization": "1710",
        "PurchasingGroup": "002",
        "CompanyCode": "1710",
        "DocumentCurrency": "USD",
        "PaymentTerms": "0002",
        "Language": "EN",
        "to_PurchaseOrderItem": [
            {
                "PurchaseOrderItem": "10",
                "Material": "MZ-RM-R300-01",
                "OrderQuantity": str(quantity),
                "PurchaseOrderQuantityUnit": "PC",
                "NetPriceAmount": str(unit_price),
                "Plant": "1710",
                "MaterialGroup": "ZFRAME",
                "AccountAssignmentCategory": "K",
                "GoodsReceiptIsExpected": True,
                "InvoiceIsExpected": True,
                "to_AccountAssignment": [
                    {
                        "AccountAssignmentNumber": "1",
                        "CostCenter": "17100100",
                    }
                ],
            }
        ],
    }

    url = f"{base_url}/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder"
    resp = http_requests.post(
        url,
        auth=auth,
        json=po_data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-CSRF-Token": csrf_token,
        },
        cookies=cookies,
        timeout=30,
    )

    if resp.status_code != 201:
        raise RuntimeError(
            f"SAP PO creation failed ({resp.status_code}): {resp.text[:500]}"
        )

    return resp.json()["d"]["PurchaseOrder"]


def _create_goods_receipt(base_url, auth, po_number, quantity=1):
    """Post a goods receipt (mvt 101) against a PO. Returns material_document number."""
    csrf_url = f"{base_url}/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV/"
    csrf_resp = http_requests.get(
        csrf_url,
        auth=auth,
        headers={"X-CSRF-Token": "Fetch", "Accept": "application/json"},
        timeout=15,
    )
    if csrf_resp.status_code != 200:
        raise RuntimeError(f"GR CSRF token fetch failed: {csrf_resp.status_code}")
    csrf_token = csrf_resp.headers.get("X-CSRF-Token")
    cookies = csrf_resp.cookies

    gr_data = {
        "GoodsMovementCode": "01",
        "DocumentDate": f"/Date({_document_date_ms(7)})/",
        "PostingDate": f"/Date({_safe_posting_date_ms()})/",
        "MaterialDocumentHeaderText": f"GR for PO {po_number}",
        "to_MaterialDocumentItem": {
            "results": [
                {
                    "Material": "MZ-RM-R300-01",
                    "Plant": "1710",
                    "StorageLocation": "171A",
                    "GoodsMovementType": "101",
                    "PurchaseOrder": po_number,
                    "PurchaseOrderItem": "10",
                    "GoodsMovementRefDocType": "B",
                    "QuantityInEntryUnit": str(quantity),
                    "EntryUnit": "PC",
                }
            ]
        },
    }

    url = f"{base_url}/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV/A_MaterialDocumentHeader"
    resp = http_requests.post(
        url,
        auth=auth,
        json=gr_data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-CSRF-Token": csrf_token,
        },
        cookies=cookies,
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"GR creation failed ({resp.status_code}): {resp.text[:500]}"
        )

    try:
        return resp.json()["d"]["MaterialDocument"]
    except (json.JSONDecodeError, KeyError):
        return "CREATED"


def _create_invoice(
    base_url, auth, po_number, invoice_amount, payment_block="", quantity="1"
):
    """Create a supplier invoice for a specific amount. Returns invoice_number.

    Args:
        payment_block: SAP PaymentBlockingReason code. '' = no block,
                       'R' = invoice verification, 'B' = manual payment block.
    """
    csrf_url = f"{base_url}/sap/opu/odata/sap/API_SUPPLIERINVOICE_PROCESS_SRV/"
    csrf_resp = http_requests.get(
        csrf_url,
        auth=auth,
        headers={"X-CSRF-Token": "Fetch", "Accept": "application/json"},
        timeout=15,
    )
    if csrf_resp.status_code != 200:
        raise RuntimeError(f"Invoice CSRF token fetch failed: {csrf_resp.status_code}")
    csrf_token = csrf_resp.headers.get("X-CSRF-Token")
    cookies = csrf_resp.cookies

    posting_ms = _safe_posting_date_ms()
    doc_ms = _document_date_ms(14)
    fiscal_year = _safe_fiscal_year()

    invoice_data = {
        "SupplierInvoice": "",
        "FiscalYear": fiscal_year,
        "CompanyCode": "1710",
        "DocumentDate": f"/Date({doc_ms})/",
        "PostingDate": f"/Date({posting_ms})/",
        "SupplierInvoiceIDByInvcgParty": f"INV-{po_number[-6:]}",
        "InvoicingParty": "USSU-VSF04",
        "DocumentCurrency": "USD",
        "InvoiceGrossAmount": str(invoice_amount),
        **({"PaymentBlockingReason": payment_block} if payment_block else {}),
        "to_SuplrInvcItemPurOrdRef": [
            {
                "SupplierInvoiceItem": "1",
                "PurchaseOrder": po_number,
                "PurchaseOrderItem": "10",
                "Plant": "1710",
                "TaxCode": "",
                "DocumentCurrency": "USD",
                "SupplierInvoiceItemAmount": str(invoice_amount),
                "PurchaseOrderQuantityUnit": "PC",
                "QuantityInPurchaseOrderUnit": str(quantity),
            }
        ],
    }

    url = f"{base_url}/sap/opu/odata/sap/API_SUPPLIERINVOICE_PROCESS_SRV/A_SupplierInvoice"
    resp = http_requests.post(
        url,
        auth=auth,
        json=invoice_data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-CSRF-Token": csrf_token,
        },
        cookies=cookies,
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"Invoice creation failed ({resp.status_code}): {resp.text[:500]}"
        )

    try:
        return resp.json()["d"]["SupplierInvoice"]
    except (json.JSONDecodeError, KeyError):
        # Some SAP versions return 201 with minimal body
        return "CREATED"


def _handle_create_ap(event: dict, origin: str) -> dict:
    """POST /test-data/ap-cases — create AP three-way match exception in SAP.

    Creates a PO, optionally posts a goods receipt, then creates a blocked
    invoice. Supports price variance (invoice_amount != po_amount) and
    quantity variance (invoice_quantity != po_quantity).
    """
    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        return _response(400, {"error": "Invalid JSON body"}, origin)

    po_amount = body.get("po_amount")
    if not po_amount or not isinstance(po_amount, (int, float)) or po_amount <= 0:
        return _response(
            400, {"error": "po_amount is required and must be > 0"}, origin
        )

    invoice_amount = body.get("invoice_amount", po_amount)
    payment_block = body.get("payment_block", "R")
    scenario_name = body.get("scenario_name", "")
    skip_gr = body.get("skip_gr", False)
    po_quantity = body.get("po_quantity", 1)
    invoice_quantity = body.get("invoice_quantity", po_quantity)
    gr_quantity = body.get("gr_quantity", po_quantity)

    price_variance = (
        round(invoice_amount - po_amount, 2) if invoice_amount != po_amount else 0
    )
    qty_variance = invoice_quantity - gr_quantity if not skip_gr else 0

    try:
        base_url, auth = _get_sap_config()
    except Exception as e:
        logger.exception("Failed to get SAP config")
        return _response(500, {"error": f"SAP config error: {e}"}, origin)

    result = {
        "domain": "finance_ap",
        "scenario_name": scenario_name,
        "po_amount": po_amount,
        "invoice_amount": invoice_amount,
        "variance": price_variance,
        "payment_block": payment_block,
        "skip_gr": skip_gr,
        "po_quantity": po_quantity,
        "invoice_quantity": invoice_quantity,
        "gr_quantity": gr_quantity,
        "qty_variance": qty_variance,
    }

    try:
        po_number = _create_po(base_url, auth, po_amount, quantity=po_quantity)
        result["po_number"] = po_number
    except Exception as e:
        logger.exception("PO creation failed")
        return _response(
            500, {"error": f"PO creation failed: {e}", "result": result}, origin
        )

    if not skip_gr:
        try:
            time.sleep(2)
            gr_doc = _create_goods_receipt(
                base_url, auth, po_number, quantity=gr_quantity
            )
            result["gr_document"] = gr_doc
        except Exception as e:
            logger.warning("GR creation failed (non-fatal): %s", e)
            result["gr_document"] = None
            result["gr_error"] = str(e)
    else:
        result["gr_document"] = None

    try:
        time.sleep(3)
        inv_number = _create_invoice(
            base_url,
            auth,
            po_number,
            invoice_amount,
            payment_block,
            quantity=invoice_quantity,
        )
        result["invoice_number"] = inv_number
    except Exception as e:
        logger.exception("Invoice creation failed")
        result["invoice_number"] = None
        result["invoice_error"] = str(e)

    return _response(201, result, origin)


def handler(event: dict, context: object) -> dict:
    method = event.get("httpMethod", "")
    path = event.get("path", "")
    origin = (event.get("headers") or {}).get("origin", "")

    logger.info("Request: %s %s", method, path)

    if method == "OPTIONS":
        return _response(200, {}, origin)

    try:
        if method == "POST" and "ap-cases" in path:
            return _handle_create_ap(event, origin)

        return _response(404, {"error": "Not found"}, origin)

    except Exception as e:
        logger.exception("Test data API error")
        return _response(500, {"error": str(e)}, origin)
