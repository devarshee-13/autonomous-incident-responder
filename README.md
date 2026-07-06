# Autonomous Incident Responder

An AI agent that responds to production outages the moment an alert fires. It
identifies the likely bad commit by **reading the actual code diffs**, finds
the relevant runbook, estimates user impact, proposes an approval-gated
remediation — and goes one step further: it writes a candidate **code fix plus
a test, runs the test to prove the fix works**, and only then offers it for a
human to approve.

Think of it as a first-responder on-call engineer that does the initial
investigation in seconds, then stops and asks a human before touching
anything.

---

## What it does

```
1. Bug shipped — traffic triggers it            ┐
2. Error rate breaches SLO → alert fires        ┘  (the "production" it watches)

3. Alert hits the agent's webhook
4. Gather recent deploys + error logs / traces
5. ★ Read the diffs → identify the culprit commit   (the core reasoning)
6. Suggest a fix + a test, and run it to VERIFY the fix works
7. Match a runbook + estimate user impact
8. Propose a rollback
9. Human approves — the rollback AND/OR opening a PR with the verified fix
10. Auto-generate the postmortem
```

Step 5 is where the intelligence lives — it narrows recent commits with a
cheap heuristic, then reasons over the real diffs to explain *why* a specific
change caused *this specific* error. It also correctly concludes **"none of
these — this looks like an external outage"** when that's true, rather than
confidently blaming an innocent commit.

Every action against infrastructure is **approval-gated**: the agent proposes,
a human approves. It never touches production on its own.

---

## Highlights

- **Culprit-commit ranking that reads code.** A heuristic pre-filter
  (deploy-time proximity + stack-trace/file overlap) narrows candidates, then
  the model reasons over the actual diffs. Measured against a **4-scenario eval
  set — 4/4**, including adversarial cases (the correct culprit is the *most
  recent* deploy; two commits touch the *same file* but only one is causal;
  and an *external outage* with no code culprit at all).
- **A fix it can prove.** For code-caused incidents the agent generates a
  corrected patch **and** a pytest test, then runs the test against both the
  buggy and fixed code — it must *fail* on the bug and *pass* on the fix. Only
  a verified fix is ever offered for approval.
- **Human-in-the-loop, done properly.** Built on LangGraph's interrupt/resume,
  the graph pauses and waits for a human. The rollback and the fix are
  *independently* approvable — mitigate now, review the forward-fix separately.
- **A live demo target, not "trust me."** A small instrumented service +
  synthetic traffic + a bug-injection switch + an SLO watcher means the agent
  responds to a *genuinely fired* alert from real failing code, not a canned
  payload.
- **Grounded postmortems.** The generated report cites real numbers from the
  investigation record (including actual test output), rather than a plausible-
  sounding summary.

---

## Architecture

Two halves, deliberately decoupled:

### A. The demo target (`demo_target/`) — the "production" it watches
A small checkout/pricing service with a real, toggle-able divide-by-zero bug,
plus the machinery to make it fail believably:

| File | Role |
|---|---|
| `checkout.py` | Real pricing logic with a toggle-able bug |
| `state.py` | In-memory metrics (rolling error rate), error-log buffer, deploy log |
| `app.py` | FastAPI: `/checkout`, `/metrics`, and introspection endpoints (`/_deploys`, `/_commits/{sha}`, `/_errors`) the agent queries |
| `inject_bug.py` | "Deploys" the bug — flips the toggle *and* records a deploy with a real diff |
| `traffic.py` | Generates checkout traffic (some carts trigger the bug) |
| `slo_watcher.py` | Polls `/metrics`; fires an alert to the agent on SLO breach — a lightweight stand-in for Prometheus + Alertmanager |

