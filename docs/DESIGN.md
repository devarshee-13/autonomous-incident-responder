# AI On-Call — Technical Spec (v1)

Autonomous incident-response agent: reacts to a real alert, ranks likely culprit
commits, retrieves the right runbook, estimates user impact, posts a Slack
brief, proposes a remediation action gated on human approval, and generates a
postmortem once the incident resolves.

Two halves:
- **Demo target system** — a small instrumented app + alerting stack that
  produces *real* alerts (via injected bugs), so the agent has something
  genuine to respond to.
- **Incident agent** — the thing we're actually building/learning from. Built
  on **LangGraph** (`langchain-anthropic` as the model wrapper) rather than a
  hand-rolled loop, with Postgres for all state and Slack Bolt for comms.

Hero-depth areas: **culprit-commit ranking** (heuristics + eval set) and the
**investigation graph's design** (state schema, node/edge structure, and the
human-in-the-loop approval interrupt) — depth here now means designing a good
graph and tool set within LangGraph, not hand-writing the tool-call loop.
Everything else (RAG, impact estimate, Slack, postmortem) is built solidly
but kept simple.

Actions are **approval-gated**: the agent can *propose* a remediation from a
fixed, typed action registry; nothing executes until a human clicks Approve
in Slack.

---

## 1. Repo layout

```
ai_on_call/
├── docker-compose.yml
├── docs/
│   ├── DESIGN.md                  # this file
│   └── postmortems/                # generated postmortem docs land here
├── runbooks/                       # markdown source-of-truth, embedded into pgvector
│   ├── high-error-rate.md
│   ├── db-connection-pool-exhaustion.md
│   └── ...
├── eval/                           # culprit-commit ranking eval harness
│   ├── scenarios/                  # one dir per injected-bug scenario + ground truth
│   ├── run_eval.py
│   └── results/
├── demo_target/                    # Half A — produces real alerts
│   ├── services/
│   │   ├── api_gateway/
│   │   ├── orders_service/
│   │   └── payments_service/
│   ├── shared/                     # common metrics/logging setup, fake user pool
│   ├── deploy_log/                 # records "deploys" (commit + timestamp) per service
│   ├── bug_injection/               # scenario scripts that merge+redeploy a bad commit
│   ├── load_gen/                    # synthetic traffic generator (tags requests with user_id)
│   └── observability/
│       ├── prometheus/
│       ├── alertmanager/
│       └── grafana/
├── agent/                          # Half B — the incident response agent
│   ├── api/
│   │   ├── main.py                 # FastAPI app
│   │   ├── routes_alerts.py        # POST /webhooks/alertmanager
│   │   └── routes_slack.py         # POST /slack/interactions (button clicks)
│   ├── core/
│   │   ├── incident.py             # incident state machine (mirrors the graph's own status)
│   │   ├── graph.py                # LangGraph StateGraph: nodes, edges, compile()
│   │   ├── state.py                # TypedDict State schema passed between nodes
│   │   ├── ranking.py              # heuristic pre-filter for culprit commits
│   │   ├── tools/                  # LangChain @tool-decorated functions, bound via .bind_tools()
│   │   │   ├── deploys.py
│   │   │   ├── commits.py
│   │   │   ├── logs.py
│   │   │   ├── metrics.py
│   │   │   └── runbooks.py
│   │   ├── actions/
│   │   │   ├── registry.py         # typed action definitions + validation
│   │   │   └── executors.py        # actually performs rollback/restart/scale
│   │   ├── slack/
│   │   │   ├── blocks.py           # Block Kit builders
│   │   │   └── client.py
│   │   └── postmortem.py
│   ├── db/
│   │   ├── models.py                # SQLAlchemy models
│   │   └── migrations/              # alembic
│   └── tests/
└── pyproject.toml
```

Single Postgres instance (with `pgvector` extension) backs the agent. The demo
target's "deploy log" is its own lightweight service/table that the agent
polls via a tool call — kept decoupled so the agent's tools look the same
whether the target is this demo app or a real one later.

