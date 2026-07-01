# **Observability and Evaluation Architectures for Custom RAG Pipelines in Python 3.11**

## **Comparative Evaluation of Observability Frameworks**

Building a production-grade Retrieval-Augmented Generation (RAG) system with a thin, custom substrate requires selecting an observability layer that balances architectural scalability, permissive open-source licensing, native compliance with telemetry standards, and operational simplicity.1 When avoiding high-level framework wrappers, the underlying observability layer must integrate directly with manual instrumentation hooks in Python 3.11.3 Four primary candidates—Langfuse, Arize Phoenix, LangSmith, and a pure OpenTelemetry (OTEL) pipeline backed by Grafana Tempo or Jaeger—exhibit divergent patterns across these critical dimensions.1

| Evaluated Dimension                       | Langfuse                                                                       | Arize Phoenix                                                        | LangSmith                                                                    | Pure OpenTelemetry (Tempo/Jaeger)                                        |
| :---------------------------------------- | :----------------------------------------------------------------------------- | :------------------------------------------------------------------- | :--------------------------------------------------------------------------- | :----------------------------------------------------------------------- |
| **Primary Open-Source License**           | MIT (Core Platform) 7                                                          | Apache-2.0 9                                                         | Proprietary (Closed Source) 6                                                | Apache-2.0 / MIT 10                                                      |
| **Self-Hosting Infrastructure Footprint** | Multi-container: Next.js Web, Async Worker, Postgres, ClickHouse, Redis, S3 12 | Single Python process or lightweight container 13                    | Complex multi-node K8s cluster requiring helm charts and external storage 14 | Standard APM stack: OTEL collector, storage backend, visualization UI 1  |
| **Enterprise Self-Hosting Constraints**   | Enterprise Edition (/ee) features require a commercial license 8               | No feature-gating on the open-source workbench 13                    | Gated entirely behind sales contracts and license keys 14                    | Unrestricted; standard telemetry standard 1                              |
| **Native OTEL Wire Compliance**           | Standard OTLP trace ingestion supported natively 3                             | Native; built on top of OpenTelemetry and OpenInference specs 9      | Low; proprietary format with secondary export translation 1                  | Absolute; standard OTEL semantic conventions 1                           |
| **Manual Python 3.11 Ergonomics**         | Highly ergonomic; direct context managers and SDK wrappers 18                  | High; standard OTEL tracer wrappers with OpenInference attributes 4  | Good; traceable decorators but tightly coupled to internal schemas 6         | Verbose; requires manual tracer configuration and span management 1      |
| **Offline Evaluation Write-Back**         | Robust; asynchronous write-back score APIs with idempotency keys 21            | Flexible; span-attached evaluation dataframes uploaded via client 22 | Supported via run/feedback APIs 24                                           | Complex; requires external correlation tables due to span immutability 1 |

Langfuse is built on a split-database architecture designed to sustain high ingestion throughput.12 By utilizing PostgreSQL for transactional application state and ClickHouse as a dedicated OLAP database for traces, observations, and scores, the platform provides highly performant analytical queries even at large scales.12 Tracing and evaluation events are buffered locally in S3 object storage before asynchronous worker containers process and ingest them into ClickHouse, decoupling ingestion from query paths.12 For high-volume production deployments, Langfuse allows scaling by separating ingestion traffic from the user interface.27 Placing /api/public/ingestion\* and /api/public/otel\* behind dedicated replicas prevents ClickHouse read contentions from degrading front-end performance.27  
The core of Langfuse is strictly MIT-licensed.7 However, advanced administration features—such as role-based access control, SCIM provisioning, audit logging, and data retention policies—reside within the /ee directory and require a paid commercial license.8 This commercial model presents a predictable scaling pathway for enterprise deployments without introducing artificial performance or trace-volume limits on the open-source core.8  
Arize Phoenix operates under an un-gated Apache-2.0 license as a developer-first LLM observability and evaluation workbench.9 It is designed to run with a minimal footprint, launching as a single container or an inline Python process that serves as a local OpenTelemetry collector.13 This makes Phoenix an exceptionally lightweight candidate for isolated evaluation harnesses and local developer testing.13  
Despite its native alignment with OpenTelemetry and the OpenInference specification, Phoenix is fundamentally structured as an evaluation workbench.9 It lacks built-in production features such as collaborative annotator queues, custom dashboards, and native prompt management within its open-source UI.13 For production-grade tracking and security controls, Phoenix relies on its integration with Arize AX, which introduces upstream enterprise software dependencies and licensing overhead.5  
LangSmith is highly optimized for teams using LangChain and LangGraph.6 However, its proprietary, closed-source nature makes it a poor fit for custom, thin RAG substrates.2 While LangSmith supports manual tracing, self-hosting is an enterprise-only add-on requiring a sales contract, an annual upfront fee, and a highly complex multi-node Kubernetes deployment.6 This complexity introduces significant infrastructure overhead and vendor lock-in.1  
A pure OpenTelemetry pipeline backed by Jaeger or Grafana Tempo provides the highest degree of infrastructure portability and zero vendor lock-in.1 It allows generative AI telemetry to be ingested alongside standard application performance monitoring (APM) metrics, logs, and database queries.1  
However, generic APM backends are natively designed for request-response timelines.1 They do not offer specialized interfaces for visualizing chat message histories, prompt version histories, or multidimensional evaluation scores.1 Adopting a pure OTEL approach requires the engineering team to build a custom visualization front-end and a secondary storage layer to handle post-hoc evaluation scores, resulting in high maintenance overhead.1

## **Manual Python 3.11 Instrumentation Ergonomics**

Because the target RAG system is built on a thin, custom substrate consisting of LanceDB and direct Generator protocols, the observability layer must be instrumented manually without relying on framework-specific auto-instrumentation.3 Manual ergonomics must be clean, thread-safe, and compatible with async execution contexts in Python 3.11.  
The following sections provide concrete, fully importable Python 3.11 code implementations for manual instrumentation across the three open-source pathways.

### **Arize Phoenix Manual Instrumentation (OpenInference Schema)**

Phoenix utilizes standard OpenTelemetry API primitives under the hood, wrapping them with OpenInference span semantic conventions to identify steps such as retrievers, chains, and language model calls.4

Python  
\# python_loc_estimate: \~48 lines  
import json  
import uuid  
from typing import List, Dict, Any  
from opentelemetry import trace  
from opentelemetry.trace import Status, StatusCode  
from phoenix.otel import register

\# Initialize Phoenix Tracer Provider mapping to custom project  
tracer_provider \= register(  
protocol="http/protobuf",  
project_name="lancedb-custom-rag",  
endpoint="http://localhost:6006/v1/traces"  
)  
tracer \= tracer_provider.get_tracer(\_\_name\_\_)

