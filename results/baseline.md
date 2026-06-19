# RAG Multi-Model Evaluation Baseline Report

## Methodology & Executive Summary

This report presents baseline quality, cost, and latency metrics across our benchmark dataset.
Evaluation is driven by OpenAI and Anthropic generator models, scored against gold annotated facts using an OpenAI judge.

> [!WARNING]
> **Same-Family Judge Bias Caveat**: OpenAIJudge is evaluated on OpenAI model outputs (`gpt-5-nano`). This might inflate scores for OpenAI-family generations due to stylistic and structural alignment. We mitigate this using cross-family generator sweeps (`claude-haiku-4-5`).

## Overall Summary

| Model                         | Fact Recall | Fact Precision | Faithfulness | Abstain Precision | Abstain Recall |
| ----------------------------- | ----------- | -------------- | ------------ | ----------------- | -------------- |
| **gpt-5-nano-2025-08-07**     | 26.4%       | 81.0%          | 84.0%        | 10.8%             | 70.0%          |
| **claude-haiku-4-5-20251001** | 25.1%       | 91.1%          | 84.8%        | 9.7%              | 93.3%          |
| **gemini-2.5-flash-lite**     | 24.3%       | 80.6%          | 75.1%        | 13.1%             | 70.0%          |

## Cost & Latency

| Model                         | Total Cost (USD) | Mean Latency (sec) | Total Tokens |
| ----------------------------- | ---------------- | ------------------ | ------------ |
| **gpt-5-nano-2025-08-07**     | $1.1791          | 36.66s             | 4,538,227    |
| **claude-haiku-4-5-20251001** | $1.9773          | 23.00s             | 3,964,429    |
| **gemini-2.5-flash-lite**     | $0.9228          | 25.93s             | 3,810,876    |

## Detailed Breakdown Per Category

| Category                     | Model                     | Retrieval Recall@10 | Retrieval nDCG@10 | Fact Recall | Fact Precision | Faithfulness |
| ---------------------------- | ------------------------- | ------------------- | ----------------- | ----------- | -------------- | ------------ |
| **basic**                    | gpt-5-nano-2025-08-07     | 97.1%               | 0.860             | 34.2%       | 81.0%          | 86.6%        |
|                              | claude-haiku-4-5-20251001 | 97.1%               | 0.860             | 33.2%       | 95.8%          | 84.1%        |
|                              | gemini-2.5-flash-lite     | 97.1%               | 0.860             | 33.1%       | 84.5%          | 82.3%        |
| **completeness**             | gpt-5-nano-2025-08-07     | 64.2%               | 0.647             | 11.8%       | 59.3%          | 63.3%        |
|                              | claude-haiku-4-5-20251001 | 64.2%               | 0.647             | 11.8%       | 55.6%          | 95.2%        |
|                              | gemini-2.5-flash-lite     | 64.2%               | 0.647             | 18.8%       | 76.2%          | 57.2%        |
| **conflicting_info**         | gpt-5-nano-2025-08-07     | 100.0%              | 0.928             | 23.7%       | 89.6%          | 95.7%        |
|                              | claude-haiku-4-5-20251001 | 100.0%              | 0.928             | 29.2%       | 97.2%          | 100.0%       |
|                              | gemini-2.5-flash-lite     | 100.0%              | 0.928             | 24.3%       | 75.0%          | 88.9%        |
| **constrained**              | gpt-5-nano-2025-08-07     | 100.0%              | 0.971             | 5.0%        | 77.5%          | 96.3%        |
|                              | claude-haiku-4-5-20251001 | 100.0%              | 0.971             | 4.5%        | 77.8%          | 93.3%        |
|                              | gemini-2.5-flash-lite     | 100.0%              | 0.971             | 8.3%        | 76.1%          | 63.3%        |
| **high_level**               | gpt-5-nano-2025-08-07     | N/A                 | N/A               | 25.0%       | 80.0%          | 59.4%        |
|                              | claude-haiku-4-5-20251001 | N/A                 | N/A               | 17.5%       | 100.0%         | 27.8%        |
|                              | gemini-2.5-flash-lite     | N/A                 | N/A               | 13.3%       | 100.0%         | 49.3%        |
| **info_not_found**           | gpt-5-nano-2025-08-07     | N/A                 | N/A               | 95.0%       | 100.0%         | 100.0%       |
|                              | claude-haiku-4-5-20251001 | N/A                 | N/A               | 100.0%      | 100.0%         | N/A          |
|                              | gemini-2.5-flash-lite     | N/A                 | N/A               | 80.0%       | 100.0%         | 66.7%        |
| **intra_document_reasoning** | gpt-5-nano-2025-08-07     | 97.5%               | 0.929             | 19.6%       | 58.3%          | 84.1%        |
|                              | claude-haiku-4-5-20251001 | 97.5%               | 0.929             | 17.9%       | 81.1%          | 77.3%        |
|                              | gemini-2.5-flash-lite     | 97.5%               | 0.929             | 21.5%       | 68.8%          | 74.7%        |
| **miscellaneous**            | gpt-5-nano-2025-08-07     | 100.0%              | 0.931             | 22.7%       | 75.0%          | 70.0%        |
|                              | claude-haiku-4-5-20251001 | 100.0%              | 0.931             | 20.0%       | 100.0%         | 100.0%       |
|                              | gemini-2.5-flash-lite     | 100.0%              | 0.931             | 19.8%       | 71.4%          | 65.5%        |
| **project_related**          | gpt-5-nano-2025-08-07     | 88.4%               | 0.863             | 20.0%       | 88.4%          | 80.2%        |
|                              | claude-haiku-4-5-20251001 | 88.4%               | 0.863             | 14.8%       | 88.9%          | 82.4%        |
|                              | gemini-2.5-flash-lite     | 88.4%               | 0.863             | 9.4%        | 85.8%          | 71.0%        |
| **semantic**                 | gpt-5-nano-2025-08-07     | 81.6%               | 0.665             | 17.4%       | 82.4%          | 84.6%        |
|                              | claude-haiku-4-5-20251001 | 81.6%               | 0.665             | 15.2%       | 87.6%          | 85.4%        |
|                              | gemini-2.5-flash-lite     | 81.6%               | 0.665             | 15.1%       | 74.5%          | 74.0%        |

