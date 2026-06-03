# RAG Multi-Model Evaluation Baseline Report

## Methodology & Executive Summary

This report presents baseline quality, cost, and latency metrics across our benchmark dataset.
Evaluation is driven by OpenAI and Anthropic generator models, scored against gold annotated facts using an OpenAI judge.

> [!WARNING]
> **Same-Family Judge Bias Caveat**: OpenAIJudge is evaluated on OpenAI model outputs (`gpt-5-nano`). This might inflate scores for OpenAI-family generations due to stylistic and structural alignment. We mitigate this using cross-family generator sweeps (`claude-haiku-4-5`).

## Overall Summary

| Model                         | Fact Recall | Fact Precision | Faithfulness | Abstain Precision | Abstain Recall |
| ----------------------------- | ----------- | -------------- | ------------ | ----------------- | -------------- |
| **gpt-5-nano-2025-08-07**     | 24.8%       | 78.7%          | 85.5%        | 12.2%             | 73.3%          |
| **claude-haiku-4-5-20251001** | 24.1%       | 90.0%          | 91.9%        | 10.0%             | 93.3%          |
| **gemini-2.5-flash-lite**     | 24.5%       | 81.1%          | 79.8%        | 12.7%             | 70.0%          |

## Cost & Latency

| Model                         | Total Cost (USD) | Mean Latency (sec) | Total Tokens |
| ----------------------------- | ---------------- | ------------------ | ------------ |
| **gpt-5-nano-2025-08-07**     | $0.8954          | 32.34s             | 3,519,457    |
| **claude-haiku-4-5-20251001** | $1.6983          | 21.07s             | 2,939,940    |
| **gemini-2.5-flash-lite**     | $0.6346          | 25.05s             | 2,753,246    |

## Detailed Breakdown Per Category

| Category                     | Model                     | Retrieval Recall@10 | Retrieval nDCG@10 | Fact Recall | Fact Precision | Faithfulness |
| ---------------------------- | ------------------------- | ------------------- | ----------------- | ----------- | -------------- | ------------ |
| **basic**                    | gpt-5-nano-2025-08-07     | 97.1%               | 0.860             | 34.0%       | 86.6%          | 89.7%        |
|                              | claude-haiku-4-5-20251001 | 97.1%               | 0.860             | 31.8%       | 92.0%          | 93.1%        |
|                              | gemini-2.5-flash-lite     | 97.1%               | 0.860             | 33.3%       | 88.4%          | 85.1%        |
| **completeness**             | gpt-5-nano-2025-08-07     | 64.2%               | 0.647             | 10.1%       | 60.4%          | 65.8%        |
|                              | claude-haiku-4-5-20251001 | 64.2%               | 0.647             | 11.4%       | 61.9%          | 100.0%       |
|                              | gemini-2.5-flash-lite     | 64.2%               | 0.647             | 7.5%        | 46.7%          | 62.2%        |
| **conflicting_info**         | gpt-5-nano-2025-08-07     | 100.0%              | 0.928             | 22.0%       | 76.9%          | 100.0%       |
|                              | claude-haiku-4-5-20251001 | 100.0%              | 0.928             | 31.0%       | 91.7%          | 96.2%        |
|                              | gemini-2.5-flash-lite     | 100.0%              | 0.928             | 24.4%       | 73.1%          | 87.5%        |
| **constrained**              | gpt-5-nano-2025-08-07     | 100.0%              | 0.971             | 2.4%        | 62.1%          | 95.0%        |
|                              | claude-haiku-4-5-20251001 | 100.0%              | 0.971             | 4.6%        | 79.2%          | 90.3%        |
|                              | gemini-2.5-flash-lite     | 100.0%              | 0.971             | 8.5%        | 77.9%          | 90.1%        |
| **high_level**               | gpt-5-nano-2025-08-07     | N/A                 | N/A               | 15.8%       | 60.0%          | 85.7%        |
|                              | claude-haiku-4-5-20251001 | N/A                 | N/A               | 17.5%       | 100.0%         | 83.3%        |
|                              | gemini-2.5-flash-lite     | N/A                 | N/A               | 13.3%       | 100.0%         | 62.5%        |
| **info_not_found**           | gpt-5-nano-2025-08-07     | N/A                 | N/A               | 90.0%       | 100.0%         | 0.0%         |
|                              | claude-haiku-4-5-20251001 | N/A                 | N/A               | 95.0%       | 100.0%         | N/A          |
|                              | gemini-2.5-flash-lite     | N/A                 | N/A               | 95.0%       | 100.0%         | 50.0%        |
| **intra_document_reasoning** | gpt-5-nano-2025-08-07     | 97.5%               | 0.929             | 18.6%       | 66.2%          | 63.5%        |
|                              | claude-haiku-4-5-20251001 | 97.5%               | 0.929             | 15.9%       | 86.5%          | 94.1%        |
|                              | gemini-2.5-flash-lite     | 97.5%               | 0.929             | 21.1%       | 63.4%          | 64.3%        |
| **miscellaneous**            | gpt-5-nano-2025-08-07     | 100.0%              | 0.931             | 21.0%       | 83.3%          | 90.9%        |
|                              | claude-haiku-4-5-20251001 | 100.0%              | 0.931             | 21.7%       | 83.3%          | 100.0%       |
|                              | gemini-2.5-flash-lite     | 100.0%              | 0.931             | 19.2%       | 83.3%          | 92.4%        |
| **project_related**          | gpt-5-nano-2025-08-07     | 88.4%               | 0.863             | 15.4%       | 84.4%          | 91.1%        |
|                              | claude-haiku-4-5-20251001 | 88.4%               | 0.863             | 13.7%       | 92.0%          | 96.7%        |
|                              | gemini-2.5-flash-lite     | 88.4%               | 0.863             | 9.2%        | 78.5%          | 77.3%        |
| **semantic**                 | gpt-5-nano-2025-08-07     | 81.6%               | 0.665             | 16.0%       | 68.4%          | 82.4%        |
|                              | claude-haiku-4-5-20251001 | 81.6%               | 0.665             | 14.4%       | 87.7%          | 82.9%        |
|                              | gemini-2.5-flash-lite     | 81.6%               | 0.665             | 15.3%       | 76.4%          | 76.7%        |