def execute_rag_pipeline(user_query: str) \-\> Dict\[str, Any\]:  
\# Root chain trace representing the end-to-end RAG request  
with tracer.start_as_current_span(  
"rag-pipeline",  
openinference_span_kind="chain"  
) as root_span:  
root_span.set_attribute("input.value", user_query)  
root_span.set_attribute("session.id", "session_abc123")

        \# 1\. Manually instrument custom LanceDB retrieval
        with tracer.start\_as\_current\_span(
            "lancedb-retrieval",
            openinference\_span\_kind="retriever"
        ) as retrieve\_span:
            retrieve\_span.set\_attribute("input.value", user\_query)

            \# Simulate LanceDB hybrid query result
            retrieved\_chunks \=

            retrieve\_span.set\_attribute("output.value", json.dumps(retrieved\_chunks))

            \# OpenInference strict mapping for retrieved documents
            for i, chunk in enumerate(retrieved\_chunks):
                prefix \= f"retrieval.documents.{i}."
                retrieve\_span.set\_attribute(f"{prefix}document.id", chunk\["id"\])
                retrieve\_span.set\_attribute(f"{prefix}document.content", chunk\["text"\])
                retrieve\_span.set\_attribute(f"{prefix}document.score", chunk\["score"\])

        \# 2\. Manually instrument custom Generator call
        with tracer.start\_as\_current\_span(
            "llm-generation",
            openinference\_span\_kind="llm"
        ) as llm\_span:
            llm\_span.set\_attribute("llm.model\_name", "claude-3-5-sonnet-20241022")
            llm\_span.set\_attribute("llm.input\_messages.0.message.role", "user")
            llm\_span.set\_attribute("llm.input\_messages.0.message.content", user\_query)

            model\_output \= "LanceDB hybrid search running on Python 3.11 runtime."

            llm\_span.set\_attribute("llm.output\_messages.0.message.role", "assistant")
            llm\_span.set\_attribute("llm.output\_messages.0.message.content", model\_output)
            llm\_span.set\_attribute("llm.token\_count.prompt", 120)
            llm\_span.set\_attribute("llm.token\_count.completion", 40)
            llm\_span.set\_status(Status(StatusCode.OK))

        root\_span.set\_attribute("output.value", model\_output)
        return {"output": model\_output, "trace\_id": root\_span.get\_span\_context().trace\_id}

### **Langfuse Manual Instrumentation (Native Python SDK)**

The Langfuse Python SDK exposes a direct, high-level API for structured LLM application monitoring.3 This SDK handles asynchronous, thread-safe queuing and flushing of events in the background.18

Python  
\# python_loc_estimate: \~38 lines  
import json  
from typing import Dict, Any  
from langfuse import get_client

\# Initializes the client from environment variable configurations  
langfuse \= get_client()

def execute_rag_pipeline_langfuse(user_query: str) \-\> Dict\[str, Any\]:  
\# Initialize the trace object  
trace \= langfuse.trace(  
name="rag-pipeline",  
session_id="session_abc123",  
input\=user_query  
)

    \# 1\. Trace LanceDB custom hybrid retrieval step
    retrieval\_span \= trace.span(
        name="lancedb-retrieval",
        input\={"query": user\_query}
    )

    retrieved\_chunks \=

    retrieval\_span.update(
        output={"chunks": retrieved\_chunks}
    )
    retrieval\_span.end()

    \# 2\. Trace custom generator step
    generation \= trace.generation(
        name="llm-generation",
        model="claude-3-5-sonnet-20241022",
        model\_parameters={"temperature": 0.2},
        input\=\[{"role": "user", "content": user\_query}\]
    )

    model\_output \= "LanceDB hybrid search running on Python 3.11 runtime."

    generation.update(
        output=model\_output,
        usage={
            "prompt\_tokens": 120,
            "completion\_tokens": 40
        }
    )
    generation.end()

    trace.update(output=model\_output)

    \# Ensure background queues flush in short-lived/serverless environments
    langfuse.flush()

    return {"output": model\_output, "trace\_id": trace.id}

### **Pure OpenTelemetry Manual Instrumentation (Standard GenAI Semantic Conventions)**

Standardizing entirely on the official, vendor-neutral OpenTelemetry Semantic Conventions for GenAI ensures your application remains compatible with any compliant backend.1

Python  
\# python_loc_estimate: \~55 lines  
import json  
from typing import Dict, Any  
from opentelemetry import trace  
from opentelemetry.sdk.trace import TracerProvider  
from opentelemetry.sdk.trace.export import BatchSpanProcessor  
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter  
from opentelemetry.trace import Status, StatusCode

\# Configure standard OTel SDK components  
provider \= TracerProvider()  
processor \= BatchSpanProcessor(OTLPSpanExporter(endpoint="http://localhost:4317"))  
provider.add_span_processor(processor)  
trace.set_tracer_provider(provider)  
tracer \= trace.get_tracer("custom-rag-service")

def execute_rag_pipeline_pure_otel(user_query: str) \-\> Dict\[str, Any\]:  
with tracer.start_as_current_span(  
"rag-pipeline",  
kind=trace.SpanKind.SERVER  
) as root_span:  
\# Standard OTel root metrics  
root_span.set_attribute("session.id", "session_abc123")

        \# 1\. Custom database client span for LanceDB
        with tracer.start\_as\_current\_span(
            "LanceDB.search",
            kind=trace.SpanKind.CLIENT
        ) as db\_span:
            db\_span.set\_attribute("db.system.name", "lancedb")
            db\_span.set\_attribute("db.collection.name", "knowledge\_chunks")
            db\_span.set\_attribute("db.operation.name", "hybrid\_search")
            db\_span.set\_attribute("db.query.summary", user\_query)

            retrieved\_payload \= "LanceDB hybrid search output mapping text chunks."
            db\_span.set\_status(Status(StatusCode.OK))

        \# 2\. Generative AI call span following GenAI semantic specifications
        with tracer.start\_as\_current\_span(
            "chat.claude",
            kind=trace.SpanKind.CLIENT
        ) as ai\_span:
            ai\_span.set\_attribute("gen\_ai.system", "anthropic")
            ai\_span.set\_attribute("gen\_ai.operation.name", "chat")
            ai\_span.set\_attribute("gen\_ai.request.model", "claude-3-5-sonnet-20241022")
            ai\_span.set\_attribute("gen\_ai.request.temperature", 0.2)

            \# Input format strictly serialized to standard JSON structures
            input\_msg \= \[{"role": "user", "parts": \[{"type": "text", "content": user\_query}\]}\]
            ai\_span.set\_attribute("gen\_ai.input.messages", json.dumps(input\_msg))

            model\_output \= "LanceDB hybrid search running on Python 3.11 runtime."
            output\_msg \= \[{"role": "assistant", "parts": \[{"type": "text", "content": model\_output}\]}\]

            ai\_span.set\_attribute("gen\_ai.output.messages", json.dumps(output\_msg))
            ai\_span.set\_attribute("gen\_ai.usage.input\_tokens", 120)
            ai\_span.set\_attribute("gen\_ai.usage.output\_tokens", 40)
            ai\_span.set\_status(Status(StatusCode.OK))

        root\_span.set\_status(Status(StatusCode.OK))
        return {"output": model\_output, "trace\_id": root\_span.get\_span\_context().trace\_id}

The programmatic complexity of manual instrumentation scales directly with the degree of standardization.1

