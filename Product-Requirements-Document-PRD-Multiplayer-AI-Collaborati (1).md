# Product Requirements Document (PRD): Multiplayer AI & Collaborative Agents Workspace

## 1. Executive Summary
This project aims to build a high-performance, real-time collaborative workspace where multiple human users and specialized AI agents (Planner, Executor, Reviewer) co-work on long-running, complex tasks. The system leverages **Moss** for sub-10ms semantic context retrieval and **LangGraph** for sophisticated multi-agent orchestration. By providing a shared, live-synced environment, the platform eliminates context silos between humans and AI, ensuring seamless collaboration and high-quality task execution.

## 2. Problem Statement
Current AI agent frameworks often operate in isolation or via simple request-response cycles. This creates several issues:
*   **Context Fragmentation:** Agents lose track of long-running task history or human interventions.
*   **Latency:** Traditional vector databases are too slow (>100ms) for "live" agent thought processes.
*   **Lack of Coordination:** Multiple agents and humans cannot easily view or influence the same workspace state simultaneously.
*   **Reliability:** Agents can get stuck in loops without a clear escalation path to human supervisors.

## 3. Goals & Objectives
*   **Real-time Collaboration:** Enable multiple humans and agents to interact in a single workspace via WebSockets.
*   **Ultra-low Latency Retrieval:** Achieve <10ms semantic search for session context using Moss.
*   **Robust Orchestration:** Implement a stateful multi-agent workflow with built-in retry and escalation logic.
*   **Security & Guardrails:** Ensure safe tool usage via domain allowlisting and secure session management.
*   **Performance Transparency:** Provide a benchmarking tool to compare Moss performance against traditional vector databases.

## 4. Target Users / Stakeholders
*   **Human Collaborators:** Users providing high-level goals, feedback, and final approvals.
*   **AI Agents:** Specialized entities (Planner, Executor, Reviewer) performing autonomous work.
*   **System Administrators:** Monitoring performance, latencies, and agent reliability.

## 5. Functional Requirements

### 5.1 Multiplayer Workspace
*   The system must support multiple concurrent human users.
*   All participants must see a live-synced view of the workspace state via a WebSocket broadcast layer.
*   Every interaction (human or agent) must be broadcast to all connected clients.

### 5.2 Multi-Agent Orchestration
*   **Planner Agent:** Decomposes high-level goals into actionable sub-tasks.
*   **Executor Agent:** Performs sub-tasks and interacts with external tools.
*   **Reviewer Agent:** Validates the output of the Executor against the original plan.
*   **Retry Logic:** The Orchestrator must track `review_attempts` per task.
*   **Escalation:** If a task fails the Reviewer pass 3 times, the Orchestrator must route the task to the "Escalate to human" node.

### 5.3 Context Management (Moss)
*   The system must use Moss Runtime as an always-warm sidecar for immediate context recall.
*   Every conversation turn, decision, and document update must be indexed in Moss.
*   Moss Cloud must handle background ingestion and distribution of indices.

### 5.4 Benchmarking & Monitoring
*   A **Benchmark Panel** must execute parallel queries against Moss and the Vector DB (e.g., pgvector).
*   The UI must display side-by-side latencies to demonstrate Moss's performance advantage.

## 6. Non-Functional Requirements
*   **Performance:** Moss semantic retrieval must consistently return results in <10ms.
*   **Availability:** Moss Runtime must run as a persistent worker/sidecar to avoid serverless cold-start latencies.
*   **Scalability:** The architecture must support workspace-level isolation (separate Moss project IDs).
*   **Reliability:** Postgres must serve as the absolute source of truth for session and task state.

## 7. System Architecture Overview
The system follows a layered architecture:
1.  **Participants Layer:** Humans (WebSockets) and Agents (Planner, Executor, Reviewer).
2.  **Orchestration Layer:** Central FastAPI/LangGraph hub managing logic and escalation.
3.  **Fast Retrieval Layer:** Moss Runtime (Sidecar) and Moss Cloud for hot context.
4.  **Durable State Layer:** Postgres (State Store) and Redis (Locks/Queues).
5.  **Cold Storage Layer:** Vector DB (Qdrant/pgvector) for long-tail historical data.
6.  **External Layer:** Tools and Web access for the Executor agent.

## 8. Tech Stack
*   **Frontend:** React, Socket.io (WebSockets).
*   **Orchestration:** Python, LangGraph, LangChain, FastAPI.
*   **Agents:** CrewAI (Executor), LlamaIndex (Reviewer).
*   **Fast Retrieval:** Moss SDK, Rust-based Moss Runtime, Moss Cloud API.
*   **Databases:** PostgreSQL (State), Redis (Coordination), Qdrant/pgvector (Cold Storage).
*   **Tools/Infrastructure:** Playwright (Web access), Prometheus (Benchmarking), Slack/Email API (Escalation).

## 9. Data Requirements
*   **Postgres Schema:** Must include tables for `sessions`, `tasks`, `agent_logs`, and `workspace_metadata`.
*   **Moss Index:** Scoped by `session_id` and `agent_id`. Must store conversation turns and decision snapshots.
*   **Data Flow:** Postgres updates must trigger a connector sync to Moss Cloud to keep the "hot" index updated.

## 10. API Specifications
*   **WebSocket Endpoint:** `/ws/workspace/{session_id}` for real-time state broadcasting.
*   **Orchestrator API:** Internal REST endpoints for task submission and status updates.
*   **Moss Query:** Local SDK call to the sidecar: `moss.search(query, limit=5)`.
*   **Escalation Webhook:** Triggered on the 3rd failed review attempt.

## 11. Security Requirements
*   **Authentication:** All human connections must undergo a **session token check** before reaching the Orchestrator.
*   **Authorization:** The Orchestrator must perform an additional check on retrieved Moss/Vector DB results before passing them to agents.
*   **Executor Sandbox:** All external tool/web calls must be filtered through a **domain allowlist**.
*   **Tenant Isolation:** Each workspace/tenant must use a unique Moss `project_id` or isolated namespace.

## 12. Deployment & Infrastructure
*   **Containerization:** Orchestrator and Agents deployed via Docker.
*   **Sidecar Pattern:** Moss Runtime must be deployed as a sidecar to the Orchestrator container to ensure low-latency IPC.
*   **State Management:** Managed Postgres and Redis instances for high availability.

## 13. Success Metrics
*   **Retrieval Latency:** Average Moss query time < 10ms.
*   **Agent Efficiency:** Reduction in task completion time compared to single-agent setups.
*   **Escalation Accuracy:** 100% of tasks failing 3 reviews are correctly routed to humans.
*   **System Transparency:** Real-time visibility of the latency delta between Moss and Cold Storage.

## 14. Timeline & Milestones
*   **Phase 1 (Week 1):** Core Orchestrator setup with LangGraph and Postgres state store.
*   **Phase 2 (Week 1):** Moss Runtime sidecar integration and semantic context indexing.
*   **Phase 3 (Week 2):** WebSocket implementation for multiplayer human-in-the-loop UI.
*   **Phase 4 (Week 2):** Implementation of Reviewer logic, Escalation node, and Benchmark panel.

## 15. Open Questions & Risks
*   **Risk:** High volume of WebSocket messages in very active workspaces could lead to UI lag. *Mitigation: Implement message batching/throttling.*
*   **Risk:** Moss index sync latency from Postgres. *Mitigation: Use async event-driven connectors for near real-time updates.*
*   **Question:** Should the "Escalate to human" node support real-time chat or just asynchronous notifications (Slack/Email)? *Initial version will support notifications with a link to the workspace.*