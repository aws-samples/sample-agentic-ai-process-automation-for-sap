# ADR-013: Amazon S3 Vectors over OpenSearch Serverless for Knowledge Base storage

## Status

Accepted (2026-06-25). Supersedes the OpenSearch Serverless storage choice in ADR-002.

## Context

Bedrock Knowledge Bases need a vector store. The original implementation used OpenSearch Serverless (AOSS) VECTORSEARCH collections. Two problems:

- **Fixed cost.** AOSS bills on OpenSearch Compute Units with a hard floor of ~2 OCUs per collection. With two KBs (SOPs + API docs) this was the single largest fixed cost in the architecture (~$350–700/month) regardless of query volume — a poor fit for a low-QPS quickstart that is often idle.
- **Operational complexity.** AOSS has no CloudFormation resource for vector index management, forcing a custom-resource Lambda (opensearch-py + AWS4Auth) that created the kNN index over the HTTP API, padded with ~3 minutes of sleeps to absorb AOSS eventual consistency. This also justified a separate stack so those failures couldn't roll back the backend.

## Decision

Use **Amazon S3 Vectors** as the KB vector store. It has native CloudFormation / CDK L1 resources (`AWS::S3Vectors::VectorBucket`, `AWS::S3Vectors::Index`) and native Bedrock KB support (`StorageConfiguration.type = "S3_VECTORS"`). The vector bucket and index become declarative resources; the custom-resource Lambda, the AOSS security policies, and the separate stack are all removed. KB resources fold into the backend stack.

Index config mirrors the prior setup: 1024 dimensions (Titan Text Embeddings v2), `float32`, `cosine` distance.

## Consequences

- **Cost:** No fixed OCU floor; S3 Vectors is pay-per-use (storage + requests). Idle KBs cost ~nothing.
- **Simplicity:** Vector store is fully declarative IaC. No custom resource, no opensearch-py/AWS4Auth dependencies, no eventual-consistency sleeps, no separate stack.
- **Trade-off:** S3 Vectors is a newer service with higher per-query latency and different metadata-filtering semantics than AOSS kNN. Acceptable for this quickstart's low-QPS SOP/API-doc retrieval; teams needing low-latency, high-QPS, or rich filtered search may prefer AOSS or OpenSearch Managed.
- **Interface stability:** The SSM KB-ID parameters (`/{stack}/bedrock/{sops,api-docs}-kb-id`) and the KB-search Lambda are unchanged, so the agent required no modification.