LangGraph needs a **checkpointer** to persist graph state across the
approval-interrupt (the graph pauses when `propose_action` is reached and must
resume later from whatever process handles the Slack button click — possibly
minutes later, in a different request). Use `langgraph.checkpoint.postgres` so
checkpoints live in the same Postgres instance rather than standing up a
separate store. The `investigation_steps` table (below) is a *separate*,
app-level audit trail — populated by hooking into each node's execution — kept
independent of LangGraph's own checkpoint format so the postmortem generator
and Slack updates don't depend on LangGraph internals.

---

## 2. Database schema (agent's Postgres)

```sql
create extension if not exists vector;
create extension if not exists pgcrypto; -- gen_random_uuid()

create type incident_status as enum (
  'investigating', 'awaiting_approval', 'remediating', 'resolved', 'closed'
);

create type action_status as enum (
  'pending_approval', 'approved', 'rejected', 'executed', 'failed'
);

create type action_type as enum (
  'rollback_to_previous_deploy', 'restart_service', 'scale_service'
);

create table incidents (
  id uuid primary key default gen_random_uuid(),
  alert_fingerprint text not null,      -- dedupe key from Alertmanager
  service text not null,
  status incident_status not null default 'investigating',
  alert_payload jsonb not null,
  summary text,                         -- filled once investigation completes
  started_at timestamptz not null default now(),
  resolved_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (alert_fingerprint, started_at)
);

-- full trace of the LangGraph run: each node's input/output plus any tool
-- calls made within it. Doubles as the raw material for the postmortem generator.
create table investigation_steps (
  id uuid primary key default gen_random_uuid(),
  incident_id uuid not null references incidents(id) on delete cascade,
  step_index int not null,
  role text not null check (role in ('assistant', 'tool_call', 'tool_result')),
  tool_name text,
  content jsonb not null,
  created_at timestamptz not null default now()
);

create table deploys (
  id uuid primary key default gen_random_uuid(),
  service text not null,
  commit_sha text not null,
  author text,
  message text,
  deployed_at timestamptz not null,
  files_changed text[],
  diff_summary text
);
create index on deploys (service, deployed_at desc);

create table culprit_candidates (
  id uuid primary key default gen_random_uuid(),
  incident_id uuid not null references incidents(id) on delete cascade,
  commit_sha text not null,
  service text not null,
  heuristic_score float not null,       -- from the pre-filter (deploy proximity + file overlap)
  llm_rank int,                          -- final rank assigned by the agent, null until decided
  llm_reasoning text,
  is_ground_truth boolean                -- only populated when incident came from eval/ scenarios
);

create table runbooks (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  content text not null,
  embedding vector(1536),
  service_tags text[],
  updated_at timestamptz not null default now()
);
create index on runbooks using ivfflat (embedding vector_cosine_ops);

create table runbook_matches (
  id uuid primary key default gen_random_uuid(),
  incident_id uuid not null references incidents(id) on delete cascade,
  runbook_id uuid not null references runbooks(id),
  similarity_score float not null,
  rank int not null
);

create table impact_estimates (
  id uuid primary key default gen_random_uuid(),
  incident_id uuid not null references incidents(id) on delete cascade,
  error_rate_baseline float not null,
  error_rate_during float not null,
  requests_affected int not null,
  users_affected int not null,
  window_start timestamptz not null,
  window_end timestamptz not null
);

create table proposed_actions (
  id uuid primary key default gen_random_uuid(),
  incident_id uuid not null references incidents(id) on delete cascade,
  action_type action_type not null,
  action_args jsonb not null,            -- validated against the action's pydantic schema
  status action_status not null default 'pending_approval',
  rationale text,
  decided_by text,                       -- slack user id
  decided_at timestamptz,
  executed_at timestamptz,
  result jsonb
);

create table audit_log (
  id uuid primary key default gen_random_uuid(),
  incident_id uuid references incidents(id) on delete set null,
  actor text not null,                   -- 'agent' | slack user id | 'system'
  action text not null,                  -- e.g. "posted slack brief", "approved rollback"
  metadata jsonb,
  created_at timestamptz not null default now()
);

create table postmortems (
  id uuid primary key default gen_random_uuid(),
  incident_id uuid not null unique references incidents(id) on delete cascade,
  content_markdown text not null,
  published_path text,                   -- e.g. docs/postmortems/<id>.md
  generated_at timestamptz not null default now()
);

-- lets us chat.update the same Slack message as the investigation progresses
create table slack_messages (
  id uuid primary key default gen_random_uuid(),
  incident_id uuid not null references incidents(id) on delete cascade,
  channel_id text not null,
  message_ts text not null,
  purpose text not null check (purpose in ('brief', 'postmortem_notice'))
);
```

