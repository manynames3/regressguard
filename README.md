# RegressGuard

Independent portfolio project. All demo inputs and outputs are fictional/sample data.

RegressGuard tests a proposed LLM feature against accepted evaluation evidence before merge. A reviewer sees repeated pass counts, critical failures, prompt/model changes, skipped checks, and a reproducible decision. The CLI, FastAPI dashboard and GitHub gate use the same runner.

## Start the dashboard

Python 3.12 and Docker are supported. The default mock requires no key or model downloads.

```sh
docker compose up --build
```

Open http://localhost:8000. Both fictional suites and their generated baseline snapshots are ready to run. Select a feature and click **Run evaluation**. The named volume retains runs, accepted baselines and alerts. Restarting preserves later promotions.

## Run the demo locally

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run from the repository root.

```sh
uv sync --locked
uv run regressguard run --suite suites/ticket-classifier.yml --runs 3
# Copy the printed run UUID into the following command.
uv run regressguard baseline --run <run-id>
uv run regressguard run --suite suites/ticket-classifier.yml --baseline latest --runs 3
uv run python demo/break_it.py
```

The last command exits **1**. It removes the JSON instruction in memory, changes the prompt version and executes the normal runner against the promoted baseline. Your prompt files stay available for the next run. The failed report lists critical cases, counts, the prompt diff and the real alert location, `data/alerts.jsonl`. Run the original command with `--baseline latest` again and it exits **0**.

The classifier has 20 fictional cases, including sentiment, Spanish requests, vague text, instructions inside a ticket, and conflicting urgency signals. Priority is urgent for team-wide disruption, data loss and a security breach. Sentiment alone is normal. The summarizer has four fictional examples and demonstrates every remaining check, including a visibly skipped optional judge.

```sh
uv run regressguard run --suite suites/summarizer.yml --runs 3
uv run uvicorn api.app:app --host 127.0.0.1 --port 8000
```

The local server shares the CLI's default database. To use the Compose database from the CLI, run commands inside the service.

```sh
docker compose exec api .venv/bin/regressguard run --suite suites/ticket-classifier.yml --baseline latest
docker compose exec api .venv/bin/python demo/break_it.py
```

## Evidence beyond a format failure

```sh
uv run python -m demo.scenarios
REGRESSGUARD_SEMANTIC_BACKEND=tfidf uv run python -m demo.calibrate
```

The first command exercises a critical case falling from 3/3 to 2/3 and a candidate whose aggregate improves while a critical case regresses. Both must fail through the normal runner, storage and alert paths. It restores a healthy baseline afterward.

The second selects a threshold using a development set, then reports false alarms and missed regressions on a separate held-out set. Every fictional labeled pair and every observed error is inspectable. See [evaluation evidence](docs/EVALUATION.md) and the [generated calibration report](docs/calibration/report.md).

## How a decision is made

```mermaid
flowchart LR
    S[YAML suite and versioned prompt] --> R[Repeated generation]
    P[Mock or explicit model endpoint] --> R
    R --> E[Per-sample checks and measurements]
    E --> D[(SQL evidence)]
    B[Promoted baseline] --> C[Comparison]
    D --> C
    C --> V[Pass / warn / fail / incomplete]
    V --> U[CLI / dashboard / Actions summary]
    V --> A[Fail alert: SQL payload + JSONL + optional webhook]
```

A sample passes when all executed checks pass and at least one check executes. Each case's pass rate is passed samples divided by requested repetitions. The aggregate is the unweighted mean of case pass rates, expressed from 0 to 100.

- **Fail, exit 1** if any critical sample fails, or the aggregate drops strictly more than the configured threshold, default 5 points.
- **Warn, exit 0** for smaller observed regressions or partial check coverage, including skipped judges.
- **Pass, exit 0** when the release checks pass.
- **Incomplete, exit 2** for execution errors or a case with no executed checks. Configuration errors, missing requested baselines and incompatible contracts also exit 2.

Exactly five points of aggregate loss warns at the default boundary. With 20 cases and three attempts, one critical case falling from 3/3 to 2/3 fails even though the mean drops only 1⅔ points. Comparisons use exact fractions before formatting. Attempts are never retried just to obtain a passing answer.

Without `--baseline`, a run explicitly collects an **uncompared** reference and still applies the critical gate. `latest` resolves the most recently promoted run for that suite. Failed and incomplete runs cannot be promoted. The selected baseline stays fixed during execution.

Every attempt records generation latency, usage and usage source. Mock usage is a deterministic whitespace estimate over prompt, input and output. Live usage comes from the endpoint or is null with an unavailable source. Judge usage is separate. These metrics are diagnostic and do not trigger the default quality gate.

