<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Webhook Signature Verification

Addresses threat model mitigations M9 (T11, T16).

## What Changed

- **Function URL replaced with API Gateway route** — `POST /webhooks` on the existing REST API. Stage-level throttling (100 RPS / 200 burst) applies to all routes including webhooks.
- **Signature verification** — the webhook processor Lambda verifies inbound payloads before processing, using the algorithm appropriate to the configured channel.
- **Secret stored in Secrets Manager** — the webhook signing secret is stored as the `webhook_secret` key in the same Secrets Manager secret that holds outbound channel credentials (`notification.secret_arn`). Read at Lambda cold start — never in env vars or config files.

## Channel Verification

| Channel | Algorithm | Headers Checked | Replay Protection |
|---------|-----------|----------------|-------------------|
| Slack | HMAC-SHA256 (`v0:` prefix) | `X-Slack-Signature`, `X-Slack-Request-Timestamp` | 5-minute window |
| Jira | HMAC-SHA256 | `X-Hub-Signature` (`sha256=` prefix) | None (Jira standard) |
| ServiceNow | Shared token | `X-Webhook-Secret` | None |
| SES | N/A (S3-triggered) | N/A | N/A |

## Configuration

1. Set `notification.secret_arn` in `config.yaml` to your channel credentials secret.
2. Run `make sync-channel-secret` to add the webhook signing secret.

Where to find the secret:
- **Slack**: App admin → Basic Information → Signing Secret
- **Jira**: Set when creating the webhook (Settings → System → WebHooks)
- **ServiceNow**: Shared token you define in the outbound REST message configuration

## Behavior

- **Secret configured**: all inbound webhooks are verified. Invalid signatures return 401.
- **No secret configured**: verification is skipped with a warning log. This allows initial setup and testing, but should not be used in production.
- **SES channel**: signature verification does not apply (emails arrive via S3 event, not HTTP).

## Rate Limiting

The webhook endpoint inherits the API Gateway stage throttle: 100 requests/second steady-state, 200 burst. This protects against webhook flooding (T11) without requiring per-source configuration.