---

## 3. Tools & graph design (LangChain / LangGraph)

Tools are `@tool`-decorated Python functions (LangChain's tool-calling
convention) bound to the model via `ChatAnthropic(...).bind_tools([...])` —
LangChain derives the JSON schema from the function signature, type hints,
and docstring, instead of hand-written schemas.

```python
from typing import Literal
from langchain_core.tools import tool

@tool
def get_recent_deploys(service: str, before: str, lookback_minutes: int = 120) -> list[dict]:
    """List deploys (commit + timestamp) for a service within a lookback
    window before a given time. Use this to find candidate commits that
    could have caused an alert."""
    ...

@tool
def get_commit_diff(service: str, commit_sha: str) -> dict:
    """Get the diff and changed files for a specific commit, so its
    contents can be compared against error stack traces."""
    ...

@tool
def get_error_samples(service: str, start: str, end: str, limit: int = 20) -> list[dict]:
    """Fetch recent error log samples/stack traces for a service in a time
    window, grouped by fingerprint with counts."""
    ...

@tool
def query_metrics(
    service: str,
    metric: Literal["error_rate", "request_rate", "p99_latency"],
    start: str, end: str, step_seconds: int = 30,
) -> dict:
    """Query a Prometheus metric for a service over a time window, including
    a baseline comparison from before the window."""
    ...

@tool
def search_runbooks(query: str, top_k: int = 3) -> list[dict]:
    """Semantic search over the runbook corpus. Use the alert description
    and/or error signature as the query."""
    ...

@tool
def propose_action(
    action_type: Literal["rollback_to_previous_deploy", "restart_service", "scale_service"],
    target_service: str, args: dict, rationale: str,
) -> str:
    """Propose a remediation action. Does NOT execute anything — creates a
    pending approval request that a human must approve in Slack. Returns the
    proposed_action_id."""
    ...
```

There's no `finalize_investigation` tool — with LangGraph, the structured
result is the graph's typed `State`, populated incrementally by each node,
rather than assembled from one forced final tool call.

### State schema

```python
from typing import Annotated, TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class State(TypedDict):
    incident_id: str
    alert: dict
    deploy_candidates: list[dict]       # from ranking.py's heuristic pre-filter
    culprit_commit: dict | None         # {commit_sha, confidence, reasoning}
    ranked_candidates: list[dict]
    runbook_match: dict | None
    impact: dict | None
    proposed_action_id: str | None
    messages: Annotated[list[BaseMessage], add_messages]  # tool-calling scratchpad
```

### Graph structure

```
START
  → gather_context      (get_recent_deploys, get_error_samples; ranking.py pre-filter narrows to top ~5)
  → rank_commits         (model call w/ get_commit_diff tool bound; writes culprit_commit + ranked_candidates)
  → search_runbook       (search_runbooks tool; writes runbook_match)
  → estimate_impact      (query_metrics tool; writes impact)
  → propose_remediation  (model call w/ propose_action tool; writes proposed_action_id)
  → [INTERRUPT: awaiting_approval]  -- graph pauses here, checkpointed to Postgres
  → execute_action       (resumes on Slack Approve/Reject; runs the action registry or skips on reject)
  → END
```

The edges from `gather_context` through `estimate_impact` are linear — each
node is a single focused model-or-tool call rather than a general ReAct loop,
which keeps the graph legible and each step's cost/behavior easy to reason
about in isolation. `propose_remediation` → interrupt is the one conditional
point: skip straight to `END` if the model decides no action is warranted
(low confidence, or the alert already self-resolved).

### Resuming from the approval interrupt

The trickiest part of the LangGraph port: the graph pauses mid-run, and the
process that resumes it (the `/slack/interactions` webhook handler) is a
*different* HTTP request, possibly minutes later. Resuming needs:
- The LangGraph `thread_id` — use `incident_id` directly, since it's one
  graph run per incident — to locate the checkpoint via the Postgres
  checkpointer (`langgraph.checkpoint.postgres`).