## Add a suite

Create a UTF-8 template under `prompts/` using the literal `{{input}}` placeholder and a YAML file under `suites/`. Run from the project root. The repository includes complete examples. Stable suite and case IDs identify evidence across file renames.

```yaml
schema_version: 1
id: greeting
name: Greeting contract
data_label: user_supplied
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

Supported checks:

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

## Baselines and the CI gate

SQL stores local run history. Git stores portable snapshots with case counts, prompt and target provenance, evaluator fingerprint and no raw sample outputs.

```sh
uv run regressguard baseline --run <run-id> --export baselines/<suite-id>.json
```

Commit the suite, prompt and generated snapshot. The supplied snapshots were produced by evaluator version 2 on the fictional demos. Earlier serialized contracts remain inspectable. Updating an old local baseline requires an explicit new reference and promotion, as documented in [evaluation evidence](docs/EVALUATION.md). Hashes detect corruption. The reviewed base commit is the source of trust.

`.github/workflows/regression-gate.yml` runs on pull requests and supports forks without secrets. It tests affected suites and writes reports to the job summary. Select **RegressGuard gate** as a required check in GitHub branch protection. This repository also supplies a PostgreSQL integration job.

The job resolves the actual base and tested merge commit, maps changed files across both trees and selects shared-prompt dependents. Engine, provider, dependency or workflow changes select all suites. A docs-only change succeeds with no affected suites. Unmapped evaluation files, deleted suites, missing snapshots and invalid Git refs block. Filenames are passed as data.

For existing suites, the **accepted base cases and policy** run against the **candidate target**, using the baseline from the base commit. When base evaluator code exists, an isolated process uses it to score candidate outputs. Editing expected answers, deleting a critical check, loosening a threshold or substituting a snapshot in the same PR cannot remove that comparison. Engine and workflow changes still require human review because enforcement code itself can change.

Changed contracts also require a proposed snapshot that replays successfully against the proposed suite. New suites have a clearly uncompared bootstrap run and need a generated snapshot. An accepted earlier prompt baseline can remain in place through prompt-only changes. Suite retirement requires a separately reviewed policy. Reports include both comparisons where applicable. All affected suites execute before the final status is returned.

Reproduce the Actions path in a Git checkout:

```sh
uv run regressguard ci --base <accepted-commit-sha> --head HEAD
```

The command writes `data/ci/report.json` and `summary.md`. In CI it appends to `GITHUB_STEP_SUMMARY`. To demonstrate a hosted failure, commit a prompt edit replacing `Return JSON only` with `Return plain text`, open a PR, inspect the failing required job, then restore the instruction and push the fix. The private repository now has observed red/green hosted runs. See [hosted CI proof](docs/CI_PROOF.md) for the PR, run links and downloaded artifact evidence.

## Configuration and optional live calls

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

## API and alert behavior

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

## Verification

```sh
uv sync --locked
uv run ruff check .
uv run pytest -q
uv run python -m demo.transport_smoke
```

The default pytest suite blocks network sockets and uses temporary SQLite databases. It covers each check, skipped and invalid judges, strict JSON, threshold boundaries, critical failures, baseline round-trips, CLI process exits, API parity and temporary Git histories with broken prompts and edited evidence. Unit tests use a fake HTTP transport. The separate transport smoke starts a local HTTP server and exercises actual requests for generation, judging, auth errors, malformed responses, missing usage and identical webhook/SQL/JSONL payloads. Its responses are scripted fixtures. It uses no paid API or external service. PostgreSQL runs in a separate integration job.

## Limitations

Three repeated attempts provide smoke-test evidence, with little statistical precision. Samples may be correlated. The scripted mock demonstrates the pipeline and has no general language understanding. Its results do not measure any hosted model's quality. TF-IDF can reject paraphrases. The conservative negation/numeric guards cannot resolve entity roles, negation scope or spelled-out quantities, and embedding thresholds have different meanings. The held-out report records concrete misses and false alarms. Judges can be biased or influenced by candidate text.

This is a local single-process application with synchronous runs and no user authentication. Compose publishes to loopback. Before using private data, choose access controls and a retention policy for SQL evidence, reports and backups. Raw sample responses remain in SQL and report pages; baseline snapshots omit them. Alerting defaults to local logging. External delivery has no background retry service. SMTP, distributed workers and continuous traffic monitoring are outside this version. Schema creation supports a fresh database; schema upgrades will need an explicit migration strategy. Provider aliases can drift, and seed parameters cannot guarantee deterministic hosted generation.