| Candidate              | Lines of Code (LoC) | Complexity Vector                                                        | Thread-Safety Mechanisms                                       | Context Management                                |
| :--------------------- | :------------------ | :----------------------------------------------------------------------- | :------------------------------------------------------------- | :------------------------------------------------ |
| **Langfuse**           | \~38 lines          | Low; high-level abstractions map directly to logical RAG steps 18        | Built-in queue-and-flush thread pool inside Python client 18   | Native Python context managers or manual spans 18 |
| **Arize Phoenix**      | \~48 lines          | Medium; leverages OpenTelemetry API wrapper with custom attributes 4     | Handled natively by Python's opentelemetry.context engine 35   | Strict index-aligned flat attribute context 36    |
| **Pure OpenTelemetry** | \~55 lines          | High; requires configuring tracer providers, processors, and endpoints 1 | Native OTel context propagation and concurrent async safety 35 | Native OTel context APIs 1                        |

## **Non-LLM Retrieval Span Representation in OpenTelemetry**

A common gap in standard APM instrumentation is representing non-LLM operations—such as vector searches, semantic rerankers, and keyword lookups—using general database conventions.1 In a custom hybrid LanceDB engine combining dense vector search and BM25 text match, standardizing the representation of retrieval spans is critical.33  
To capture this hybrid retrieval pipeline correctly under OpenTelemetry, the tracing implementation must combine standard database semantic conventions (db.\*) with GenAI-specific retrieval semantic conventions (gen_ai.\* or openinference.\*).33  
Representing retrieved documents as single serialized JSON strings inside a span attribute is considered an anti-pattern. This approach limits indexing performance, prevents sub-attribute filtering, and causes payload parsing errors in analytical backends.26 Instead, individual document chunks must be mapped using zero-indexed flattened attribute naming structures.36  
The retrieval span should be executed as a CLIENT span.37 It must explicitly capture the input query, the search parameters (such as the number of requested neighbors ![][image1]), and the details of the retrieved document chunks.39

Trace Span: "LanceDB.search" (Kind: CLIENT, openinference.span.kind: RETRIEVER)  
├── db.system.name: "lancedb"  
├── db.collection.name: "wiki_embeddings"  
├── db.operation.name: "hybrid_search"  
├── gen_ai.data_source.id: "knowledge_base_alpha" \[39, 42\]  
├── input.value: "What is the hybrid search threshold?"  
├── retrieval.documents.0.document.id: "chunk_994" \[36, 41\]  
├── retrieval.documents.0.document.content: "LanceDB hybrid search combines BM25..." \[36, 41\]  
├── retrieval.documents.0.document.score: 0.9142 \[36, 41\]  
├── retrieval.documents.0.document.metadata: '{"source": "docs", "author": "dev"}' \[36, 41\]  
├── retrieval.documents.1.document.id: "chunk_204" \[36, 41\]  
└── retrieval.documents.1.document.content: "Dense vector indexing utilizes IvfPq..." \[36, 41\]

This structural mapping enables deep trace analysis. By decomposing retrieved documents into distinct, indexed keys, downstream analytical engines (such as ClickHouse or Elasticsearch) can execute high-speed queries to identify retrieval anomalies.2 For example, developers can query for all traces where retrieval.documents.0.document.score fell below ![][image2] yet the generation span returned a highly confident response, indicating potential hallucination risks.2

## **Cost Calculation Engine and Token Economics**

A production-grade RAG evaluation harness must support precise token-level cost tracking.9 Because different model providers use distinct input, output, caching, and reasoning token pricing structures, token costs must be calculated programmatically at trace execution or ingestion time.43

### **Standard Token Pricing Model**

The pricing matrix below outlines the specific per-token pricing for the requested models as of May 2026\.43

| Model Variant                  | Base Model Key             | Input Cost (per 1M tokens) | Output Cost (per 1M tokens) | Cache Read Discount |
| :----------------------------- | :------------------------- | :------------------------- | :-------------------------- | :------------------ |
| **gpt-5-nano-2025-08-07**      | gpt-5-nano-2025-08-07      | $0.05 46                   | $0.40 46                    | N/A                 |
| **gpt-4o-mini**                | gpt-4o-mini                | $0.15 45                   | $0.60 45                    | 50% ($0.075) 43     |
| **claude-3-5-haiku-20241022**  | claude-3-5-haiku-20241022  | $0.80 45                   | $4.00 45                    | 90% ($0.08) 43      |
| **claude-3-5-sonnet-20241022** | claude-3-5-sonnet-20241022 | $3.00 45                   | $15.00 45                   | 90% ($0.30) 43      |

### **Dynamic Pricing Calculation Model**

To calculate costs accurately, the instrumentation layer must support advanced token attributes, including cached input tokens and reasoning tokens.40 For example, Anthropic supports prompt caching read discounts, while newer models include reasoning tokens inside the overall completion count.40  
The overall calculation is defined mathematically as follows:  
![][image3]  
Where ![][image4] represents token counts, and ![][image5] represents the respective unit prices per single token.  
The following Python 3.11 module implements this pricing calculator natively.

Python  
\# python_loc_estimate: \~32 lines  
from typing import Dict, Any

MODEL_PRICING \= {  
"gpt-5-nano-2025-08-07": {  
"input": 0.05 / 1e6,  
"output": 0.40 / 1e6,  
"cache_read": 0.05 / 1e6  
},  
"gpt-4o-mini": {  
"input": 0.15 / 1e6,  
"output": 0.60 / 1e6,  
"cache_read": 0.075 / 1e6  
},  
"claude-3-5-haiku-20241022": {  
"input": 0.80 / 1e6,  
"output": 4.00 / 1e6,  
"cache_read": 0.08 / 1e6  
},  
"claude-3-5-sonnet-20241022": {  
"input": 3.00 / 1e6,  
"output": 15.00 / 1e6,  
"cache_read": 0.30 / 1e6  
}  
}

def calculate_span_cost(  
model_name: str,  
input_tokens: int,  
output_tokens: int,  
cached_input_tokens: int \= 0,  
reasoning_tokens: int \= 0  
) \-\> float:  
pricing \= MODEL_PRICING.get(model_name)  
if not pricing:  
return 0.0

    base\_input \= max(0, input\_tokens \- cached\_input\_tokens)
    input\_cost \= (base\_input \* pricing\["input"\]) \+ (cached\_input\_tokens \* pricing\["cache\_read"\])

    \# Reasoning tokens are billed at standard output rates
    total\_output \= output\_tokens \+ reasoning\_tokens
    output\_cost \= total\_output \* pricing\["output"\]

    return input\_cost \+ output\_cost

Applying this pricing engine to a representative scenario where a RAG request consumes ![][image6] input tokens (with ![][image7] of those tokens successfully read from the cache) and generates ![][image8] output tokens yields the exact costs detailed in the table below.

| Model Variant                  | Cache Read Cost | Base Input Cost | Output Cost | Total Request Cost |
| :----------------------------- | :-------------- | :-------------- | :---------- | :----------------- |
| **gpt-5-nano-2025-08-07**      | $0.000020       | $0.000030       | $0.000200   | **$0.000250**      |
| **gpt-4o-mini**                | $0.000030       | $0.000090       | $0.000300   | **$0.000420**      |
| **claude-3-5-haiku-20241022**  | $0.000032       | $0.000480       | $0.002000   | **$0.002512**      |
| **claude-3-5-sonnet-20241022** | $0.000120       | $0.001800       | $0.007500   | **$0.009420**      |