## Root-Cause Attribution

Of the **failed** gold facts (`absent` / `contradicted`), the split between a
_retrieval gap_ (no retrieved doc substantiated the fact) and a _generation gap_ (the
evidence WAS retrieved but the generator failed to use it). N/A = no per-fact evidence.

| Category                     | Model                     | Retrieval-Gap (failed facts) | Generation-Gap (failed facts) | Retrieval-Gap % |
| ---------------------------- | ------------------------- | ---------------------------- | ----------------------------- | --------------- |
| **basic**                    | gpt-5-nano-2025-08-07     | 352                          | 15                            | 95.9%           |
|                              | claude-haiku-4-5-20251001 | 349                          | 30                            | 92.1%           |
|                              | gemini-2.5-flash-lite     | 341                          | 33                            | 91.2%           |
| **completeness**             | gpt-5-nano-2025-08-07     | 169                          | 62                            | 73.2%           |
|                              | claude-haiku-4-5-20251001 | 176                          | 93                            | 65.4%           |
|                              | gemini-2.5-flash-lite     | 138                          | 85                            | 61.9%           |
| **conflicting_info**         | gpt-5-nano-2025-08-07     | 107                          | 0                             | 100.0%          |
|                              | claude-haiku-4-5-20251001 | 96                           | 4                             | 96.0%           |
|                              | gemini-2.5-flash-lite     | 98                           | 9                             | 91.6%           |
| **constrained**              | gpt-5-nano-2025-08-07     | 285                          | 15                            | 95.0%           |
|                              | claude-haiku-4-5-20251001 | 294                          | 9                             | 97.0%           |
|                              | gemini-2.5-flash-lite     | 289                          | 2                             | 99.3%           |
| **high_level**               | gpt-5-nano-2025-08-07     | 22                           | 0                             | 100.0%          |
|                              | claude-haiku-4-5-20251001 | 22                           | 2                             | 91.7%           |
|                              | gemini-2.5-flash-lite     | 23                           | 2                             | 92.0%           |
| **info_not_found**           | gpt-5-nano-2025-08-07     | 1                            | 0                             | 100.0%          |
|                              | claude-haiku-4-5-20251001 | 0                            | 0                             | 0.0%            |
|                              | gemini-2.5-flash-lite     | 3                            | 1                             | 75.0%           |
| **intra_document_reasoning** | gpt-5-nano-2025-08-07     | 76                           | 12                            | 86.4%           |
|                              | claude-haiku-4-5-20251001 | 77                           | 12                            | 86.5%           |
|                              | gemini-2.5-flash-lite     | 73                           | 13                            | 84.9%           |
| **miscellaneous**            | gpt-5-nano-2025-08-07     | 33                           | 1                             | 97.1%           |
|                              | claude-haiku-4-5-20251001 | 36                           | 0                             | 100.0%          |
|                              | gemini-2.5-flash-lite     | 35                           | 1                             | 97.2%           |
| **project_related**          | gpt-5-nano-2025-08-07     | 353                          | 14                            | 96.2%           |
|                              | claude-haiku-4-5-20251001 | 351                          | 34                            | 91.2%           |
|                              | gemini-2.5-flash-lite     | 408                          | 11                            | 97.4%           |
| **semantic**                 | gpt-5-nano-2025-08-07     | 407                          | 19                            | 95.5%           |
|                              | claude-haiku-4-5-20251001 | 403                          | 29                            | 93.3%           |
|                              | gemini-2.5-flash-lite     | 417                          | 21                            | 95.2%           |
