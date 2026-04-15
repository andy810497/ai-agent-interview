# AI Agentic System: Insurance Claim & Support Worker

## Objective
A containerized, asynchronous AI agentic system built with Python, Kafka, PostgreSQL, and the GCP Gemini API. This system simulates a background worker that processes insurance inquiries and claims, demonstrating autonomous tool-use (Function Calling), cost awareness, and production-grade resilience.

## System Architecture

The system follows a decoupled, event-driven architecture to ensure stability under fluctuating LLM API latency.

* **Producer:** Simulates incoming customer requests (both standard inquiries and edge cases like missing info) and publishes them to Kafka.
* **Kafka (KRaft mode):** Acts as the asynchronous message broker, buffering requests so the upstream isn't blocked by LLM processing times.
* **Agent (Consumer):** The core AI worker. It consumes messages, reasons using `gemini-2.5-flash`, and autonomously decides when to query the database.
* **PostgreSQL:** Serves as the source of truth for policy data.

## Quick Start

### Prerequisites
* Docker and Docker Compose (v2) installed.
* A valid GCP Gemini API Key.

### Run the System
1. Open `docker-compose.yml` and replace `YOUR_GEMINI_API_KEY_HERE` with your actual API key.
2. Build and start the infrastructure and services:
   ```bash
   docker compose up --build -d
3. Watch the agent in action (monitor the logs):
   ```bash
   docker logs -f agent_consumer
4. To gracefully shut down and clean up:
   ```bash
   docker compose down


### Design Reasoning & Evaluation Criteria
1. Code Quality & Isolatable Dependencies (Clean Architecture)
The agent.py is structured using Object-Oriented Programming (OOP) and Dependency Injection (DI) to ensure high maintainability and testability.

* Separation of Concerns: The PolicyDatabase class handles all PostgreSQL interactions, while the InsuranceAgent class handles LLM reasoning.

* Verifiability: The agent's core logic is completely decoupled from Kafka and the actual database. In a testing environment, the database dependency can be easily replaced with a MockDB without altering the agent's logic.

2. Stability & Graceful Degradation
The system is designed to remain stable under common failure and edge cases:

* Kafka Healthchecks: Docker Compose uses service_healthy conditions for Kafka and PostgreSQL. The Python consumer will wait patiently until the infrastructure is fully ready, preventing connection refusal loops.

* No Data Loss (Manual Commit): The Kafka consumer enable.auto.commit is set to False. Messages are only committed after the agent successfully processes them.

* API Rate Limit Handling: Implemented a robust try-except block specifically catching HTTP 429/Quota errors. Instead of crashing, the system pauses for 60 seconds (throttling) and retries, protecting the API from being banned.

* Edge Case Resiliency: The prompt generator injects "poison pills" (e.g., missing policy numbers, fake IDs). The agent relies on its LLM reasoning to gracefully ask for more info instead of causing a system crash.

3. Code Ownership & Cost Awareness
Controlling LLM token consumption is a primary design consideration for this pipeline:

* Model Selection: Chosen models/gemini-2.5-flash over the Pro version. For procedural classification and database tool-use, the Flash model provides the perfect balance of low latency and extreme cost-effectiveness.

* Token Tracking Ledger: The system intercepts the usage_metadata of every API call, meticulously logging the Prompt Tokens, Candidate Tokens, and a running cumulative total.

## Future Enhancements
Given a production environment, the following improvements would be implemented:

* Dead Letter Queue (DLQ): Route persistently failing messages (e.g., malformed JSON) to a separate Kafka topic for manual review.

* Downstream Integration: Instead of just logging the final answer, publish the Agent's structured output to a processed-events Kafka topic for downstream microservices to consume.
