<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Knowledge Base Cost Optimization

The quickstart uses [Amazon S3 Vectors](https://aws.amazon.com/s3/) as the vector store for its two Bedrock Knowledge Bases (SOPs + API docs). S3 Vectors is pay-per-use with no provisioned infrastructure and no compute-unit floor — a deliberate cost choice for a low-QPS RAG workload that is often idle. See [ADR-013](../design-decisions/013-s3-vectors-over-aoss.md) for the rationale behind switching away from OpenSearch Serverless.

## Cost Model

Amazon S3 Vectors is generally available as the first cloud object store with native vector storage and query support. It bills on three dimensions, with no provisioned OCUs to pay for whether or not the index is queried:

| Dimension | What you pay for |
|-----------|------------------|
| Uploading | PUT requests when vectors are ingested (initial sync + updates) |
| Storing | The vectors held in the index, billed by size over time |
| Querying | Each similarity query against the index |

For two small Knowledge Bases (SOPs + API docs) at low query volume, this typically lands at a few dollars per month or less. An idle Knowledge Base costs effectively nothing — only the (tiny) storage charge for the stored vectors. Because there is no compute floor, cost scales down to near-zero when the agent isn't running.

Exact figures depend on corpus size and query volume. For current per-unit prices, see the **S3 Vectors** section of the [Amazon S3 pricing page](https://aws.amazon.com/s3/pricing/). AWS positions S3 Vectors at up to ~90% lower cost than dedicated vector databases for suitable workloads.

S3 Vectors scales to up to 2 billion vectors per index and 10,000 indexes per bucket, so the quickstart's small corpus uses a tiny fraction of its capacity.

## When This Is the Right Choice — and When It Isn't

S3 Vectors is built for **large, long-term, infrequent-access vector workloads** with low query rates. Query latency is sub-second (around 100ms warm), which is well within budget for an agent that retrieves a handful of times per case.

**S3 Vectors fits when:**

- Query volume is low (low QPS) and access is infrequent — exactly this quickstart's RAG pattern
- The Knowledge Base is often idle and you want cost to track usage, not provisioned capacity
- Sub-second retrieval latency is acceptable

**Prefer OpenSearch Serverless or OpenSearch Managed when:**

- You need high-QPS, low-latency search (consistent sub-100ms at scale)
- You rely on rich metadata-filtered or hybrid text + vector search semantics
- A fixed monthly cost in exchange for dedicated, always-warm capacity is an acceptable trade

## Tips to Reduce Cost Further

- **Prune stale documents.** Remove SOPs and API docs the agent no longer needs so you store and query fewer vectors.
- **Batch ingestion.** Sync documents in batches rather than one PUT at a time to keep upload request counts down.
- **Use smaller embedding dimensions** if the embedding model supports it. Fewer dimensions per vector means less storage. (The quickstart uses Titan Text Embeddings v2 at 1024 dimensions.)

## Appendix — The Former AOSS Approach (Historical)

Before [ADR-013](../design-decisions/013-s3-vectors-over-aoss.md), the quickstart stored vectors in OpenSearch Serverless (AOSS) VECTORSEARCH collections. This is documented here for teams who choose to switch back to AOSS and accept its fixed cost (for example, to get high-QPS low-latency search).

AOSS billed on OpenSearch Compute Units (OCUs) with a hard floor of ~2 OCUs per collection:

| Configuration | OCUs | Approx. Monthly Cost |
|---------------|------|----------------------|
| Two collections, redundant (default) | ~4 | ~$700 |
| Two collections, non-redundant | ~2 | ~$350 |

**Rate:** $0.24/OCU-hour × 730 hours/month ≈ $175.20 per OCU per month.

This floor applied whether the collections held 10 documents or 10 million, and whether or not they were queried — which is why it was the single largest fixed cost in the original architecture and a poor fit for a low-QPS quickstart. See [ADR-013](../design-decisions/013-s3-vectors-over-aoss.md) for the full rationale of the move to S3 Vectors.

## References

- [Amazon S3 pricing](https://aws.amazon.com/s3/pricing/) — see the S3 Vectors section for current per-unit prices
- [ADR-013: S3 Vectors over OpenSearch Serverless](../design-decisions/013-s3-vectors-over-aoss.md)
- [Bedrock KB vector store comparison](https://docs.aws.amazon.com/prescriptive-guidance/latest/choosing-an-aws-vector-database-for-rag-use-cases/vector-db-comparison.html)
- [OpenSearch Serverless pricing](https://aws.amazon.com/opensearch-service/pricing/)
- [Cost Benchmark (inference + infrastructure)](../evaluations/COST_BENCHMARK.md)
