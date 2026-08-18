#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Gate 4 SAP write test for the `entra-obo` auth profile.

Dials the isolated auth-verification MCP server directly with a human Entra token
(the OBO direct-MCP topology, so no Gateway and no Cedar policy in the path) and
performs an update against one purchase-order header field.

The test is built to be reversible and to fail loudly rather than leave SAP dirty:
capture before-state, write, verify, restore, verify the restore. `--discover`
stops after the read so the target field can be chosen from real metadata instead
of guessed.

Usage:
    python3 test-scripts/gate4-sap-write.py --discover     # read-only recon
    python3 test-scripts/gate4-sap-write.py --field NAME --value STR
    python3 test-scripts/gate4-sap-write.py --no-restore   # leave the change in place
"""

import argparse
import json
import os
import subprocess  # nosec B404 - fixed argv, no shell
import sys
import time
import uuid

import jwt
import requests

TENANT = "68a36f8c-e7a3-4e4d-b33b-9069169654c2"
SPA_CLIENT_ID = "ae4bcea0-1f31-4cc3-b7c4-2caab0944eb2"
OBO_APP_ID = "6cf13814-815d-47ff-87dc-75e786f6aeaf"
SCOPE = f"openid profile email offline_access api://{OBO_APP_ID}/SAP.Access"
STACK_BASE = os.environ.get("STACK_BASE", "erp-obo-v1")
REGION = os.environ.get("AWS_REGION", "us-east-1")
TEST_PO = os.environ.get("TEST_PO", "4500001940")
SERVICE = "API_PURCHASEORDER_PROCESS_SRV"
ENTITY = "A_PurchaseOrder"
TOKEN_CACHE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".gate4-token.json"
)

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))
    return ok


def jwt_claims(token):
    """Decode a JWT payload without verifying — inspection only, never for trust."""
    return jwt.decode(  # nosec  # nosemgrep: unverified-jwt-decode
        token, options={"verify_signature": False}
    )


def device_code_login(fresh=False):
    """Interactive human login, cached at mode 0600 in a gitignored dir."""
    if not fresh and os.path.exists(TOKEN_CACHE):
        with open(TOKEN_CACHE) as f:
            cached = json.load(f)
        if jwt_claims(cached["access_token"]).get("exp", 0) - 120 > time.time():
            return cached

    r = requests.post(
        f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/devicecode",
        data={"client_id": SPA_CLIENT_ID, "scope": SCOPE},
        timeout=30,
    )
    r.raise_for_status()
    d = r.json()
    print(f"\n>>> {d['message']}\n", flush=True)
    deadline = time.time() + d["expires_in"]
    while time.time() < deadline:
        time.sleep(d["interval"])
        t = requests.post(
            f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": SPA_CLIENT_ID,
                "device_code": d["device_code"],
            },
            timeout=30,
        ).json()
        if "access_token" in t:
            with open(TOKEN_CACHE, "w") as f:
                f.write(json.dumps(t))
            os.chmod(TOKEN_CACHE, 0o600)
            return t
        if t.get("error") != "authorization_pending":
            raise RuntimeError(f"device flow failed: {t.get('error')}")
    raise TimeoutError("device code expired")


def mcp_url():
    out = subprocess.run(  # nosec B603 - fixed argv
        [
            "aws",
            "ssm",
            "get-parameter",
            "--name",
            f"/{STACK_BASE}/mcp_invocation_url",
            "--region",
            REGION,
            "--query",
            "Parameter.Value",
            "--output",
            "text",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


class Mcp:
    """Minimal MCP streamable-HTTP client for an AgentCore runtime.

    The runtime answers a single JSON-RPC POST with either a JSON body or an SSE
    stream depending on the method, so both shapes are parsed.
    """

    def __init__(self, url, token):
        self.url = url
        self.token = token
        self.session = f"gate4wr{uuid.uuid4().hex}"[:40]
        self.mcp_session_id = None
        self._id = 0

    def _post(self, method, params=None, notify=False):
        self._id += 1
        body = {"jsonrpc": "2.0", "method": method}
        if not notify:
            body["id"] = self._id
        if params is not None:
            body["params"] = params
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": self.session,
        }
        # Streamable HTTP: the server issues a session id on initialize and expects
        # it echoed on every later request.
        if self.mcp_session_id:
            headers["Mcp-Session-Id"] = self.mcp_session_id
        r = requests.post(self.url, headers=headers, json=body, timeout=180)
        if r.headers.get("Mcp-Session-Id"):
            self.mcp_session_id = r.headers["Mcp-Session-Id"]
        if notify:
            return r.status_code, None
        if r.status_code != 200:
            return r.status_code, {"error": r.text[:500]}
        text = r.text
        # SSE frames may be preceded by an `event:` line and use CRLF endings, so
        # scan every line rather than testing the first one.
        if "data:" in text:
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    try:
                        return 200, json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
        try:
            return 200, r.json()
        except json.JSONDecodeError:
            return 200, {"error": text[:500]}

    def initialize(self):
        st, resp = self._post(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "gate4-sap-write", "version": "1.0"},
            },
        )
        if st == 200 and resp and "result" in resp:
            self._post("notifications/initialized", notify=True)
        return st, resp

    def tools(self):
        st, resp = self._post("tools/list")
        if st != 200 or not resp or "result" not in resp:
            return st, [], resp
        return st, [t["name"] for t in resp["result"].get("tools", [])], resp

    def call(self, name, args):
        st, resp = self._post("tools/call", {"name": name, "arguments": args})
        if st != 200 or not resp:
            return st, None, resp
        if "error" in resp:
            return st, None, resp["error"]
        result = resp.get("result", {})
        # Tool payloads arrive as a content list of text parts holding JSON.
        for part in result.get("content", []):
            if part.get("type") == "text":
                try:
                    return st, json.loads(part["text"]), result
                except json.JSONDecodeError:
                    return st, part["text"], result
        return st, result, result


def read_po(mcp, po):
    """Read one PO header. odata_read has no key argument — filter by the key field."""
    return mcp.call(
        "odata_read",
        {
            "service_name": SERVICE,
            "entity_set": ENTITY,
            "filter": f"PurchaseOrder eq '{po}'",
            "top": 1,
        },
    )


def update_po(mcp, po, data):
    """PATCH one PO header field via the MCP's identifier_fields/payload contract."""
    return mcp.call(
        "odata_update",
        {
            "service_name": SERVICE,
            "entity_set": ENTITY,
            "identifier_fields": {"PurchaseOrder": po},
            "payload": data,
        },
    )