- The Slack button's `value` still carries `proposed_action_id`; the
  interaction handler looks that up in `proposed_actions` to find the
  `incident_id`/`thread_id`, then calls
  `graph.invoke(None, config={"configurable": {"thread_id": incident_id}})`
  to resume from the checkpoint.

---

## 4. Slack message design

Two message types, both built with Block Kit and posted via `chat.postMessage`,
then mutated in place with `chat.update` as the incident progresses (tracked
via the `slack_messages` table so we know which `message_ts` to update).

### 4.1 Incident brief

```json
{
  "blocks": [
    { "type": "header", "text": { "type": "plain_text", "text": "🚨 payments-service — elevated error rate" } },
    { "type": "section", "fields": [
      { "type": "mrkdwn", "text": "*Status:*\nAwaiting Approval" },
      { "type": "mrkdwn", "text": "*Started:*\n3 min ago" }
    ]},
    { "type": "divider" },
    { "type": "section", "text": {
      "type": "mrkdwn",
      "text": "*Probable cause* (82% confidence)\n<https://github.com/org/repo/commit/abc123|abc123> by @jdoe — \"add retry logic to payment gateway client\"\n```+ except Exception:\n+     return retry(payload, max_attempts=0)```\n_Reasoning: max_attempts=0 makes every call fail immediately; error onset matches deploy time within 40s._"
    }},
    { "type": "section", "text": {
      "type": "mrkdwn",
      "text": "*Impact*\n47% of requests failing (baseline 0.2%) · ~1,240 users affected · 6 min ongoing"
    }},
    { "type": "section", "text": {
      "type": "mrkdwn",
      "text": "*Runbook:* <https://internal/runbooks/high-error-rate|High Error Rate — Payments>"
    }},
    { "type": "actions", "elements": [
      { "type": "button", "text": { "type": "plain_text", "text": "✅ Approve rollback" }, "style": "primary",
        "action_id": "approve_action", "value": "<proposed_action_id>" },
      { "type": "button", "text": { "type": "plain_text", "text": "❌ Reject" }, "style": "danger",
        "action_id": "reject_action", "value": "<proposed_action_id>" }
    ]},
    { "type": "context", "elements": [
      { "type": "mrkdwn", "text": "Incident `<incident_id>` · <https://internal/incidents/<id>|full investigation trace>" }
    ]}
  ]
}
```

- Action buttons only appear once status reaches `awaiting_approval` (i.e. the
  brief is first posted without them, then `chat.update`d once the graph
  reaches the `propose_remediation` → interrupt point).
- Button `value` carries the `proposed_action_id`; the Slack interaction
  payload also carries the clicking user's id, which becomes `decided_by`.
- `POST /slack/interactions` verifies the Slack signing secret, looks up the
  action to find the paused graph's `thread_id`, flips the action's status,
  resumes the graph (which runs `execute_action` on approve or skips to `END`
  on reject), and calls `chat.update` to replace the Actions block with a
  plain status line ("✅ Approved by @jdoe — rollback executed").

### 4.2 Postmortem notice

Posted as a new message in the same thread once the postmortem is generated:

```json
{
  "blocks": [
    { "type": "section", "text": { "type": "mrkdwn",
      "text": "📄 *Postmortem ready* for this incident.\n<https://github.com/org/repo/blob/main/docs/postmortems/<id>.md|View postmortem>" } },
    { "type": "section", "text": { "type": "mrkdwn",
      "text": "_TL;DR: rollback of abc123 resolved elevated error rate within 4 min of approval; 1,240 users affected over 9 min total._" } }
  ]
}
```

---

## 5. Open items for the next pass

- Exact heuristic scoring formula for `ranking.py` (weights for deploy-time
  proximity vs. file overlap) — worth tuning once the eval set exists.
- Whether `deploys`/`investigation_steps` truncate large diffs/log blobs
  before storing (probably yes, with a pointer to full content on disk).
- Auth between `demo_target` and `agent` (shared network + simple API key is
  enough for a demo; not worth more).
- Whether to run each linear node (`gather_context` → `estimate_impact`) as
  its own model call, or collapse some into plain Python functions that only
  call a tool directly without going back through the model — worth deciding
  once we see real latency/cost per incident.
- Exact LangGraph version/API surface to pin (checkpointer API has changed
  across releases) — verify against current docs when we start `graph.py`
  rather than trusting this spec's syntax verbatim.
