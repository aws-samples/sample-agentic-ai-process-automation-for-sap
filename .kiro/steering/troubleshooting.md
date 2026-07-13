---
inclusion: always
---

<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->
# Troubleshooting

## AccessDeniedException on GetSecretValue

**Symptom:** Lambda fails with `AccessDeniedException` when calling `secretsmanager:GetSecretValue`.

**Root cause:** The IAM policy grants access to a secret ARN that doesn't match the actual secret the Lambda is trying to read. This happens when:
- The `stack_name_base` was changed after initial deployment, but the SSM parameter still points to the old secret
- A Lambda was using a hardcoded fallback stack name instead of the `STACK_NAME_BASE` env var

**Fix:**
1. Check the Lambda's `STACK_NAME_BASE` env var matches `stack_name_base` in `cdk/config.yaml`
2. Verify the SSM parameter `/{stack_name_base}/secrets/sap-credentials-arn` points to the correct secret
3. Redeploy: `cd cdk && cdk deploy --all` — the IAM policies now use the actual secret ARN from CDK, not a convention-based pattern

## Lambda KeyError: 'STACK_NAME_BASE'

**Symptom:** Lambda crashes at cold start with `KeyError: 'STACK_NAME_BASE'`.

**Root cause:** The Lambda's CDK construct doesn't pass the `STACK_NAME_BASE` environment variable. All Lambdas that reference stack resources require this.

**Fix:** In the CDK stack, add `STACK_NAME_BASE: config.stack_name_base` to the Lambda's environment variables.

## SSM Parameter Not Found

**Symptom:** Lambda fails with `ParameterNotFound` when reading from SSM.

**Common causes:**
- Stack name mismatch between the Lambda's `STACK_NAME_BASE` and the SSM parameter prefix
- The CDK stack that creates the parameter hasn't been deployed yet
- Wrong SSM path pattern (e.g. `/{stack}/sap/credentials-arn` vs `/{stack}/secrets/sap-credentials-arn`)

**Fix:** Check the SSM parameter exists: `aws ssm get-parameter --name "/{stack_name_base}/secrets/sap-credentials-arn"`. The canonical paths are:
- `/{stack_name_base}/secrets/sap-credentials-arn` — SAP credentials secret ARN
- `/{stack_name_base}/autonomy/trigger-mode` — trigger mode
- `/{stack_name_base}/autonomy/action-mode` — action mode

## SAP Credentials Not Working

**Symptom:** SAP OData calls return 401 or connection errors.

**Debug steps:**
1. Verify the secret has real values: `aws secretsmanager get-secret-value --secret-id "{stack_name_base}/sap-credentials"`
2. If values are `PLACEHOLDER`, run `make sync-sap-secret` to set real credentials
3. Check `sap.base_url` in config.yaml points to the correct SAP endpoint
4. For `service-account` mode, verify the SAP user has the required OData service authorizations

## CDK Deploy Fails

**Common issues:**
- `pip` not installed or not on PATH → Lambda bundling requires pip for local dependency installation
- CDK not bootstrapped → `cd cdk && cdk bootstrap`
- Node modules stale → `cd cdk && rm -rf node_modules && npm install`
- Config missing → `cp cdk/config.yaml.example cdk/config.yaml` and edit

## CDK Deploy Shows No Progress

**Symptom:** `cdk deploy` appears silent — no output in the terminal.

**Root cause:** CDK v2's default progress mode uses a progress bar that doesn't render in all terminals, especially when output is piped or tailed.

**Fix:** Add `--progress events` to get CloudFormation event-by-event output:
```bash
make deploy
```
The Makefile target already includes `--progress events`. You can also monitor progress in the CloudFormation console.

## Lambda Bundling Fails

**Symptom:** `cdk deploy` or `cdk synth` fails during "Bundling asset" phase.

**Root cause:** Local `pip install` failed for a Lambda's dependencies. This can happen if pip is not installed, or if a dependency requires native compilation that isn't available as a pre-built wheel.

**Fix:**
- Ensure `pip` is on your PATH: `pip --version`
- If a specific Lambda fails, install Docker or Finch as a fallback — CDK will automatically use Docker when local bundling fails
- Docker: `docker ps` to verify it's running
- Finch: `brew install --cask finch && finch vm init && finch vm start`, then `export CDK_DOCKER=finch`

## Frontend Shows Blank Page or Auth Errors

**Fix:** Regenerate the frontend config from current stack outputs:
```bash
make deploy-frontend    # full redeploy
# or for local dev:
make local-config
```

## Cryptography .so Loading Failure

**Symptom:** Lambda fails with `/var/task/cryptography/hazmat/bindings/_rust.abi3.so: cannot open shared object file: No such file or directory` even though the file exists.

**Root cause:** Architecture mismatch — the `.so` was bundled for aarch64 but the Lambda runs on x86_64 (or vice versa). The `dlopen` error message is misleading.

**Fix:**
1. Verify the Lambda architecture: `aws lambda get-function-configuration --function-name NAME --query Architectures`
2. Ensure it matches the bundled wheel platform. For `manylinux2014_aarch64` wheels, set `architecture: lambda.Architecture.ARM_64` in CDK
3. The `cryptography` package must be bundled with the Lambda directly (in `requirements.txt`), not in a Lambda layer
