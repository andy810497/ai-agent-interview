# AI Agentic System: Insurance Claim & Support Worker

## Objective
A containerized, asynchronous AI agentic system built with Python, Kafka, PostgreSQL, and the GCP Gemini API. This system simulates a background worker that processes insurance inquiries and claims, demonstrating autonomous tool-use (Function Calling), cost awareness, and production-grade resilience.

## System Architecture

The system follows a decoupled, event-driven architecture to ensure stability under fluctuating LLM API latency.

* **Producer:** Simulates incoming customer requests (both standard inquiries and edge cases like missing info) and publishes them to Kafka. Includes application-level retry logic to handle the gap between Docker healthcheck passing and Kafka being fully ready.
* **Kafka (KRaft mode):** Acts as the asynchronous message broker, buffering requests so the upstream isn't blocked by LLM processing times. Runs without Zookeeper using the modern KRaft consensus protocol.
* **Agent (Consumer):** The core AI worker. It consumes messages, reasons using `gemini-2.5-flash`, and autonomously decides when to query the database.
* **PostgreSQL:** Serves as the source of truth for policy data.

## Quick Start

### Prerequisites
* Docker and Docker Compose (v2) installed.
* A valid GCP Gemini API Key.

### Setup

1. Create a `.env` file in the project root:
   ```bash
   GEMINI_API_KEY=your_actual_api_key_here
   ```
   > `.env` is already in `.gitignore` and will never be committed to version control.

2. Build and start all services:
   ```bash
   docker compose up --build -d
   ```

3. Watch the agent in action:
   ```bash
   docker logs -f agent_consumer
   ```

4. Gracefully shut down and clean up:
   ```bash
   docker compose down
   ```

---

## Design Reasoning & Evaluation Criteria

### 1. Code Quality & Isolatable Dependencies (Clean Architecture)

`agent.py` is structured using OOP and Dependency Injection (DI) to ensure high maintainability and testability.

* **Separation of Concerns:** `PolicyDatabase` handles all PostgreSQL interactions; `InsuranceAgent` handles LLM reasoning. Neither knows about Kafka.

* **Verifiability:** The agent's core logic is completely decoupled from Kafka and the actual database. In a testing environment, the database dependency can be replaced with a `MockDB` without altering any agent logic.

* **Connection Pooling:** `PolicyDatabase` uses `psycopg2.SimpleConnectionPool` instead of opening and closing a new connection on every query. This avoids connection overhead at scale and bounds the maximum number of concurrent DB connections.

### 2. Stability & Graceful Degradation

The system is designed to remain stable under common failure and edge cases.

* **Two-Layer Readiness Check:** Docker Compose `service_healthy` conditions ensure infrastructure is up before containers start. The Producer additionally performs an application-level Kafka connectivity check (`list_topics`) with retry logic on startup — because *infrastructure ready ≠ application ready* in distributed systems.

* **No Data Loss (Manual Commit):** `enable.auto.commit` is set to `False`. Messages are only committed after the agent successfully processes them. If processing fails, the message remains in Kafka and will be reprocessed.

* **429 Rate Limit Handling with Retry:** Instead of sleeping once and discarding the message, the agent retries up to 3 times with exponential backoff (60s → 120s → 180s). Only on confirmed success is the Kafka offset committed. If all retries are exhausted, the message is intentionally not committed, preserving it for the next consumer run.

* **Dead Letter Queue (DLQ):** Malformed messages (e.g., invalid JSON) that cannot be processed are forwarded to a `incoming-requests.DLQ` Kafka topic before being committed. This ensures bad messages don't block the main queue, while still being available for manual inspection and replay after the root cause is fixed.

* **Edge Case Resiliency:** The producer injects "poison pills" (missing policy numbers, fake IDs). The agent uses LLM reasoning to gracefully handle these instead of crashing.

### 3. Code Ownership & Cost Awareness

Controlling LLM token consumption is a primary design consideration for this pipeline.

* **Model Selection:** `gemini-2.5-flash` was chosen over the Pro version. For procedural classification and database tool-use, Flash provides the right balance of low latency and cost-effectiveness.

* **Token Tracking Ledger:** Every API call intercepts `usage_metadata` and logs Prompt Tokens, Candidate Tokens, and a running cumulative total separately — because input and output tokens have different unit costs on Gemini's pricing model, making it possible to diagnose whether cost is driven by prompt design or response verbosity.

### 4. Secret Management

API keys are loaded from a `.env` file via Docker Compose environment variable substitution (`${GEMINI_API_KEY}`). The `.env` file is excluded from version control via `.gitignore`. In a production environment, this would be replaced with a dedicated secret manager (e.g., GCP Secret Manager or AWS Secrets Manager).

---

## Future Enhancements

* **Downstream Integration:** Instead of only logging the final answer, publish the agent's structured output to a `processed-events` Kafka topic for downstream microservices to consume.

* **Partition Scaling:** The current setup uses a single Kafka partition. To horizontally scale consumers, the topic partition count would need to be increased, allowing multiple consumer instances within the same `group.id` to process messages in parallel.