### B. The agent (`agent/`) — the responder
A [LangGraph](https://langchain-ai.github.io/langgraph/) `StateGraph`. The
graph accumulates a typed investigation record as it runs:

```
START
  → gather_context      deploys + error logs; heuristic pre-filter (ranking.py)
  → rank_commits        model reads diffs → ranked culprit verdict
  → suggest_fix         (only if a culprit was found) patch + test, then verify
  → search_runbook      keyword retrieval over runbooks/
  → estimate_impact     error-rate delta × traffic → affected requests
  → propose_remediation model proposes a rollback from a fixed action registry
  → [INTERRUPT]         pause for human approval (rollback and/or apply fix)
  → execute_action      run the approved action(s) — stubs for now
  → END → postmortem
```

Key modules: `graph.py` (nodes + wiring), `ranking.py` (heuristic pre-filter),
`fix_verifier.py` (the sandboxed test runner), `actions/registry.py` (the fixed,
typed set of allowed actions — the model picks from it, never invents commands),
`postmortem.py` (report generation).

The agent's tools (`agent/core/tools/`) read from **static fixtures** by default
and from the **live demo target over HTTP** when `DEMO_TARGET_URL` is set — same
tool signatures either way, so the eval set and the live demo exercise the same
code.

---

## Setup

Requires Python 3.11+ and an Anthropic API key.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY=sk-ant-...
```

The default model is `claude-opus-4-8`.

---

## Running it

There are two ways to exercise the system. **The fixture flow needs nothing but
an API key** — no servers, no database, no Slack.

### 1. Fixture flow (fast, self-contained)

Run the culprit-ranking eval set (measures ranking accuracy — the hero metric):

```bash
python -m eval.run_scenario
# → [PASS] scenario_01 ... 4/4 scenarios passed
```

Run a full incident end-to-end (investigation → verified fix → approval →
postmortem) against one scenario:

```bash
# interactive — you'll be prompted to approve the rollback and the fix
SCENARIO_DIR=eval/scenarios/scenario_01 python -m eval.run_incident

# or non-interactive
SCENARIO_DIR=eval/scenarios/scenario_01 python -m eval.run_incident --auto-approve
SCENARIO_DIR=eval/scenarios/scenario_04 python -m eval.run_incident   # external outage: no culprit, no fix
```

Generated postmortems are written to `postmortems/<incident_id>.md`.

### 2. Live demo (the whole loop, against a real fired alert)

Five terminals (each with the venv activated). This uses an in-memory
checkpointer, so it needs **no Postgres and no Slack**:

```bash
# 1. the demo target
python -m uvicorn demo_target.app:app --port 8100

# 2. the agent webhook (Slack-free), pointed at the live target
DEMO_TARGET_URL=http://localhost:8100 python -m uvicorn agent.api.main_cli:app --port 8000

# 3. traffic
python -m demo_target.traffic

# 4. the SLO watcher
python -m demo_target.slo_watcher

# 5. wait ~30s for traffic to build up, then inject the bug
python -m demo_target.inject_bug
```

Watch terminal 4: the error rate climbs, crosses the SLO threshold, and fires an
alert. Terminal 2 then prints the full incident brief — culprit commit,
verified fix, impact, and proposed rollback — investigating the *live* service.

---

## The eval set

`eval/scenarios/` holds four incidents with known ground truth. Each is a
`(alert, deploys, error_samples, metrics, expected)` bundle. They're chosen to
test *reasoning*, not just "pick the most recent deploy":

| Scenario | Tests |
|---|---|
| `scenario_01` | Baseline: a divide-by-zero pricing bug |
| `scenario_02` | The correct culprit **is** the most recent deploy (don't over-correct) |
| `scenario_03` | Two commits touch the **same file** — only one is causal (must read diffs) |
| `scenario_04` | **External SMTP outage** — no code culprit; must express low confidence, not blame an innocent commit |

Current result: **4/4**.

---

## Scope & boundaries (what's real vs. demonstrative)

This is a portfolio project. Some boundaries are deliberate:

- **Action executors are stubs.** Approving a rollback prints
  `[stub] Would roll back ...` rather than actually mutating infra — on
  purpose. The interesting, real parts are the *investigation*, the *fix
  verification*, and the *approval workflow*; a project that actually
  rewrites production deploys is not something you want running loose.
- **The fix verifier runs LLM-generated code.** It's scoped to a throwaway
  temp dir + a subprocess with a timeout, and only ever runs a fix it's about
  to prove — but it is **not** a hardened sandbox. Fine for a local demo;
  never point it at untrusted input in production.
- **Deploy diffs are synthetic.** The culprit diffs are hand-crafted strings
  (they reference file paths like `payments/pricing.py`), decoupled from the
  demo target's real source. The agent reasons over them as it would over real
  git diffs; wiring it to a real repo's `git log`/`git show` is a drop-in swap
  behind the existing tool interface.
- **Slack + Postgres are built but optional.** Full Slack Block Kit approval
  (`agent/core/slack/`, `agent/slack_listener.py`) and a Postgres checkpointer
  (`agent/core/checkpointer.py`, `docker-compose.yml`) exist for the
  multi-process production flow (`agent/api/main.py`); the Slack-free in-memory
  path above is what the demo uses.

See [`docs/DESIGN.md`](docs/DESIGN.md) for the full technical design.

---

## Tech stack

Python · [LangGraph](https://langchain-ai.github.io/langgraph/) ·
[`langchain-anthropic`](https://pypi.org/project/langchain-anthropic/)
(Claude Opus 4.8) · FastAPI · Pydantic · pytest · Postgres (optional) ·
Slack Bolt (optional).
