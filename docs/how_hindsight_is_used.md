# How Hindsight Is Used in Meredian

Meredian uses **Hindsight** (`retain`, `recall`, `reflect`, and automatic **Observations** consolidation) as the institutional memory layer connecting engineering shifts in Seattle (Shift A), London (Shift C), and Bengaluru (Shift B).

## 1. Isolated Per-Incident & Cross-Incident Banks
- **Incident Bank (`payments-memleak`, `auth-token-storm`, `redis-failover-stall`)**: Each active incident gets its own isolated bank so facts and observations from unrelated outages never bleed into real-time interception.
- **Cross-Incident Pattern Bank (`meredian-team-patterns`)**: Proven fixes and multi-day learnings (Day 5+) are retained in a shared team-patterns bank so recurring architectural anti-patterns (e.g., unbounded middleware caches or stale Redis Sentinel sockets) are surfaced across incidents.

## 2. Bank Mission, Directives & Disposition
Every Meredian bank is configured via `configure_bank`:
- **Mission**: *"I am the institutional memory of a global engineering team. I prioritize what was tried, what failed and why, and what is still unknown."*
- **Directives (Hard Rules)**:
  1. Never claim something was tested without evidence.
  2. Always cite commit hash, terminal log reference, or Band chat message ID.
  3. Never tell an engineer something is impossible; only state that it was tried under specific conditions.
- **Disposition**: `moderately_skeptical` — distinguishes *"failed under 1,500 RPS staging load"* from *"can never work under any conditions"*, powering the `related` verdict and `retry_of` override loop.

## 3. Core Hindsight Operations
| Operation | Where Used in Meredian | Token Budget / Behavior |
|---|---|---|
| `retain` | `memory/client.py :: retain_attempt` | Stores plain-English attempt narratives built from structured fields, tracks asynchronous `operation_id` status (`updating` -> `ready`), extracts entities/facts, and triggers observation consolidation. |
| `recall` | `memory/client.py :: recall_for_action` | Uses a **small token budget (`400` tokens)** for low-latency (`<50ms` local) real-time interception in VS Code and the terminal hook, and a **larger budget (`1600` tokens)** for Memory Explorer searches. |
| `reflect` | `memory/client.py :: reflect_for_briefing` | Synthesizes the shift-start **State of the Problem** briefing (ruled-out dead ends with commit/log citations, cross-site condition conflicts, leading suspect, and recommended first step). |
| **Observations** | `hindsight_client :: _ConsolidateObservations` | Consolidates multiple attempts on the same subsystem into higher-order beliefs (e.g., *"Redis timeout and connection pool tuning have been tested 2 times across shifts and do not stop the memory growth"*) with a full Day 1 → Day 2 → Day 5 evolution history. |

