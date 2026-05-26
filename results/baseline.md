# RAG Multi-Model Evaluation Baseline Report

## Methodology & Executive Summary

This report presents baseline quality, cost, and latency metrics across our benchmark dataset.
Evaluation is driven by OpenAI and Anthropic generator models, scored against gold annotated facts using an OpenAI judge.

> [!WARNING]
> **Same-Family Judge Bias Caveat**: OpenAIJudge is evaluated on OpenAI model outputs (`gpt-5-nano`). This might inflate scores for OpenAI-family generations due to stylistic and structural alignment. We mitigate this using cross-family generator sweeps (`claude-haiku-4-5`).

## Overall Summary

| Model                         | Fact Recall | Fact Precision | Faithfulness | Abstain Precision | Abstain Recall |
| ----------------------------- | ----------- | -------------- | ------------ | ----------------- | -------------- |
| **gpt-5-nano-2025-08-07**     | 24.6%       | 80.3%          | 88.1%        | 10.5%             | 69.0%          |
| **claude-haiku-4-5-20251001** | 24.1%       | 91.4%          | 92.1%        | 9.7%              | 93.3%          |

## Cost & Latency

| Model                         | Total Cost (USD) | Mean Latency (sec) | Total Tokens |
| ----------------------------- | ---------------- | ------------------ | ------------ |
| **gpt-5-nano-2025-08-07**     | $0.8861          | 48.38s             | 3,492,418    |
| **claude-haiku-4-5-20251001** | $1.7019          | 15.04s             | 2,963,710    |

## Detailed Breakdown Per Category

| Category                     | Model                     | Retrieval Recall@10 | Retrieval nDCG@10 | Fact Recall | Fact Precision | Faithfulness |
| ---------------------------- | ------------------------- | ------------------- | ----------------- | ----------- | -------------- | ------------ |
| **basic**                    | gpt-5-nano-2025-08-07     | 97.1%               | 0.860             | 32.4%       | 79.4%          | 90.1%        |
|                              | claude-haiku-4-5-20251001 | 97.1%               | 0.860             | 32.0%       | 92.6%          | 92.1%        |
| **completeness**             | gpt-5-nano-2025-08-07     | 64.2%               | 0.647             | 9.1%        | 56.2%          | 56.3%        |
|                              | claude-haiku-4-5-20251001 | 64.2%               | 0.647             | 12.9%       | 68.8%          | 93.8%        |
| **conflicting_info**         | gpt-5-nano-2025-08-07     | 100.0%              | 0.928             | 25.6%       | 90.4%          | 98.5%        |
|                              | claude-haiku-4-5-20251001 | 100.0%              | 0.928             | 28.6%       | 93.8%          | 100.0%       |
| **constrained**              | gpt-5-nano-2025-08-07     | 100.0%              | 0.971             | 3.1%        | 59.0%          | 91.8%        |
|                              | claude-haiku-4-5-20251001 | 100.0%              | 0.971             | 3.2%        | 83.3%          | 100.0%       |
| **high_level**               | gpt-5-nano-2025-08-07     | N/A                 | N/A               | 20.0%       | 100.0%         | 77.1%        |
|                              | claude-haiku-4-5-20251001 | N/A                 | N/A               | 17.5%       | 100.0%         | 75.0%        |
| **info_not_found**           | gpt-5-nano-2025-08-07     | N/A                 | N/A               | 94.7%       | 100.0%         | 0.0%         |
|                              | claude-haiku-4-5-20251001 | N/A                 | N/A               | 100.0%      | 100.0%         | 0.0%         |
| **intra_document_reasoning** | gpt-5-nano-2025-08-07     | 97.5%               | 0.929             | 15.9%       | 57.4%          | 78.5%        |
|                              | claude-haiku-4-5-20251001 | 97.5%               | 0.929             | 18.8%       | 81.7%          | 90.7%        |
| **miscellaneous**            | gpt-5-nano-2025-08-07     | 100.0%              | 0.931             | 24.2%       | 100.0%         | 100.0%       |
|                              | claude-haiku-4-5-20251001 | 100.0%              | 0.931             | 20.8%       | 100.0%         | 88.9%        |
| **project_related**          | gpt-5-nano-2025-08-07     | 88.4%               | 0.863             | 20.0%       | 88.9%          | 93.0%        |
|                              | claude-haiku-4-5-20251001 | 88.4%               | 0.863             | 12.9%       | 90.2%          | 97.6%        |
| **semantic**                 | gpt-5-nano-2025-08-07     | 81.6%               | 0.665             | 15.1%       | 80.1%          | 88.1%        |
|                              | claude-haiku-4-5-20251001 | 81.6%               | 0.665             | 13.2%       | 93.0%          | 89.5%        |