This precision is critical because in high-throughput production environments, relying on naive, un-cached pricing calculations can cause the tracked cost metrics to drift by up to ![][image9] from the actual invoice.44

## **Offline Evaluation and Metric Attachment**

Unlike online evaluations that run concurrently with the request, offline evaluations are executed asynchronously in batches.49 The evaluation pipeline runs the custom LLM-as-judge or programmatic code evaluators against historic database traces, calculating metrics such as faithfulness, correctness, or context recall after the user session has concluded.23  
The system must write these newly calculated metric scores back to the original database rows using the trace or span ID as the primary key.21  
The write-back process varies across different candidates:

- **Langfuse Pipeline**: The developer calls langfuse.create_score() using the exact trace_id and optional observation_id.21 To update or correct a score later without generating duplicate entries, an idempotency key must be passed in the id field.21 This ensures the underlying engine performs a safe merge rather than appending a duplicate row.21
- **Arize Phoenix Pipeline**: Spans are queried programmatically from the Phoenix server via the trace DSL and formatted as a Pandas DataFrame.23 The offline evaluations are executed in Python, mapped into a standard Phoenix annotation dataframe using the helper function to_annotation_dataframe(), and written back to the server asynchronously via the px_client.spans.upload_evaluations() API.22
- **Pure OpenTelemetry Pipeline**: OpenTelemetry span data is designed to be immutable once exported, meaning historical spans cannot be modified to append new evaluation attributes.1 Consequently, attaching offline metrics to a pure OTEL pipeline requires the engineering team to deploy a secondary analytics layer.1 This layer stores evaluation scores in a relational database or as distinct span events, using the traceId to join the telemetry tables during queries.1

The following Python 3.11 class implements an offline write-back evaluation manager for both Langfuse and Phoenix, utilizing idempotency keys to prevent duplicate evaluations.21

Python  
\# python_loc_estimate: \~42 lines  
import uuid  
from typing import Optional  
from langfuse import Langfuse  
from phoenix.client import AsyncClient  
from phoenix.evals.utils import to_annotation_dataframe  
import pandas as pd

class OfflineEvaluationWriter:  
def \_\_init\_\_(self, langfuse_client: Optional\[Langfuse\] \= None, phoenix_client: Optional\[AsyncClient\] \= None):  
self.langfuse \= langfuse_client  
self.phoenix \= phoenix_client

    def write\_score\_to\_langfuse(
        self,
        trace\_id: str,
        metric\_name: str,
        score\_value: float,
        explanation: str,
        observation\_id: Optional\[str\] \= None
    ) \-\> None:
        if not self.langfuse:
            return

        \# Standardize score\_id using a deterministic UUID to prevent duplicates
        score\_id \= str(uuid.uuid5(uuid.NAMESPACE\_DNS, f"{trace\_id}-{metric\_name}"))

        self.langfuse.create\_score(
            id\=score\_id, \# Serves as the idempotency key for updates
            trace\_id=trace\_id,
            observation\_id=observation\_id,
            name=metric\_name,
            value=score\_value,
            data\_type="NUMERIC",
            comment=explanation
        )

    async def write\_scores\_to\_phoenix(
        self,
        span\_id: str,
        metric\_name: str,
        score\_value: float,
        explanation: str
    ) \-\> None:
        if not self.phoenix:
            return

        \# Format the evaluation data as a standard Pandas DataFrame
        eval\_data \= \[{
            "span\_id": span\_id,
            "label": "pass" if score\_value \>= 0.8 else "fail",
            "score": score\_value,
            "explanation": explanation
        }\]
        df \= pd.DataFrame(eval\_data)

        \# Format the data into a standard Phoenix annotation dataframe
        phoenix\_annotation \= to\_annotation\_dataframe(df)

        \# Rename columns to map to the expected Phoenix schema \[22\]
        phoenix\_annotation \= phoenix\_annotation.rename(columns={
            "label": f"eval.{metric\_name}.label",
            "score": f"eval.{metric\_name}.score",
            "explanation": f"eval.{metric\_name}.explanation"
        })

        \# Upload the annotations asynchronously to the Phoenix server \[23\]
        await self.phoenix.spans.upload\_evaluations(phoenix\_annotation)

## **Tool-Agnostic RAG Telemetry Schema**

To ensure the custom evaluation harness remains framework-agnostic, we define a standard RAG Telemetry Schema. This schema maps core RAG concepts to both incubating OpenTelemetry Semantic Conventions and OpenInference attributes, ensuring complete compatibility with standard collectors.10

| RAG Logical Entity     | Concept Field        | OTEL Standard GenAI Attribute | OpenInference Equivalent                | Custom Evaluation Write-back Format |
| :--------------------- | :------------------- | :---------------------------- | :-------------------------------------- | :---------------------------------- |
| **System Metadata**    | Application Name     | service.name 53               | service.name 38                         | Trace Root Level Attribute          |
|                        | Pipeline Context     | gen_ai.pipeline.name 54       | traceloop.workflow.name 40              | Trace Root Level Attribute          |
|                        | Session/Conversation | gen_ai.conversation.id 39     | session.id 38                           | Trace Root Level Attribute          |
| **User Request**       | User Prompt Text     | gen_ai.input.messages 42      | input.value 41                          | Input Message Array                 |
| **LanceDB Search**     | DB Engine Name       | db.system.name 37             | db.system.name 41                       | Span Level Attribute                |
|                        | Query Collection     | db.collection.name 37         | db.collection.name 41                   | Span Level Attribute                |
|                        | Input Query Text     | db.query.summary 37           | input.value 41                          | String Query Attribute              |
|                        | Document Content     | N/A                           | retrieval.documents.i.document.content  | String Attribute Array 36           |
|                        | Document Score       | N/A                           | retrieval.documents.i.document.score    | Float Attribute Array 41            |
|                        | Document Metadata    | N/A                           | retrieval.documents.i.document.metadata | JSON String Attribute 41            |
| **LLM Generator**      | Target Model         | gen_ai.request.model 39       | llm.model_name 41                       | Span Level Attribute                |
|                        | Output Response      | gen_ai.output.messages 42     | output.value 41                         | Output Message Array                |
|                        | Input Tokens         | gen_ai.usage.input_tokens 39  | llm.token_count.prompt 41               | Integer Counter Metric              |
|                        | Output Tokens        | gen_ai.usage.output_tokens 39 | llm.token_count.completion 41           | Integer Counter Metric              |
|                        | Dynamic Cost USD     | gen_ai.usage.cost_usd 1       | llm.cost 38                             | Double Value Metric                 |
| **Offline Evaluation** | Metric Name          | gen_ai.evaluation.name 42     | evaluator.name 33                       | Score Name String 21                |
|                        | Metric Value         | gen_ai.evaluation.score.value | evaluator.score 33                      | Numeric Float Value 21              |
|                        | Evaluation Label     | gen_ai.evaluation.score.label | evaluator.label 33                      | Categorical String 21               |
|                        | Critic Explanation   | gen_ai.evaluation.explanation | evaluator.explanation                   | Text Comment String 21              |

