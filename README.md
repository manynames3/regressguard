# RegressGuard

**Catch quality regressions when prompts and models change.**

An LLM feature can keep returning successful responses while its answers get worse. RegressGuard makes that quality change visible in code review. It runs repeated evaluations, compares the results with an accepted baseline, and fails CI when a critical case breaks or the overall score drops beyond policy.

Independent portfolio project. All demo inputs and outputs are fictional/sample data.

The supplied CI gate uses scripted mock models. The CLI and API also support explicitly configured OpenAI-compatible endpoints. The hosted evidence below demonstrates the regression workflow with controlled fictional behavior.

## See the gate catch a regression

In an observed GitHub Actions run, a model change caused one critical support-ticket case to pass only **2 of 3 attempts**. Every other case still passed. The aggregate score dropped just **1.67 points**, below the five-point aggregate threshold. The critical-case rule caught it.

| Observed result | Evidence |
| --- | --- |
| Critical case fell from 3/3 to 2/3. The quality gate exited 1. Engine tests and PostgreSQL persistence passed. | [Failing workflow](https://github.com/manynames3/regressguard/actions/runs/42555751538) |
| Restoring the healthy model produced a passing baseline comparison. A prompt-version change kept the suite selected for evaluation. | [Passing workflow](https://github.com/manynames3/regressguard/actions/runs/42555872612) |
| The final workflow passed the regression gate, engine tests, calibration, PostgreSQL persistence, and loopback HTTP integration. | [Final verification](https://github.com/manynames3/regressguard/actions/runs/42556189688) |

Both outcomes are preserved in the same demonstration PR. Downloaded artifact evidence records the run IDs, commit SHAs, baseline, case deltas, and source-artifact hashes. The repository is currently private, so GitHub evidence links require access. [Proof PR](https://github.com/manynames3/regressguard/pull/1) · [Evidence and reproduction notes](docs/CI_PROOF.md)

## Run it in minutes

Start the API and dashboard with Docker Compose.

```sh
docker compose up --build
```

Open http://localhost:8000, select a feature, and click **Run evaluation**. The fictional classifier and summarizer arrive with generated baselines. SQLite history, promotions, and local alerts persist in a named volume. The demo needs no API key or model download.

For local development, install uv and use Python 3.12. Run these commands from the repository root. [uv installation](https://docs.astral.sh/uv/getting-started/installation/)

```sh
uv sync --locked
uv run regressguard run --suite suites/ticket-classifier.yml --runs 3
# Replace <run-id> with the UUID printed by the preceding command.
uv run regressguard baseline --run <run-id>
uv run regressguard run --suite suites/ticket-classifier.yml --baseline latest
uv run python demo/break_it.py
```

The final command deliberately removes the JSON-format instruction in memory, changes the prompt version, and exits **1**. Its report shows the failing cases, before/after counts, and prompt diff. The alert is written to `data/alerts.jsonl`. Rerun the original suite with `--baseline latest` to observe recovery.

To use the dashboard with the same local database, run `uv run uvicorn api.app:app --host 127.0.0.1 --port 8000`. For the Compose database, execute the CLI inside the service.

```sh
docker compose exec api .venv/bin/regressguard run --suite suites/ticket-classifier.yml --baseline latest
docker compose exec api .venv/bin/python demo/break_it.py
```

## Engineering decisions that make the result reviewable

- **Accepted evidence comes from the PR's base commit.** The gate evaluates the candidate target against the accepted cases and policy. Editing expected answers, relaxing a threshold, or replacing a baseline in the same PR cannot remove that comparison.
- **Critical behavior has its own gate.** One failed critical sample blocks the candidate, even when improvements elsewhere raise its average.
- **Every comparison has a defined measuring instrument.** Inputs, checks, severity, evaluator version, rubric, semantic backend, and repetition count form a fingerprinted contract. Incompatible contracts require an explicit new reference.
- **Incomplete execution blocks CI.** A provider outage, missing baseline, or entirely skipped case returns exit 2. Reports distinguish those conditions from measured quality failures.
- **Results remain inspectable.** SQL retains run evidence, the dashboard exposes individual attempts, and Git stores portable baseline snapshots. Prompt hashes, requested and returned model IDs, parameters, usage, and Git metadata make changes traceable.

## Exercise the harder failure modes

```sh
uv run python -m demo.scenarios
REGRESSGUARD_SEMANTIC_BACKEND=tfidf uv run python -m demo.calibrate
```

The scenario runner uses the normal generation, evaluation, storage, comparison, and alert paths.

| Fictional scenario | Observed behavior |
| --- | --- |
| An intermittent outage-classification error | A critical case changes from 3/3 to 2/3. The aggregate loses 1⅔ points and the gate fails. |
| Improvements conceal a critical regression | The aggregate rises from 85 to 98⅓. A critical sample fails, so the gate still fails. |

The scenario command restores a healthy baseline afterward. The mock provider receives the prompt, input, generation parameters, and attempt index. Evaluation answers and severity stay outside that boundary.

Calibration fits its representation and selects a threshold on 10 development pairs before evaluating 24 separate held-out pairs. At the selected threshold, the negation/numeric guards caught **9 of 12 unacceptable outputs**, compared with **5 of 12** for cosine alone. Both modes falsely rejected **4 of 12 acceptable outputs**. Every label, rationale, and observed error is included in the evidence. These are measurements of authored synthetic fixtures. [Evaluation methodology](docs/EVALUATION.md) · [Generated calibration report](docs/calibration/report.md)

## Architecture and release policy

Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy · SQLite/PostgreSQL · Jinja2 · GitHub Actions

```mermaid
flowchart LR
    S[Versioned prompt and YAML suite] --> R[Repeated generation]
    P[Mock or configured model endpoint] --> R
    R --> E[Checks and per-attempt measurements]
    E --> D[(SQL run evidence)]
    B[Accepted baseline] --> C[Comparison policy]
    D --> C
    C --> U[CLI report and dashboard]
    C --> G[GitHub Actions verdict]
    C --> A[Local alert and optional webhook]
```

The CLI, API, and CI gate share one run service. A sample passes when at least one check executes and all executed checks pass. A case's pass rate is its passed samples divided by its requested repetitions. The aggregate is the unweighted mean of case pass rates on a 0–100 scale.

| Verdict | Condition | CLI exit |
| --- | --- | --- |
| Pass | Release checks pass | 0 |
| Warn | A smaller regression or partial check coverage is observed | 0 |
| Fail | Any critical sample fails, or aggregate loss exceeds the suite threshold | 1 |
| Incomplete | Execution, coverage, configuration, or baseline compatibility prevents a valid result | 2 |

The aggregate threshold defaults to five points. A loss of exactly five points warns. Score comparisons use exact fractions before display rounding.

A run without `--baseline` collects an explicitly uncompared reference and still applies the critical gate. `latest` selects the last promoted run for that suite and freezes its ID for the comparison. Completed pass/warn runs are eligible for explicit promotion. Every generation attempt records latency, token usage, and its usage source. These measurements are diagnostic under the default policy.

## Put the gate in a pull request

Generate a reference, inspect it, then promote and export its snapshot.

```sh
uv run regressguard baseline --run <run-id> --export baselines/<suite-id>.json
```

Commit the suite, prompt, and generated snapshot. The supplied workflow runs on PRs, selects affected suites from both Git trees, writes a job summary, and preserves JSON/Markdown artifacts. Shared prompts select every referencing suite. Engine, provider, dependency, or workflow changes select all suites. Valid docs-only changes succeed with no affected suites.

When the base evaluator exists, an isolated process uses that revision to score candidate outputs. Changed evaluation contracts also require a replayable proposed snapshot. New suites begin with an uncompared bootstrap run. Missing references, invalid refs, and unmapped evaluation files block the job.

Require **RegressGuard gate** in branch protection to make its result a merge requirement. Changes to the enforcement code itself still need review. The supplied gate uses mock generation and TF-IDF without judge credentials. A real application needs its feature adapter, representative cases, an accepted live reference, and a separately configured credentialed gate.

Reproduce a comparison locally from a Git checkout.

```sh
uv run regressguard ci --base <accepted-commit-sha> --head HEAD
```

Local reports go to `data/ci/`. The supplied version-2 baselines were generated by actual runs. Earlier evidence remains inspectable, and changing evaluator contracts requires an explicit new reference and promotion. [Baseline upgrade instructions](docs/EVALUATION.md#evaluator-version-changes)

## Define your own feature


Create a UTF-8 template under `prompts/` using the literal `{{input}}` placeholder and a YAML file under `suites/`. Run from the project root. The repository includes complete examples. Stable suite and case IDs identify evidence across file renames.

```yaml
schema_version: 1
id: greeting
name: Greeting contract
data_label: fictional_sample
feature:
  prompt: prompts/greeting/v1.txt
  prompt_version: v1
  model: mock/summarizer-v1
  generation:
    temperature: 0
policy:
  aggregate_drop_points: 5
cases:
  - id: greeting
    input: Hello there.
    expected_behavior: Preserve the greeting.
    severity: standard
    checks:
      - type: exact_match
        expected: Hello there.
```

For this mock example, the template should say `Preserve the facts. {{input}}`. Custom model IDs require an explicit live provider or a feature adapter. The provider boundary in `regressguard/providers.py` receives only the feature target, template, input and attempt index. Application integrations can implement that boundary to exercise their actual response path. It never receives reference answers or checks.

Each generated sample can run the following checks.

| Type | Configuration | Semantics |
| --- | --- | --- |
| `exact_match` | `expected` | Strict string equality |
| `contains` | nonempty `keywords`, optional `mode: all/any`, `case_sensitive` | Substring checks, default all and case-sensitive |
| `regex` | `pattern` | Search with a 100 ms execution deadline |
| `json_schema` | `schema` | Entire response must be strict JSON matching Draft 2020-12 |
| `semantic_similarity` | `reference`, `threshold` | Cosine score must meet threshold |
| `llm_judge` | `rubric`, `rubric_version`, `threshold` | Structured finite 0–1 judge score; skip without judge config |

JSON rejects surrounding prose, code fences, duplicate keys, NaN/Infinity and numeric overflow such as `1e999`. Schemas permit local references. Prompt paths cannot escape `prompts/`, including through symlinks. Duplicate YAML keys, IDs, unsupported parameters and invalid checks are rejected before running.

TF-IDF uses lowercase Unicode word tokens, smoothed IDF on fixed suite references, and L2 cosine with zero-vector score 0. Unseen tokens receive a fixed IDF in both vectors so invented words affect the score. Semantic checks default to `preserve_facts: true`, requiring matching negation-marker counts and numeric values. Results expose guard failures separately from cosine. Set this option to false for cosine-only measurement. The corpus and algorithm are fingerprinted. The optional embeddings extra uses a cached local model with remote code disabled.

```sh
uv sync --locked --extra embeddings
export REGRESSGUARD_SEMANTIC_BACKEND=embeddings
export REGRESSGUARD_EMBEDDING_PATH=/absolute/path/to/downloaded/model
```

Auto mode uses the provided local model if its dependency and assets are available, falling back to TF-IDF. It never downloads an embedding model during a run. Explicit embeddings mode reports missing assets. Changing representation, rubric, active judge, checks, inputs, severity, repetition count or scoring policy requires a compatible reference. Changing the prompt/model/params is the intended comparison.


## Runtime reference

<details>
<summary>Environment configuration and optional live calls</summary>


All runtime configuration uses environment variables. `.env.example` contains safe defaults. Compose reads a root `.env`; for local CLI use, export the desired variables in your shell. Merely placing a key in an environment file never selects live generation.

| Variable | Default / purpose |
| --- | --- |
| `DATABASE_URL` | `sqlite:///data/regressguard.db`; conventional PostgreSQL URLs normalize to the psycopg driver |
| `REGRESSGUARD_DATA_DIR` | `data`, local alert and CI output directory |
| `REGRESSGUARD_PROVIDER` | `mock`; explicitly choose `openai` for compatible chat-completions endpoints |
| `OPENAI_BASE_URL` | Endpoint base, default `https://api.openai.com/v1` |
| `OPENAI_API_KEY` | Live generation key, blank by default |
| `REGRESSGUARD_JUDGE_MODEL`, `REGRESSGUARD_JUDGE_KEY` | Independent opt-in judge |
| `REGRESSGUARD_SEMANTIC_BACKEND` | `auto` in code, `tfidf` in Compose/CI |
| `REGRESSGUARD_EMBEDDING_PATH` | Optional local model artifact |
| `REGRESSGUARD_WEBHOOK_URL` | Optional Slack-compatible JSON webhook |
| `REGRESSGUARD_SEED_BASELINES` | `1` in Compose, idempotent import on fresh databases |
| `REGRESSGUARD_ROOT` | Working directory, root for suite discovery |
| `REGRESSGUARD_CI_OUTPUT` | `data/ci`, generated gate reports |

For PostgreSQL, set `DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DATABASE`. Use an existing database reachable by the app. Run `uv run python demo/postgres_smoke.py` for explicit integration verification.

Live suites must use a model ID supported by the chosen endpoint. The client supports text chat completions with temperature, max_tokens, top_p and seed. Missing keys, malformed envelopes and transport failures remain visible errors. Both generation and judge calls have 30-second deadlines. Responses over 100 KB are rejected. Repetitions are bounded to 1–20, suites to 200 cases and checks to 20 per case. CI is configured for mock generation, TF-IDF and no judge credentials.


</details>

<details>
<summary>API endpoints and alert behavior</summary>


Open `/docs` for the generated API schema.

| Endpoint | Operation |
| --- | --- |
| `GET /api/suites` | Discover suites, target and promoted baseline |
| `POST /api/runs` | JSON body with suite_id, baseline (default latest, null collects reference), runs |
| `GET /api/runs?suite=…&limit=50&offset=0` | Paginated history |
| `GET /api/runs/{id}/report` | Persisted evidence and verdict |
| `POST /api/runs/{id}/baseline` | Explicit promotion |
| `GET /api/alerts` | Logical alerts and local/webhook delivery status |
| `GET /healthz` | Database readiness |

A quality fail returns its report as a completed API operation. An incomplete execution returns HTTP 502 and the persisted run ID. The single-process API permits one run at a time and reports 409 when busy. Dashboard trend segments break when contracts change and link to a table of actual observations.

Each completed fail transactionally creates one SQL alert payload, appends the same JSON to the local log, and sends it to the optional webhook. The payload includes suite/run IDs, old/new versions and failing counts. Delivery errors stay visible in `/api/alerts` and cannot turn the failure green. A crash between external delivery and recording delivery status can duplicate a physical alert. Its stable run ID permits receiver-side deduplication.


</details>

## Verify the implementation

```sh
uv sync --locked
uv run ruff check .
uv run pytest -q
uv run python -m demo.transport_smoke
```

The default pytest suite uses temporary SQLite databases and blocks network sockets. It exercises all six check types, critical and aggregate policies, baseline compatibility, CLI exits, API behavior, alert errors, and Git-based CI comparisons. Engine tests use accepted fixtures so a deliberate feature regression reaches the quality gate independently.

The separate HTTP smoke starts a loopback server and sends actual requests through the compatible client and webhook code. It verifies generation, judging, missing usage, authentication failures, malformed envelopes, and identical alert payloads in HTTP, SQL, and JSONL. Responses are scripted. PostgreSQL persistence has its own hosted integration job.

## Scope and limitations

- **Evaluation quality depends on the cases and checks.** The classifier's 20 cases and the summarizer's four cases are fictional. They demonstrate the workflow and its edge cases. Hosted LLM quality and local embedding execution remain unverified.
- **Three attempts provide limited precision.** Samples can be correlated, and the mock's faults are controlled. The release policy measures observed failures without claiming statistical significance.
- **Similarity is one source of evidence.** TF-IDF can reject valid paraphrases. Negation/numeric guards can miss entity-role changes, shifted scope, and spelled-out quantities. Judges can also be biased or influenced by candidate text.
- **The application runs locally in one process.** Runs are synchronous, the dashboard has no authentication, and Compose publishes to loopback. Private-data use needs appropriate access controls and retention for SQL evidence, reports, and backups.
- **Alert delivery is observable and bounded.** Local logging is the default. External delivery has a timeout and recorded status, with no background retry service. A crash can duplicate a physical alert; its run ID supports deduplication.
- **Deployment protection requires integration.** Branch protection and deployment rules must require the check. Continuous traffic monitoring, distributed workers, SMTP, and database migration tooling are outside this version. Provider aliases can drift despite a fixed requested model ID.
