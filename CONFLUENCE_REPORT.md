# Calendly-Bot + MCP AI Agent Exploration

## 1. Project Overview

This proof-of-concept connects Calendly’s existing API (via the MCP-wrapper) to an AI agent.

- **Languages & frameworks:**
  - **Backend:** Python (FastAPI) & Node.js (MCP-server)
  - **AI:** OpenAI via MCP
- **Goal:** Let users “chat” with Calendly to schedule/modify events.

## 2. Objectives

1. Explore Calendly’s current API surface.
2. Stand up an AI-driven agent that can call Calendly endpoints via MCP.
3. Evaluate end-to-end event creation, rescheduling, and cancellation.
4. Identify gaps and limitations in the current API.

## 3. Architecture & Implementation

- The Python service wraps common scheduling workflows (in `CalendlyWorkflow.py`).
- The Node-based MCP server (`src/index.ts`) exposes Calendly calls as tools.
- The AI agent (`MCP_Agent.py`) uses OpenAI to interpret user intents and invoke these tools.
- Local dev: virtualenv “med,” FastAPI + Uvicorn, plus “calendly-mcp-server” npm package.

## 4. Key Findings

- **Authentication:** OAuth via Coinbase-style flow works reliably.
- **Read operations** (list events, availability) functioned end-to-end.
- **Event creation** calls succeed server-side, but don’t finalize until user clicks “Confirm” in Calendly’s UI. 
  → Agents can draft an event, but the end user still must manually confirm.
- **Reschedule & cancel** possess similar UX caveats.

## 5. Limitations

- No fully “headless” event creation under today’s API—requires UI confirmation.
- Lack of deep webhook support limits real-time status updates.
- Rate limiting/documentation gaps around recurring meetings.

## 6. Upcoming Calendly API (v2)

- Calendly has announced a **v2 API** expected Q4 2025.
- Promises include:
  - Full headless flow (create + confirm)
  - Webhook enhancements for status callbacks
  - Better support for recurring events & advanced adjustments
- We’ll monitor their public roadmap and be ready to integrate immediately.

## 7. Conclusions & Next Steps

1. Our AI agent MVP is live: users can “chat” to see availability and draft events.
2. Critical UX gap: manual confirmation step in Calendly GUI.
3. Short-term: document current “draft → confirm” flow clearly in user guidance.
4. Mid-term: swap to v2 API when available—revisit “fully automated” use case.
5. Long-term: add webhook-driven status updates and richer AI-driven scheduling intelligence.

---

*Report prepared by Satwik on October 17, 2025*
