# AI Agentic System: Insurance Claim & Support Worker

A containerized, event-driven AI agentic system built with Python, Kafka, PostgreSQL, and the GCP Gemini API. The system simulates a production-grade background worker that autonomously processes insurance inquiries and claims using LLM function calling, with built-in resilience and cost control.

---

## System Architecture

```
[Producer] ──► [Kafka: incoming-requests] ──► [Agent / Consumer]
                                                      │
                                              [Tool: PolicyDatabase]
                                                      │
                                                [PostgreSQL]
                                                      │
                                         [Kafka: processed-events]
```

The architecture is deliberately decoupled so that each component has a single responsibility and can be scaled or replaced independently.

- **Producer** — Simulates incoming customer requests (standard inquiries and edge cases) and publishes them to Kafka. Includes application-level retry logic to bridge the gap between Docker healthcheck passing and Kafka being truly ready.
- **Kafka (KRaft mode)** — Acts as the asynchronous message broker. Buffers requests so the upstream system is never blocked by LLM processing latency. Runs without Zookeeper using the modern KRaft consensus protocol.
- **Agent (Consumer)** — The core AI worker. Consumes messages from Kafka, reasons using `gemini-2.5-flash`, and autonomously decides when to invoke database tools. Publishes structured results to `processed-events` for downstream consumption.
- **PostgreSQL** — The source of truth for policy data. Accessed exclusively through the `PolicyDatabase` tool, which is injected into the Agent.

---

## Quick Start

### Prerequisites

- Docker and Docker Compose (v2) installed
- A valid GCP Gemini API Key

### Setup

1. Create a `.env` file in the project root:

   ```bash
   GEMINI_API_KEY=your_actual_api_key_here
   DB_USER=user
   DB_PASSWORD=password
   DB_NAME=insurance_db
   ```

   > `.env` is already listed in `.gitignore` and will never be committed to version control.

2. Build and start all services:

   ```bash
   docker compose up --build -d
   ```

3. Watch the agent process tasks in real time:

   ```bash
   docker logs -f agent_consumer
   ```

4. Gracefully shut down and clean up:

   ```bash
   docker compose down
   ```

---

## Design Reasoning

### 1. Clean Architecture & Isolatable Dependencies

`agent.py` is structured around OOP and Dependency Injection (DI) to maximise maintainability and testability.

**Separation of Concerns** — `PolicyDatabase` owns all PostgreSQL interactions; `InsuranceAgent` owns LLM reasoning. Neither class knows about Kafka. The Kafka integration lives exclusively in `main()`, which wires the components together.

**Verifiability** — Because the Agent receives its database tool via constructor injection, swapping the real `PolicyDatabase` for a `MockDB` in tests requires zero changes to agent logic. The core reasoning loop is testable in complete isolation.

**Connection Pooling** — `PolicyDatabase` uses `psycopg2.SimpleConnectionPool` rather than opening a new connection per query. This eliminates per-query connection overhead and caps the maximum number of concurrent database connections to 5, making resource consumption predictable.

### 2. Stability & Graceful Degradation

**Two-Layer Readiness Check** — Docker Compose `service_healthy` conditions enforce startup order at the orchestration level. The Producer additionally performs an application-level check using `list_topics()` with retry logic, because *infrastructure healthy ≠ application ready* in distributed systems. This two-layer approach catches the gap between a container passing its healthcheck and the application inside being fully operational.

**No Data Loss (Manual Commit)** — `enable.auto.commit` is set to `False`. A Kafka offset is committed only after the Agent has successfully processed and published the result. If processing fails for any reason, the message remains in Kafka and will be redelivered on the next consumer run.

**429 Rate Limit Handling** — On receiving a 429 response, the Agent retries up to 3 times with linear backoff (60s → 120s → 180s). Only on confirmed success is the offset committed. If all retries are exhausted, the message is intentionally left uncommitted so it is preserved for the next run without manual intervention.

**Dead Letter Queue (DLQ)** — Malformed messages (e.g., invalid JSON) that cannot be parsed are forwarded to `incoming-requests.DLQ` before the offset is committed. This ensures unparseable messages never block the main queue, while remaining available for manual inspection and replay once the root cause is resolved.

**Edge Case Resiliency** — The Producer injects "poison pill" messages: requests with missing policy numbers and requests referencing non-existent policy IDs. The Agent handles these gracefully via LLM reasoning rather than crashing.

### 3. Code Ownership & Cost Awareness

**Model Selection** — `gemini-2.5-flash` was chosen over the Pro variant. For structured classification and database tool-use, Flash provides the right balance of low latency and cost-effectiveness. The model can be swapped in a single line if requirements change.

**Token Tracking** — Every API call captures `usage_metadata` and logs Prompt Tokens, Candidate Tokens, and a running cumulative total as separate values. Input and output tokens carry different unit costs on Gemini's pricing model, so separating them makes it possible to diagnose whether cost growth is driven by prompt design (input) or response verbosity (output).

**Controlled Throughput** — The Producer randomises its send interval between 10 and 20 seconds, simulating realistic traffic patterns and preventing runaway token consumption during development.

### 4. Secret Management

Secrets are loaded from a `.env` file via Docker Compose environment variable substitution. The `.env` file is excluded from version control via `.gitignore`. In a production environment, this would be replaced with a dedicated secret manager such as GCP Secret Manager or AWS Secrets Manager.

---

## Project Structure

```
.
├── docker-compose.yml
├── .env                    # Not committed — see Setup
├── .gitignore
├── db_init/
│   └── init.sql            # Schema and seed data for PostgreSQL
├── producer/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py             # Kafka Producer with retry logic
└── consumer/
    ├── Dockerfile
    ├── requirements.txt
    └── agent.py            # PolicyDatabase + InsuranceAgent + Kafka Consumer
```

---

## Future Enhancements

**Partition Scaling** — The current setup uses a single Kafka partition. To horizontally scale consumers, the topic partition count would need to be increased, allowing multiple consumer instances within the same `group.id` to process messages in parallel without duplication.

**Thread-Safe Token Accounting** — The current token counter is a class-level variable suitable for single-threaded operation. In a multi-threaded consumer, this would be replaced with an atomic counter or a `threading.Lock`-protected update to eliminate race conditions.

**Persistent Result Storage** — Agent responses are currently published to `processed-events` and logged. A natural next step is writing structured results to a `results` table in PostgreSQL to support audit trails, analytics, and replay.