def first_record(payload):
    """Normalize the assorted shapes odata_read returns into one dict."""
    if isinstance(payload, dict):
        for key in ("data", "d", "results", "value"):
            if key in payload:
                inner = payload[key]
                if isinstance(inner, list):
                    return inner[0] if inner else None
                if isinstance(inner, dict):
                    return first_record(inner) or inner
        return payload
    if isinstance(payload, list):
        return payload[0] if payload else None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true", help="read-only recon, no write")
    ap.add_argument("--field", help="PO header field to update")
    ap.add_argument("--value", help="value to write")
    ap.add_argument(
        "--no-restore", action="store_true", help="leave the change in place"
    )
    ap.add_argument("--fresh-login", action="store_true")
    args = ap.parse_args()

    url = mcp_url()
    print(f"MCP: {url[:110]}...")
    if "dzwr01" not in url:
        print("\nREFUSING: the resolved MCP is not the isolated auth-verify server")
        print("  A write must not run against a server shared with other work.")
        return 1

    tok = device_code_login(fresh=args.fresh_login)
    claims = jwt_claims(tok["access_token"])
    print(f"Human: {claims.get('preferred_username')}\n")

    mcp = Mcp(url, tok["access_token"])
    print("MCP handshake:")
    st, resp = mcp.initialize()
    ok = st == 200 and resp and "result" in resp
    check("initialize succeeds with the human Entra token", ok, f"HTTP {st}")
    if not ok:
        print(f"    {json.dumps(resp)[:400]}")
        return summarize()
    print(f"    negotiated: {resp['result'].get('protocolVersion')}")

    st, names, _ = mcp.tools()
    check("tools/list returns tools", bool(names), f"{len(names)} tools")
    print(f"    {sorted(names)}")
    # The write flags are deploy-time env vars on the runtime, so the tool list is
    # itself the evidence that this server differs from the read-only one.
    check("odata_update is exposed (write enabled)", "odata_update" in names)
    check("odata_delete is NOT exposed (delete disabled)", "odata_delete" not in names)
    check("odata_create is NOT exposed (create disabled)", "odata_create" not in names)

    print(f"\nBefore-state of PO {TEST_PO}:")
    st, payload, raw = read_po(mcp, TEST_PO)
    rec = first_record(payload)
    check("read returns the PO", isinstance(rec, dict) and bool(rec), f"HTTP {st}")
    if not isinstance(rec, dict) or not rec:
        print(f"    {json.dumps(payload)[:600]}")
        return summarize()

    with open("/tmp/po-before.json", "w") as f:  # nosec B108 - single-operator manual test driver, not a service
        json.dump(rec, f, indent=1)
    print(f"    {len(rec)} fields captured → /tmp/po-before.json")
    for k in sorted(rec):
        v = rec[k]
        if isinstance(v, (str, int, float)) and str(v).strip():
            print(f"      {k} = {v!r}")

    if args.discover:
        print("\n(discover mode — no write attempted)")
        return summarize()

    if not args.field or args.value is None:
        print(
            "\nNeed --field and --value to write. Re-run with --discover output above."
        )
        return summarize()

    field, new_value = args.field, args.value
    before = rec.get(field)
    print(f"\nWrite: {field}  {before!r} → {new_value!r}")
    if field not in rec:
        check(f"{field} exists on the entity", False, "field absent from the read")
        return summarize()

    st, wpayload, wraw = update_po(mcp, TEST_PO, {field: new_value})
    wrote = st == 200 and not (isinstance(wraw, dict) and wraw.get("isError"))
    check("odata_update accepted by SAP", wrote, f"HTTP {st}")
    print(f"    {json.dumps(wpayload)[:400] if wpayload else json.dumps(wraw)[:400]}")

    print("\nVerify the change landed:")
    st, payload2, _ = read_po(mcp, TEST_PO)
    rec2 = first_record(payload2) or {}
    after = rec2.get(field)
    check(f"{field} now reads back as the new value", after == new_value, f"{after!r}")

    if args.no_restore:
        print(f"\n!! left in place: {field} = {after!r} (was {before!r})")
        return summarize()

    print(f"\nRestore: {field} → {before!r}")
    st, rpayload, rraw = update_po(mcp, TEST_PO, {field: before})
    restored_call = st == 200 and not (isinstance(rraw, dict) and rraw.get("isError"))
    check("restore update accepted", restored_call, f"HTTP {st}")

    st, payload3, _ = read_po(mcp, TEST_PO)
    rec3 = first_record(payload3) or {}
    final = rec3.get(field)
    check(f"{field} is back to its original value", final == before, f"{final!r}")
    if final != before:
        print(f"\n!! MANUAL REVERT NEEDED: set {field} to {before!r} on PO {TEST_PO}")

    print(f"\n  session id (for STAD correlation): {mcp.session}")
    print(f"  expect SAP audit user: {claims.get('preferred_username')} → DANZACH")
    return summarize()


def summarize():
    print("\n" + "=" * 60)
    failed = [n for n, ok, _ in results if not ok]
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")
    for n in failed:
        print(f"  FAILED: {n}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
