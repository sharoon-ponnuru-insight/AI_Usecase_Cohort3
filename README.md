# OmniCare

A local multi-agent customer-service assistant built with the Google Agent
Development Kit (`google-adk`) and a Streamlit UI (used instead of `adk web`).

## Architecture

OmniCare is a graph-based ADK `Workflow` (not plain `sub_agents` delegation),
so routing is deterministic rather than prompt-based:

```
START -> concierge_router_agent -> route_to_specialist (FunctionNode)
                                        |-- ORDER_TRACKING   -> order_tracking_agent
                                        |-- RETURNS_LOYALTY  -> returns_and_loyalty_agent
```

- **concierge_router_agent** — greets the customer and classifies each
  message as `ORDER_TRACKING` or `RETURNS_LOYALTY`.
- **order_tracking_agent** — looks up order status/tracking and updates the
  delivery address (only while an order is `PROCESSING`).
- **returns_and_loyalty_agent** — processes refunds and issues apology
  loyalty points.

Every agent runs in `mode="single_turn"` so control returns to the graph
after each turn (graph-workflow nodes do not support `mode="task"` in
ADK Python v2.0.0), and `rerun_on_resume=True` so the workflow restarts at
the router on every new user message instead of getting stuck on the last
specialist that ran.

### Tools (`omnicare/tools.py`)
- `get_order_status(order_id, tool_context)`
- `update_delivery_address(order_id, new_address, tool_context)`
- `issue_order_refund(order_id, refund_amount, reason, tool_context)`
- `add_loyalty_points(customer_id, points, tool_context)`

### Callbacks (`omnicare/callbacks.py`)
- `block_test_terms_callback` (`before_model_callback`) — blocks messages
  containing test/blocked terms (e.g. `COMPETITOR_DISCOUNT`, dummy 16-digit
  card numbers) before calling the LLM; also records the user's message into
  a short rolling `conversation_history`.
- `customer_id_guard_callback` (`before_tool_callback`) — blocks any
  order-related tool call when the order belongs to a different customer
  than the one in session state.
- `refund_limit_callback` (`before_tool_callback`) — blocks refunds over
  $100 unless `manager_approval` is enabled.
- `activity_logger_callback` (`after_tool_callback`) — appends a one-line
  summary of every tool call to `state["activity_log"]`.
- `record_agent_response_callback` (`after_model_callback`) — records each
  agent's final text reply into `conversation_history`, which is re-injected
  into every agent's instruction so context survives across the graph's
  isolated per-node branches.

### Session state
- `customer_id` — active customer, e.g. `CUST-101`.
- `manager_approval` — bool, controlled by a UI checkbox.
- `last_order_id` — last order looked up or acted on.
- `activity_log` — list of tool-call summaries.
- `conversation_history` — short rolling transcript (last 4 turns) used to
  give agents context despite graph-node isolation.

### Local database (`omnicare/db.py`)
SQLite database (`omnicare/omnicare.db`), auto-created and seeded on first
import with 8 sample orders across `CUST-101` / `CUST-102` covering
`PROCESSING`, `SHIPPED`, `DELIVERED`, and `DELAYED` statuses.

## Setup

```bash
cd omnicare
pip install -r requirements.txt
cp .env.example .env   # fill in your GCP project/location
gcloud auth application-default login
```

`config.py` currently points `MODEL_NAME` at `gemini-3.5-flash` as a
placeholder — swap it to a published model (e.g. `gemini-flash-latest`) if
you hit a model-not-found error.

## Running

```bash
# No-LLM smoke test for the tool functions
python omnicare/dev_harness.py

# Streamlit UI
streamlit run omnicare/app.py
```

> Unit tests (`omnicare/tests/`) are planned but not yet implemented.

The Streamlit UI (`omnicare/app.py`) provides:
- A sidebar to pick a sample customer (`CUST-101` / `CUST-102`) and toggle
  "Manager Approval Override".
- A live view of session state and the activity log.
- A chat window showing which sub-agent answered each message.

## Project layout

```
omnicare/
  config.py         # env/model config
  db.py             # SQLite schema, seed data, CRUD helpers
  tools.py          # the 4 ADK tool functions
  callbacks.py       # before/after model & tool callbacks
  agents.py         # graph workflow: router + 2 specialist agents
  app.py            # Streamlit UI
  dev_harness.py    # no-LLM tool smoke test
```