## **Architectural Decision Record**

This Architectural Decision Record details the selection and integration strategy for the observability layer of the custom RAG evaluation harness.

### **Status**

Approved

### **Context and Problem Statement**

The development team requires a production-grade observability and evaluation layer for a lightweight, custom RAG system written in Python 3.11. The underlying infrastructure is highly customized: a LanceDB vector store executing hybrid search queries, custom Generator implementations, and custom offline LLM-as-judge evaluation workers. The team wants to avoid bloated frameworks like LangChain, LlamaIndex, or RAGAs to minimize system complexity and overhead.  
Key constraints include the ability to run on self-hosted infrastructure, complete compatibility with open-source licensing models (e.g., MIT or Apache 2.0), compliance with OpenTelemetry standards, and the ability to write back offline evaluation scores to historical database rows.

### **Decision**

The primary tool selected for tracking and evaluation is **Langfuse (Self-Hosted)**.6 **Arize Phoenix (Open Source)** is selected as the designated runner-up option.13  
To minimize ingestion latency and prevent data loss during operational spikes, a three-phase deployment timeline will be adopted:

- **Phase 1 (Immediate)**: Traces are persisted locally in standard JSONL format to a high-speed disk directory or a secure S3 bucket. This completely decouples trace persistence from user request-response lifecycles, guaranteeing zero network-associated latency overhead.12 It also establishes a highly durable source-of-truth for offline regression testing and subsequent batch ingestion.12
- **Phase 2 (Intermediate)**: Self-hosted Langfuse will be deployed using Docker Compose or Kubernetes, utilizing ClickHouse for analytics and PostgreSQL for transactional state.12 An asynchronous python exporter will be integrated to read Phase 1 JSONL data and stream it back into ClickHouse using standard SDK primitives, utilizing deterministic score IDs as idempotency keys.12
- **Phase 3 (Long-Term Target)**: Update the instrumentation layer to use standard OpenTelemetry GenAI Semantic Conventions.1 Instrument an intermediate OpenTelemetry Collector to export standard OTLP traces to both Langfuse (for LLM engineering and evaluations) and Grafana Tempo or Jaeger (for overall application performance monitoring).1

### **Consequences**

Deploying Langfuse ensures the custom RAG evaluation harness benefits from a highly scalable, open-source tracing UI that natively supports prompt management, human-in-the-loop annotation, and flexible score metrics.6 Offloading tracing computations to ClickHouse preserves transactional performance under high production loads, while the MIT-licensed core protects the system from vendor lock-in and unexpected pricing tiers.6  
The operational footprint of this architecture is relatively high.28 Running ClickHouse, Redis, and PostgreSQL instances requires active database maintenance, schema migration controls, and disk sizing profiles.12 However, the initial phase of JSONL disk serialization protects the runtime application from database downtimes, providing a secure, reliable deployment path.12  
If the team has limited DevOps bandwidth and prefers not to manage ClickHouse clusters, migrating to Arize Phoenix is a viable path.13 However, this requires sacrificing collaborative human annotation queues and native prompt playgrounds in the open-source UI.13 Utilizing the standard tool-agnostic telemetry schema outlined in this report ensures the engineering team can transition between Langfuse and Arize Phoenix without modifying the core RAG application code.1

#### **Referências citadas**

1. OpenTelemetry GenAI Semantic Conventions \- The Standard for LLM Observability, acessado em maio 25, 2026, [https://dev.to/x4nent/opentelemetry-genai-semantic-conventions-the-standard-for-llm-observability-1o2a](https://dev.to/x4nent/opentelemetry-genai-semantic-conventions-the-standard-for-llm-observability-1o2a)
2. LLMOps Observability: LangSmith vs Arize vs Langfuse vs W\&B | by Kanerika Inc \- Medium, acessado em maio 25, 2026, [https://medium.com/@kanerika/llmops-observability-langsmith-vs-arize-vs-langfuse-vs-w-b-f1baeabd1bbf](https://medium.com/@kanerika/llmops-observability-langsmith-vs-arize-vs-langfuse-vs-w-b-f1baeabd1bbf)
3. Get Started with Tracing \- Langfuse, acessado em maio 25, 2026, [https://langfuse.com/docs/observability/get-started](https://langfuse.com/docs/observability/get-started)
4. Using Tracing Helpers \- Phoenix \- Arize AI, acessado em maio 25, 2026, [https://arize.com/docs/phoenix/tracing/how-to-tracing/setup-tracing/instrument](https://arize.com/docs/phoenix/tracing/how-to-tracing/setup-tracing/instrument)
5. Setup Tracing \- Phoenix \- Arize AI, acessado em maio 25, 2026, [https://arize.com/docs/phoenix/tracing/how-to-tracing/setup-tracing](https://arize.com/docs/phoenix/tracing/how-to-tracing/setup-tracing)
6. LangSmith Alternative? Langfuse vs. LangSmith for LLM Observability \- Langfuse, acessado em maio 25, 2026, [https://langfuse.com/faq/all/langsmith-alternative](https://langfuse.com/faq/all/langsmith-alternative)
7. How can I self-host Langfuse?, acessado em maio 25, 2026, [https://langfuse.com/faq/all/self-hosting-langfuse](https://langfuse.com/faq/all/self-hosting-langfuse)
8. Why is Langfuse Open Source?, acessado em maio 25, 2026, [https://langfuse.com/handbook/chapters/open-source](https://langfuse.com/handbook/chapters/open-source)
9. phoenix/.agents/skills/phoenix-tracing/SKILL.md at main · Arize-ai/phoenix · GitHub, acessado em maio 25, 2026, [https://github.com/Arize-ai/phoenix/blob/main/.agents/skills/phoenix-tracing/SKILL.md](https://github.com/Arize-ai/phoenix/blob/main/.agents/skills/phoenix-tracing/SKILL.md)
10. opentelemetry-semantic-conventions-ai \- PyPI, acessado em maio 25, 2026, [https://pypi.org/project/opentelemetry-semantic-conventions-ai/](https://pypi.org/project/opentelemetry-semantic-conventions-ai/)
11. OpenTelemetry Semantic Conventions \- Standard Attributes for Traces, Metrics & Logs, acessado em maio 25, 2026, [https://uptrace.dev/opentelemetry/semconv](https://uptrace.dev/opentelemetry/semconv)
12. Self-host Langfuse (Open Source LLM Observability), acessado em maio 25, 2026, [https://langfuse.com/self-hosting](https://langfuse.com/self-hosting)
13. Phoenix vs Langfuse 2026: OSS LLM Observability Compared \- Future AGI, acessado em maio 25, 2026, [https://futureagi.com/blog/arize-phoenix-vs-langfuse-2026](https://futureagi.com/blog/arize-phoenix-vs-langfuse-2026)
14. Self-hosted LangSmith \- Docs by LangChain, acessado em maio 25, 2026, [https://docs.langchain.com/langsmith/self-hosted](https://docs.langchain.com/langsmith/self-hosted)
15. Enterprise License Key (self-hosted) \- Langfuse, acessado em maio 25, 2026, [https://langfuse.com/self-hosting/license-key](https://langfuse.com/self-hosting/license-key)
16. How do I obtain a self-hosted LangSmith license key? \- LangChain Support Portal, acessado em maio 25, 2026, [https://support.langchain.com/articles/7011309930-how-do-i-obtain-a-self-hosted-langsmith-license-key](https://support.langchain.com/articles/7011309930-how-do-i-obtain-a-self-hosted-langsmith-license-key)
17. phoenix/docs/phoenix/skill.md at main · Arize-ai/phoenix \- GitHub, acessado em maio 25, 2026, [https://github.com/Arize-ai/phoenix/blob/main/docs/phoenix/skill.md](https://github.com/Arize-ai/phoenix/blob/main/docs/phoenix/skill.md)
18. LLM Observability & Application Tracing (Open Source) \- Langfuse, acessado em maio 25, 2026, [https://langfuse.com/docs/observability/overview](https://langfuse.com/docs/observability/overview)
19. Log LLM calls \- Docs by LangChain, acessado em maio 25, 2026, [https://docs.langchain.com/langsmith/log-llm-trace](https://docs.langchain.com/langsmith/log-llm-trace)
20. OpenTelemetry for AI Systems: LLM and Agent Observability (2026) \- Uptrace, acessado em maio 25, 2026, [https://uptrace.dev/blog/opentelemetry-ai-systems](https://uptrace.dev/blog/opentelemetry-ai-systems)
21. Scores via API/SDK \- Langfuse, acessado em maio 25, 2026, [https://langfuse.com/docs/evaluation/evaluation-methods/scores-via-sdk](https://langfuse.com/docs/evaluation/evaluation-methods/scores-via-sdk)
22. Run online evals on traces \- Arize AX Docs, acessado em maio 25, 2026, [https://arize.com/docs/ax/evaluate/run-evals-on-traces](https://arize.com/docs/ax/evaluate/run-evals-on-traces)
23. phoenix/tutorials/evals/evals_quickstart.ipynb at main · Arize-ai/phoenix \- GitHub, acessado em maio 25, 2026, [https://github.com/Arize-ai/phoenix/blob/main/tutorials/evals/evals_quickstart.ipynb](https://github.com/Arize-ai/phoenix/blob/main/tutorials/evals/evals_quickstart.ipynb)
24. Manage datasets \- Docs by LangChain, acessado em maio 25, 2026, [https://docs.langchain.com/langsmith/manage-datasets](https://docs.langchain.com/langsmith/manage-datasets)
25. Log user feedback using the SDK \- Docs by LangChain, acessado em maio 25, 2026, [https://docs.langchain.com/langsmith/attach-user-feedback](https://docs.langchain.com/langsmith/attach-user-feedback)
26. OpenTelemetry Semantic Conventions: An Explainer \- Dash0, acessado em maio 25, 2026, [https://www.dash0.com/knowledge/otel-semantic-conventions-explainer](https://www.dash0.com/knowledge/otel-semantic-conventions-explainer)
27. Scaling Langfuse Deployments, acessado em maio 25, 2026, [https://langfuse.com/self-hosting/configuration/scaling](https://langfuse.com/self-hosting/configuration/scaling)
28. Langfuse Pricing 2026: Plans, Costs & Breakdown \- CheckThat.ai, acessado em maio 25, 2026, [https://checkthat.ai/brands/langfuse/pricing](https://checkthat.ai/brands/langfuse/pricing)
29. LLM Evaluation Frameworks: Head-to-Head Comparison \- Comet, acessado em maio 25, 2026, [https://www.comet.com/site/blog/llm-evaluation-frameworks/](https://www.comet.com/site/blog/llm-evaluation-frameworks/)
30. Top LLM Evaluation Platforms: In Depth Comparison : r/AI_Agents \- Reddit, acessado em maio 25, 2026, [https://www.reddit.com/r/AI_Agents/comments/1pa02zc/top_llm_evaluation_platforms_in_depth_comparison/](https://www.reddit.com/r/AI_Agents/comments/1pa02zc/top_llm_evaluation_platforms_in_depth_comparison/)
31. LangSmith Plans and Pricing \- LangChain, acessado em maio 25, 2026, [https://www.langchain.com/pricing](https://www.langchain.com/pricing)
32. Best LLM Observability Tools for AI Agents: Latitude vs Langfuse, LangSmith, Arize, and Braintrust (2026), acessado em maio 25, 2026, [https://latitude.so/blog/best-llm-observability-tools-agents-latitude-vs-langfuse-langsmith](https://latitude.so/blog/best-llm-observability-tools-agents-latitude-vs-langfuse-langsmith)
33. OpenInference Specification \- GitHub Pages, acessado em maio 25, 2026, [https://arize-ai.github.io/openinference/spec/](https://arize-ai.github.io/openinference/spec/)
34. OpenTelemetry GenAI Semantic Conventions | MLflow AI Platform, acessado em maio 25, 2026, [https://mlflow.org/docs/latest/genai/tracing/opentelemetry/genai-semconv/](https://mlflow.org/docs/latest/genai/tracing/opentelemetry/genai-semconv/)
35. Advanced Features \- Langfuse, acessado em maio 25, 2026, [https://langfuse.com/docs/observability/sdk/advanced-features](https://langfuse.com/docs/observability/sdk/advanced-features)
36. \[bug\] retriever for vector store search missing retrieved documents · Issue \#2627 · Arize-ai/openinference \- GitHub, acessado em maio 25, 2026, [https://github.com/Arize-ai/openinference/issues/2627](https://github.com/Arize-ai/openinference/issues/2627)
37. Semantic conventions for database client spans \- OpenTelemetry, acessado em maio 25, 2026, [https://opentelemetry.io/docs/specs/semconv/db/database-spans/](https://opentelemetry.io/docs/specs/semconv/db/database-spans/)
38. Introduction to OpenInference \- OpenInference, acessado em maio 25, 2026, [https://arize-ai-openinference.mintlify.app/introduction](https://arize-ai-openinference.mintlify.app/introduction)
39. Semantic Conventions for GenAI agent and framework spans \- OpenTelemetry, acessado em maio 25, 2026, [https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/)
40. GenAI Semantic Conventions \- traceloop, acessado em maio 25, 2026, [https://www.traceloop.com/docs/openllmetry/contributing/semantic-conventions](https://www.traceloop.com/docs/openllmetry/contributing/semantic-conventions)
41. Semantic Conventions | openinference \- GitHub Pages, acessado em maio 25, 2026, [https://arize-ai.github.io/openinference/spec/semantic_conventions.html](https://arize-ai.github.io/openinference/spec/semantic_conventions.html)
42. Gen AI | OpenTelemetry, acessado em maio 25, 2026, [https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/)
43. Pricing \- NanoGPT, acessado em maio 25, 2026, [https://nano-gpt.com/pricing](https://nano-gpt.com/pricing)
44. How to Monitor OpenAI API Costs and Token Usage with OpenTelemetry \- OpenObserve, acessado em maio 25, 2026, [https://openobserve.ai/blog/monitor-openai-api-costs-opentelemetry/](https://openobserve.ai/blog/monitor-openai-api-costs-opentelemetry/)
45. Models and pricing \- Monica API Platform, acessado em maio 25, 2026, [https://platform.monica.im/docs/en/models-and-pricing](https://platform.monica.im/docs/en/models-and-pricing)
46. OpenDataSky AI Model Pricing, acessado em maio 25, 2026, [https://opendatasky.com/document/en/pricing.html](https://opendatasky.com/document/en/pricing.html)
47. LLM Pricing: Top 15+ Providers Compared \- AIMultiple, acessado em maio 25, 2026, [https://aimultiple.com/llm-pricing](https://aimultiple.com/llm-pricing)
48. LLM Price Comparison Tool \- Langtail, acessado em maio 25, 2026, [https://langtail.com/llm-price-comparison](https://langtail.com/llm-price-comparison)
49. Run offline evals on experiments \- Arize AX Docs, acessado em maio 25, 2026, [https://arize.com/docs/ax/evaluate/run-evals-on-experiments](https://arize.com/docs/ax/evaluate/run-evals-on-experiments)
50. LLM-as-a-Judge \- Langfuse, acessado em maio 25, 2026, [https://langfuse.com/docs/evaluation/evaluation-methods/llm-as-a-judge](https://langfuse.com/docs/evaluation/evaluation-methods/llm-as-a-judge)
51. Support for Metric Calculation (Precision@K, Recall@K) and Adding ..., acessado em maio 25, 2026, [https://github.com/orgs/langfuse/discussions/5215](https://github.com/orgs/langfuse/discussions/5215)
52. Evaluating AI Agents with Arize Phoenix | by Amanatullah \- Medium, acessado em maio 25, 2026, [https://medium.com/@amanatulla1606/evaluating-ai-agents-with-arize-phoenix-8ca60cc52f4a](https://medium.com/@amanatulla1606/evaluating-ai-agents-with-arize-phoenix-8ca60cc52f4a)
53. How to Implement Semantic Conventions in OpenTelemetry \- OneUptime, acessado em maio 25, 2026, [https://oneuptime.com/blog/post/2026-01-25-semantic-conventions-opentelemetry/view](https://oneuptime.com/blog/post/2026-01-25-semantic-conventions-opentelemetry/view)
54. AI Agents Module \- Sentry Developer Documentation, acessado em maio 25, 2026, [https://develop.sentry.dev/sdk/telemetry/traces/modules/ai-agents/](https://develop.sentry.dev/sdk/telemetry/traces/modules/ai-agents/)
55. Retrieve Traces via CLI \- Phoenix \- Arize AI, acessado em maio 25, 2026, [https://arize.com/docs/phoenix/tracing/how-to-tracing/importing-and-exporting-traces/retrieve-traces-via-cli](https://arize.com/docs/phoenix/tracing/how-to-tracing/importing-and-exporting-traces/retrieve-traces-via-cli)

[image1]: data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAsAAAAeCAYAAAD6t+QOAAAAz0lEQVR4Xu3STQpBURwF8KuIolBMxBKIRShlwoBFGNgCMwMZGCiZKhmwBRswYAuyBDMTzvHOzbvvmbwhOfWrd+89vY9/z5jvTQJGsoCOe+wmDj15QN89DqcmLFcCZ6FEKg/kGjz4lI1steZHt6VkSzYXGUIBlrCSna9nysZ7V2rBFJJwktm7GrHMudryAfLaz4qTORyFd+FEqk7DF5bGwuyN92E2XXuRgjs0heH4JtAQzv+VSOU63CAjDB97hrWktW9iULQLX3LG+xvpn5/IE1FOL4dIyi2AAAAAAElFTkSuQmCC
[image2]: data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACUAAAAYCAYAAAB9ejRwAAAB8ElEQVR4Xu2UMUhVURjHv8JMTQnDQXFoMSQRxYYWpU1KIaxJghZBohYRdXNxcJAG0cAWiYeghCEIggYKhYnVUKQmuiQGqTiJ0OSi/b/3nfve6f/ufeYWcn/wG+7/O/fe755zzxGJOWfkOv+V67CIwyyc5dnSBz/AKecCvOEPiCAB9+A7+BbOwVlPbVqphIvwNfwCe1weSRdcghe87DFch5e9LIyP8CfcgN/hGtyB750XYT7ch412i1yCm2LvUEP575rSm7ZhN+UF8ATep5zR5fLJE1v6MqfSBn+nRhjP4VdnBjfFXh7WsT5oiEOPHEl/fcAwvEvZJPxBmU7CsbOYanJHrKmHXBCb8jccZkGbGeNQbBOsUvZU7L1qFdWSzWihhQtiu2qewyzoi+s4FMu/UfZE0k3VUy35dVp4wAWxmZrmMIImeMih4xNcocyfqVqqyS1XaOUCOICjHEagy7zMoWNGbLf5dEi6qXKqJXeL/tCdIbne0E55FLsSPau9kjmLA/CX0z+KUrwSO2l9dAPog0rcdSHcgi9TI9KUin3AOBccFfBI7FQP0J+/3xnKFfgZvoDPnPoP3PbG6LmlB+SglwUETY1wweOR2MGqM5+AE2JnpBqJTmENvOe8+nf5VBrgNQ4JfWYzrJaIJYuJiYkh/gAJmnFvhAZO+wAAAABJRU5ErkJggg==
[image3]: data:image/png;base64,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
[image4]: data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAA8AAAAbCAYAAACjkdXHAAAAyklEQVR4XmNgGNJAE4jjCOBYKA4HYnWINgigSPNmIL4BxPVQnAfEu4D4PxC3AnEmktwbIM6BaGNg4APik0DMChOAgnVA/B6ImdDEe4HYFcaJgmJkwAjErxkgLkIH04FYBsYB+YMDIQcG2gwQJ5egiYMAyAt4QRYDRLMpugQxYBUQfwJiZnQJYsALIN6OLkgIaEAxyMmVaHIEAUWa06EYpNkaTY4gWAnF34GYDU0OK9AD4iNAfAaIv0DxDyC+CMSHgZgXoXQUjAJ6AgCEByxYuAX3cwAAAABJRU5ErkJggg==
[image5]: data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAcCAYAAABoMT8aAAAA1UlEQVR4Xu3SvQ7BcBTG4ROLyS2IGzAw2iSsDFaTCyBEfKwGK5cgroDBDUgsRlaLwehjNfG+/R9Je5ImbTpY+kueRHraU20qkmZrqRGMYaK/h9CFogqtoubwgSU0oAkDuKmVnh/aVNyCgjneU5zVzSzQDq72oLjHIS5om5lXRr1gbWbspC6QNTOvsuIdOr7jOZjBU1V9s0CJF/QVF+xhA1s4wgLyKjSeTA9x7yJWvIAXEu8cu5K4v058jNjxc/0t4IuMXA0OcIe3Oov7dCOVeEFa2v/7Atn6OHEX1GsCAAAAAElFTkSuQmCC
[image6]: data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADIAAAAZCAYAAABzVH1EAAACg0lEQVR4Xu2WTYiNYRTHz5jBmIgJKzJZqEEWFtPIkCRfjSKZnZAoMVKKFBqSr4WS2EiSoiZkM1PKAlnMSD4WNhZSPiI2apqFb/9/55yZc1/vO/N2r9Sd7q9+dc+557n3nud9Pq5IhQr/lZpkogj4GaOSyRTGJBMp5KlJpWwb4ZcuhEfMD3B0eD8vE+Et8zZ8CM9J4Q+pMk/A+6J1XXBaqHHmin7GdfgEbi98+2/2wYuw2/wtxTVyBx4yHf7Q4yE+YN4NuT2iP5gNOuPhZ7jI4jr4Di4fqBgCNkSLaWSW6Lg5prMJfpHBpfbG3BlqZoiObQq5bfBTiMll0YkellIa2SU6borprLJ8s+hS4Wu6IdTUWm5/yN2AL0JMTsF+GVyemZTSyFHRceNMZ7Hl18Gl9pquDjXkJzwb4gfwUYjJYdGxk8xMYiO5TwrjvOi4sabTYvktok/BG1kZash3eCXEfBo9ISYHRcfONDMppZHTouO4TKjDzcp8m+hT8Ea45CI/4IUQ82n0hpjwEOHYqWYmI7KRuDzy4ON4l1BnmeW5P5rsNV0baqotx33mdMNnISbH4C/ReppJbCTOah6WiI5rNJ2N8Jvo5uQh0G/uCDXTRce2hlwH/Bhicgk+TuRSiY3Ek4dw07411yTeI7wjXoveG9ThzX4zxFdN3gnOevheClcBJ+MrbLCYx+1z2D5QkQJnh8cdb07aB1/Be3Cy1SwQvaDoNcslmQdfmnvhSdHP4C3tTDA5s2fgbtElNDvUOJvhU7gVdopOyj+Bdwvl35ks/PjlnmDzWX9AOcPz4QopbDRJveiSi8u1ZHjqUG7asoV7hk9iqKdRNgz716BcGDGNVKiQkz9kRpnl5DwmUwAAAABJRU5ErkJggg==
[image7]: data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAB8AAAAZCAYAAADJ9/UkAAABs0lEQVR4Xu2VuyvGYRTHj0sk15LJ5LYowsBEmZT4AzCRGE3KJkwuGaQY3SnXMrAYXEqug5LChBRiMTAI39M5P877+L0oheH91Kfe85znfc9zOb/fSxTin5EJE9xBQ7Q74MN35vjyZ8WT4RUsdsar1U04CTdgQcAMIZckNwH3YFVg+nPG4QsFFufPl2qcjpXAC5joTQLx8BYWapwEr2GRGpRKdZg+FuedjqkWLlRn4kaSBVlm4YjqC69+Xs2jj8XvYK9qOYKjJp6D+yZmBuC56ks/zDHa4pHwGXaoll24YuJ11dIDn9QwJ0elsNXEbvEUjdtUyzZJU3kcwlUTM10k32e5J96IgQswyoy5xWM19tv5DlxzYnfn3SQnx0bYxJ8Wb4aLJD/arg6SFBui905+gJ2q5YCkyTyW4JaJmT6ShmUDyCC5cysviIs3wXydx/fo97jcwBYTc0+cmZiZhsvql5SRFOeXiEcDSTOx4TqWRnIivAGPbPgIUzXmYz6FNWpQptRjeA9PSI7Mg18+7AzJdfD9lpu8Rz1Jrpakn9w++RHpsILkEQwG/z/wnCw3ESJEiF/lFV/QdGDgN+8wAAAAAElFTkSuQmCC
[image8]: data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAB8AAAAZCAYAAADJ9/UkAAAB30lEQVR4Xu2UP0hXURTHj2k1qBiIEjhlBBLh0JAE6tIgikOTUE1FlINTQ5pTISKlOLg0BIF/UEQLl7DFQQui/2BGixCUOBi5KhHp98s5D8+97/2wSZf3gc9wzj2P+9695zyRnEOkOE4YR+KE43icyOB/ag5387vwO5w1n8JlOOCLwFXzDZyCr+H5oEKpF12bhB/hlXA5pBf+gX/Nz7ArqBBpgutmmeWa4RqsSIpAOfwNL1h8Am7ABjNFD2yDJWYW/NIJ08ONbrj4tugLeZ7BMTNFN2yNkxGbcNj0fIPjLn4OP7mYPIY/zRS880HYby7Ce7LXcDyNf7DP9HyACy5+ZXqGZO9Ki6I16YT3XcwCNt60xVVwBz4wPe9Emyrhq+jLex6JPk/ZE/tyS7QJ2Uylog9mffl7uBTF8ZfzVHlytNBYBxzY5hyrc1GuQ3TDyxZvwYemh/8DNlnCPHzrYjIi2rA0oFp0E3akh+PDfKPFvMescfklOqoJ7IkfLiYz8KWZgsmTUY6bfIFHLeY1sJloMgWnRE/ktMXkLNyGNRbzmFfhNTNFC3wB75hP4Aqs80Vg1OQk8GR4v/w5xdwUXbsO5yTdJyk4y5fMi/BYuBxQC9tFR7AQlaI1Z+KFnJycA2UXD5hzgyvqV2cAAAAASUVORK5CYII=
[image9]: data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACYAAAAYCAYAAACWTY9zAAACT0lEQVR4Xu2VWahOURiGP2PmKRkihUyJQpSSOZJyoxDqGFJEilIyXRCZiwsSkmS8kCFlKCWSC8l0Y7w1XCClSOJ9+96993f2Wefvz9W5+J96an1rrb332mv4llmNpkEPuAx2lClawunlysZoBZvJSrSWKSbAG3AavC8Xw+ahT3d4E84NdUnaw93wKrws78JxsRMYDO/B8/Ix3Fivh9kluFDlOfIa3C/3wTvwnPpUZAM8o3I2Y+/gN9hN9W3hRzhTMeFyvDRfNsJZ+QKnKu4nDyomXBXOaPbeijTZgXG9f1v9jXoa/oUjFS+BP/LWgp3wRYi/whkqc+npuqLZtsPZIa4IRz+0VMeZeB3iC/B9iDPWmv9AT8WcjdUqr5TDFY+Fx1SuGi7DAHhEvoJjQjsPQ5yZjOXmAxuluC98ZD4zZyVpA2/BToqrhrmHJ/OKPAm7hPZnssxS84FNCXUt4BDzn83SxAEr9h7fe1h2kFVzCn6CvRU/hM+L5hxufA6snFoik+Ahlbn535rvvdHmk0GT9DJ/ILLA/INbFDPHcXnLrDLv17/cYEXm5xK2Ux0H+TTvYbZXNmAQ/AOvl+oXmX/wuOJN8HvRnLPDPI3EzJ5xVI4PdZvhgxBnfRpcXfzTX3BbqZ4ZmgObpXgg/AmH5T2c25b+Yz63S0bq4JMQc+/RJPPgG7gHbpWf4ZrYCcw3P5kr5Al40XyzR7qap43UncpT+8E8PfWx4qpqFB7nieaXMGVWT9HZfDboCEtf+OutyF0pJpvfqcyNHBytUaNGjf/hH3C4dmTaGGaxAAAAAElFTkSuQmCC
