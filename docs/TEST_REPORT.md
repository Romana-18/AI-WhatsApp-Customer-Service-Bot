# KAALEX implementation test report

Report date: 2026-09-09
Last updated: 2026-09-10

## Task evidence

### T01 — dependencies and containers

Status: IMPLEMENTED; automated/local container gate passed; live Hugging Face routability check
BLOCKED on a missing owner token.

Created files:

- `.python-version`
- `pyproject.toml`
- `uv.lock`
- `.gitignore`
- `.dockerignore`
- `Dockerfile`
- `compose.yaml`
- `.env.example`
- `app/__init__.py`
- `app/routes/__init__.py`
- `app/config.py`
- `tests/conftest.py`
- `tests/test_config.py`
- `docs/TEST_REPORT.md`

No pre-existing specification file was modified. No T02 file was created.

Configuration evidence:

- Required settings are typed with Pydantic Settings.
- Enabled Hugging Face requires `HF_TOKEN` and `HUGGINGFACE_MODEL`.
- The configured candidate is `Qwen/Qwen2.5-7B-Instruct:cheapest`.
- Enabled WhatsApp requires every Meta credential and an explicit Graph API version.
- Production rejects non-HTTPS public origins.
- A supplied test database URL must differ from the application database URL.
- Secrets use `SecretStr`, input values are hidden from validation errors, and `.env.example`
  contains blank secret fields.
- Default tests patch HTTPX's real sync and async transports while retaining MockTransport and
  ASGI transport behavior. Opt-in live tests require both a `live` marker and
  `RUN_LIVE_TESTS=1`.

Dependency evidence:

- Host Python discovered: 3.10.5.
- uv installed and used: 0.12.11.
- uv downloaded/selected CPython 3.12.14 from `.python-version`.
- `uv lock --check`: resolved 40 packages successfully.
- `uv.lock` SHA-256 before and after frozen sync:
  `F1065D1FD451BE1B0426047E69C8EC6751BA19394F1CBFD0D2604C09AE070E83`.
- Direct locked packages: alembic 1.19.2, argon2-cffi 25.1.0, fastapi 0.141.1,
  httpx 0.28.1, Jinja2 3.1.6, psycopg[binary] 3.3.5, pydantic 2.13.5,
  pydantic-settings 2.15.0, SQLAlchemy 2.0.52, uvicorn 0.52.4, pytest 9.1.1,
  pytest-asyncio 1.4.0, and ruff 0.16.6.

Container evidence:

- Docker Engine/server: 29.0.1, Linux containers on Docker Desktop.
- Docker Compose: v2.40.3-desktop.1; profiles and health-check dependencies parsed successfully.
- Python image: `python:3.12.14-slim-bookworm`, digest
  `sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254`.
- PostgreSQL image: `postgres:17.11-bookworm`, digest
  `sha256:051f7b7b3abdd564d1dd22020ede611c096a272e0`.
- Final runtime image ID:
  `sha256:17541f2fbf1b6c421bae68a2656193f6288541c205022131c5836fd6129fd15f`.
- Final test image ID:
  `sha256:329e272adf6ce48b6c65b7a6f8fedaca60fb500bc87489fcd79646f8ef3b7b43`.
- Runtime inspection observed Python 3.12.14, uv 0.12.11, and non-root
  `uid=999(app) gid=999(app)`.
- The runtime and test targets install from `uv.lock` with `uv sync --frozen`.
- `web` builds the runtime image and `worker` consumes the same image. The test profile builds a
  separate target containing development tools.
- Compose binds web to `127.0.0.1:8000`; the application database has no host port; application
  and test database volumes are distinct.
- Build-context inspection found no `.env`, private key, certificate key, or local database file.
  The included `.env.example` has blank secrets.

Corrections made during verification:

- Initial Docker Hub pulls failed DNS resolution. Exact-tag retries later succeeded; no tag was
  substituted.
- Building `web` and `worker` as duplicate exporters of the same image caused an image export
  race. Compose now builds through `web`, while `worker` consumes that same image.
- A canceled BuildKit export left a missing snapshot. A non-destructive `--no-cache` retry passed;
  no Docker data was pruned.
- The first container pytest run showed uv could not write under the non-root user's nonexistent
  home. `UV_CACHE_DIR=/tmp/uv-cache` was added.
- The second container pytest run exposed a console-script import-path issue and blank Compose
  environment values. The test command now uses `python -m pytest`, `/opt/app` is owned by the app
  user, empty environment values are ignored, and tests explicitly isolate their settings inputs.

## Commands actually run

Commands are listed chronologically. Repeated commands are retained because their failures and
subsequent successful retries are part of the evidence.

1. `Get-Content -Raw -LiteralPath '<specification file>'` for `AGENTS.md`,
   `COMPANY_RULES.md`, `DECISIONS.md`, `README.md`, and `task.md`.
2. `Get-ChildItem -Force -Recurse | Select-Object FullName,PSIsContainer`
3. `python --version`
4. `uv --version` — command not found.
5. `docker version --format '{{json .}}'` — sandboxed engine access failed.
6. `docker compose version`
7. `Get-Command uv -ErrorAction SilentlyContinue | Format-List *; py -0p; pipx --version`
8. `python -m pip install --user uv==0.12.11`
9. `python -m uv --version; python -m uv lock`
10. `Get-Item -LiteralPath 'uv.lock'; Get-Content -LiteralPath 'uv.lock' -TotalCount 20`
11. `Get-FileHash -Algorithm SHA256 -LiteralPath 'uv.lock'`
12. `python -m uv sync --frozen`
13. `Get-FileHash -Algorithm SHA256 -LiteralPath 'uv.lock'` (post-sync)
14. `.\.venv\Scripts\python.exe --version`
15. `.\.venv\Scripts\python.exe -c '<direct dependency version inspection>'`
16. `.\.venv\Scripts\ruff.exe --version`
17. `.\.venv\Scripts\python.exe -m pytest -q`
18. `.\.venv\Scripts\ruff.exe check .`
19. `.\.venv\Scripts\ruff.exe format --check .`
20. `docker compose --profile test config`
21. `Test-Path -LiteralPath 'C:\Program Files\Docker\Docker\Docker Desktop.exe'; Get-Process ...`
22. `docker info --format '{{json .ServerVersion}}'` — sandboxed pipe access failed.
23. `docker info --format '{{json .}}'` — elevated access passed.
24. `docker pull python:3.12.14-slim-bookworm` — initial DNS failure.
25. `docker pull postgres:17.11-bookworm` — initial DNS failure.
26. `docker image inspect python:3.12.14-slim-bookworm --format '{{json .RepoDigests}}'` —
    image was not yet cached.
27. `docker image inspect postgres:17.11-bookworm --format '{{json .RepoDigests}}'` — image was
    not yet cached.
28. `docker compose build` — initial long-running attempt.
29. `docker compose build` — duplicate image exporter failure captured.
30. `docker compose build` — missing BuildKit parent snapshot failure.
31. `docker compose build --no-cache` — passed.
32. `docker compose --profile test build test` — passed.
33. `docker compose --profile test run --rm --no-deps test` — failed on non-root uv cache.
34. `docker compose --profile test build web test` — passed after cache-path correction.
35. `docker compose --profile test run --rm --no-deps test` — failed on blank environment/input
    isolation issues.
36. `docker compose --profile test build web test` — passed while investigating final context.
37. `Get-Content` review of `.dockerignore`, `app/config.py`, and `tests/test_config.py`.
38. `.\.venv\Scripts\python.exe -m pytest -q` — passed.
39. `.\.venv\Scripts\ruff.exe check .` — passed.
40. `.\.venv\Scripts\ruff.exe format --check .` — passed.
41. `docker compose --profile test build web test` — final build passed.
42. `docker compose --profile test run --rm --no-deps test` — final container run passed.
43. `docker pull postgres:17.11-bookworm` — exact-tag retry passed.
44. `docker image inspect python:3.12.14-slim-bookworm postgres:17.11-bookworm ...` — Python
    tag was not yet retained; PostgreSQL digest recorded.
45. `docker image inspect kaalex-whatsapp-bot:local kaalex-whatsapp-bot:test ...`
46. `docker run --rm --entrypoint python kaalex-whatsapp-bot:local --version`
47. `docker run --rm --entrypoint uv kaalex-whatsapp-bot:local --version`
48. `docker run --rm --entrypoint id kaalex-whatsapp-bot:local`
49. `docker pull python:3.12.14-slim-bookworm` — exact-tag retry passed.
50. `docker image inspect python:3.12.14-slim-bookworm postgres:17.11-bookworm ...` — both
    canonical digests recorded.
51. `python -m uv lock --check` and `python -m uv tree --frozen --depth 1` — sandboxed user-cache
    access failed.
52. `Get-FileHash -Algorithm SHA256 -LiteralPath 'uv.lock'`
53. `rg -n -i 'openrouter|redis|celery|langchain|vector database|givingchampion' ...`
54. `Get-ChildItem ...` scan for `.env`, private key, and database files.
55. `python -m uv --cache-dir .uv-cache lock --check` — passed.
56. `python -m uv --cache-dir .uv-cache tree --frozen --depth 1` — passed.
57. `docker compose --profile test config --quiet` — passed.
58. `docker run --rm --entrypoint find kaalex-whatsapp-bot:local /opt/app ...`
59. PowerShell presence-only check for `HF_TOKEN` — returned `HF_TOKEN_PRESENT=false`; no token
    value was read or logged.
60. `Get-Content -Raw -LiteralPath '<changed file>'` for final source review.
61. `git diff --stat` — failed because the supplied folder is not a Git repository.
62. `Get-ChildItem -Force -Recurse ...` — final repository inventory.
63. `.\.venv\Scripts\python.exe -m pytest -q` — final local run passed.
64. `.\.venv\Scripts\ruff.exe check .` — final lint run passed.
65. `.\.venv\Scripts\ruff.exe format --check .` — final format run passed.
66. `docker compose --profile test build web test` — cached export hit Docker Desktop's
    missing-snapshot error after the build context changed.
67. `docker compose build --no-cache web` — final isolated runtime build passed.
68. `docker compose --profile test build --no-cache test` — final isolated test build passed.
69. `docker compose --profile test run --rm --no-deps test` — final container run passed.
70. `docker image inspect kaalex-whatsapp-bot:local kaalex-whatsapp-bot:test ...` — final IDs and
    non-root users recorded.
71. `docker run --rm --entrypoint find kaalex-whatsapp-bot:local /opt/app ...` — final image-context
    inventory; `docs/` is excluded.

## Automated tests

- PASS — final local: `.\.venv\Scripts\python.exe -m pytest -q` → 13 passed in 1.11s.
- PASS — final container: `docker compose --profile test run --rm --no-deps test` → 13 passed in
  0.40s on Linux/Python 3.12.14.
- PASS — lint: `ruff check .` → all checks passed.
- PASS — format: `ruff format --check .` → 11 files already formatted.
- PASS — Compose: `docker compose --profile test config --quiet` exited 0.
- PASS — frozen lock: SHA-256 unchanged and `uv lock --check` resolved 40 packages.

### T01 acceptance criteria

1. PASS — runtime and test container targets built from the frozen lock; local frozen sync left the
   lock hash unchanged.
2. PASS — tests prove enabled providers reject missing credentials with actionable names and no
   secret values, while disabled providers require no fake credentials.
3. PASS — tests prove production HTTP is rejected, production HTTPS is accepted, and local
   loopback HTTP is accepted.
4. PASS — tests prove an equal test/application database URL is rejected and a distinct URL is
   accepted.
5. PASS — real HTTPX transports are blocked in default tests while MockTransport works. Secret and
   database-file scans were empty; `.dockerignore` excludes local secrets and database files.
6. PASS — configuration and `.env.example` use only `HF_TOKEN`, `HUGGINGFACE_MODEL`, and the locked
   Hugging Face candidate; the source scan found no OpenRouter integration (only the negative test
   assertion mentions its name).

## Live tests

- BLOCKED — configured Hugging Face model routability/free-allowance check.
  `HF_TOKEN_PRESENT=false` on 2026-09-09. No real provider call was made, no credits were purchased,
  and no model/provider fallback was selected. An owner-provided fine-grained `HF_TOKEN` and
  explicit live-run opt-in are required.
- WhatsApp live tests are outside T01 and were not run.

## Blockers

- The T01 local/image/lock gate is proven.
- Hugging Face account-specific routability and free allowance remain BLOCKED until the owner
  supplies the required token and authorizes the opt-in request.

## Limitations

- This report covers T01 and T02 only.
- No application routes, integration clients, worker implementation, or UI are implemented yet.
- The `web` and `worker` commands intentionally reference modules scheduled for later tasks; images
  build now, but those services are not expected to start until their modules exist.
- The T01-only test run used `--no-deps` intentionally. T02 uses the isolated `test-db` service.
- The first failed Compose test run created the project default network and an empty named test DB
  volume. They were left intact rather than deleting Docker state without an explicit request.
- Windows PowerShell emitted a profile execution-policy warning for elevated commands; the commands'
  recorded exit statuses and Docker results were still available.
- Health checks describe local process/database health only and do not prove Meta or Hugging Face
  availability.

### T02 — schema and migration

Status: IMPLEMENTED; isolated PostgreSQL migration, constraint, transaction, persistence, drift,
and full-regression gates passed. T03 was not started.

Files created, in task order:

- `app/db.py`
- `app/models.py`
- `alembic.ini`
- `migrations/env.py`
- `migrations/versions/0001_initial.py`
- `tests/test_database.py`

File modified after implementation and verification:

- `docs/TEST_REPORT.md`

Pre-existing user work preserved:

- `.env.example` already had one uncommitted blank-line insertion before T02. T02 did not edit or
  revert it.
- The five specification Markdown files were read but not modified.

Schema and migration evidence:

- Alembic revision `0001_initial` creates exactly the five application tables `employees`,
  `sessions`, `conversations`, `messages`, and `jobs`; Alembic also owns `alembic_version`.
- Conversation IDs use `BIGINT GENERATED BY DEFAULT AS IDENTITY`; all other entity IDs use UUID.
- Job `enqueue_sequence` uses a unique `BIGINT GENERATED BY DEFAULT AS IDENTITY` value.
- PostgreSQL `TIMESTAMPTZ` and `JSONB` are used where required.
- Foreign keys, uniqueness constraints, enum-value checks, nonnegative counters/version checks,
  length checks, and required operational indexes are installed by the migration.
- Partial unique indexes enforce one running job per conversation and one outbound bot result per
  trigger message.
- `alembic check` reported `No new upgrade operations detected`, proving the migration matches the
  SQLAlchemy metadata at this revision.
- The async engine rejects every driver except `postgresql+psycopg`; SQLite is explicitly refused.
- The session maker creates independent async sessions, and the scoped helper rolls back failed
  work.

Database and image evidence:

- Both `db` and `test-db` were observed healthy on PostgreSQL 17.11
  (`PostgreSQL 17.11 (Debian 17.11-1.pgdg12+2)`).
- Database identity was observed as `kaalex_test`; the safety fixture also requires Docker host
  `test-db`, database `kaalex_test`, and a target distinct from application database `kaalex`.
- No migration, insert, truncate, or query test was run against application database `kaalex`.
- Docker inspection showed separate durable named-volume mounts:
  `kaalex-whatsapp-bot_app-db-data` and `kaalex-whatsapp-bot_test-db-data`.
- A synthetic row inserted into `kaalex_test` remained after restarting `test-db` (count `1`) and
  was then deleted (`DELETE 1`). The deletion was intentional cleanup of synthetic test data and is
  not recoverable; no customer or application data was involved.
- Final runtime image: `kaalex-whatsapp-bot:local`, image ID
  `sha256:c59f0c74685f232384cbae17bf22e73bb3af09ec8c557fa9f0b7c5b9c5415654`, non-root user `app`.
- Final test image: `kaalex-whatsapp-bot:test`, image ID
  `sha256:d793ac223be24055f5d4a6cfb2cbcbeb04c579b5818722bc5b3af8431dfb2eae`, non-root user `app`.
- Both images retain the T01 frozen dependency lock; T02 added no dependencies and did not modify
  `pyproject.toml` or `uv.lock`.

#### T02 commands actually run

Commands are chronological. Repeated builds and test runs are retained to distinguish failures
from successful corrected reruns. Secret values are omitted.

1. `Get-Content -Raw -LiteralPath '<attached pasted-text.txt>'`
2. `Get-Content -Raw -LiteralPath 'AGENTS.md'`
3. `Get-Content -Raw -LiteralPath 'COMPANY_RULES.md'`
4. `Get-Content -Raw -LiteralPath 'DECISIONS.md'`
5. `Get-Content -Raw -LiteralPath 'README.md'`
6. `Select-String` extraction of the complete T02 section from `task.md`
7. `rg --files`; `git status --short`; presence-only `.env` inspection
8. `git status --short`; `git diff -- .env.example`; `git log -1 --oneline`
9. `docker compose --profile test ps`
10. `.\.venv\Scripts\ruff.exe check app/db.py app/models.py migrations/env.py migrations/versions/0001_initial.py tests/test_database.py` — failed on one unused import.
11. `.\.venv\Scripts\ruff.exe format --check app/db.py app/models.py migrations/env.py migrations/versions/0001_initial.py tests/test_database.py` — reported one file requiring formatting.
12. `.\.venv\Scripts\ruff.exe format tests/test_database.py` — reformatted one file.
13. `.\.venv\Scripts\ruff.exe check app/db.py app/models.py migrations/env.py migrations/versions/0001_initial.py tests/test_database.py` — passed after the import correction.
14. `.\.venv\Scripts\ruff.exe format --check app/db.py app/models.py migrations/env.py migrations/versions/0001_initial.py tests/test_database.py` — passed.
15. `.\.venv\Scripts\python.exe -m pytest tests/test_config.py -q` — 13 passed in 1.01s.
16. `docker compose --profile test up -d test-db` — created and started the isolated test database.
17. `docker compose --profile test build --no-cache test` — passed with the frozen lock.
18. `docker compose --profile test run --rm test uv run --frozen python -m pytest tests/test_database.py -q` — 17 setup errors; Pydantic's multi-host DSN object did not expose `.host`.
19. `.\.venv\Scripts\ruff.exe check app/db.py app/models.py migrations/env.py migrations/versions/0001_initial.py tests/test_database.py` — passed after using SQLAlchemy URL parsing.
20. `.\.venv\Scripts\ruff.exe format --check app/db.py app/models.py migrations/env.py migrations/versions/0001_initial.py tests/test_database.py` — passed.
21. `docker compose --profile test build test` — passed.
22. `docker compose --profile test run --rm test uv run --frozen python -m pytest tests/test_database.py -q` — 16 passed, 1 failed; the rollback assertion accessed an expired ORM object outside async I/O.
23. `docker compose --profile test build test` — passed after retaining the scalar conversation ID before the deliberate rollback.
24. `docker compose --profile test run --rm test uv run --frozen python -m pytest tests/test_database.py -q` — 17 passed in 2.00s.
25. `docker compose --profile test run --rm test sh -c 'export DATABASE_URL="$TEST_DATABASE_URL"; unset TEST_DATABASE_URL; exec uv run --frozen alembic downgrade base'` — passed.
26. `docker compose --profile test run --rm test sh -c 'export DATABASE_URL="$TEST_DATABASE_URL"; unset TEST_DATABASE_URL; exec uv run --frozen alembic upgrade head'` — passed.
27. The preceding `alembic upgrade head` command was run a second time — passed with no additional migration.
28. A shell-wrapped synthetic persistence insert was attempted — failed with a shell quoting syntax error before executing SQL; no data changed.
29. `docker compose --profile test exec -T test-db psql -U kaalex_test -d kaalex_test -c '<synthetic INSERT>'` — `INSERT 0 1`.
30. `docker compose --profile test restart test-db` — passed.
31. `docker compose --profile test exec -T test-db psql -U kaalex_test -d kaalex_test -c '<synthetic persistence count>'` — returned `1`.
32. `docker compose --profile test exec -T test-db psql -U kaalex_test -d kaalex_test -c '<synthetic cleanup DELETE>'` — `DELETE 1`.
33. `docker compose --profile test run --rm test sh -c 'export DATABASE_URL="$TEST_DATABASE_URL"; unset TEST_DATABASE_URL; exec uv run --frozen alembic check'` — `No new upgrade operations detected`.
34. `docker compose --profile test run --rm test` — 30 passed in 2.40s.
35. `docker compose --profile test exec -T test-db postgres --version`
36. `docker compose --profile test exec -T test-db psql -U kaalex_test -d kaalex_test -Atc 'SELECT current_database(), current_setting(...)'`
37. `docker inspect kaalex-whatsapp-bot-db-1 kaalex-whatsapp-bot-test-db-1 --format '<mount evidence>'`
38. `docker compose --profile test build test` — passed after hardening safety evidence to retain only the application database name.
39. `docker compose --profile test run --rm test` — final 30 passed in 2.21s.
40. `.\.venv\Scripts\ruff.exe check .` — all checks passed.
41. `.\.venv\Scripts\ruff.exe format --check .` — 16 files already formatted.
42. `docker compose build web` — runtime image built successfully from the frozen lock.
43. `git status --short`; `git diff --check`; `git diff --stat`
44. `rg -n --hidden --glob '!.git/**' --glob '!.env' '<unfinished/forbidden-pattern scan>' app/db.py app/models.py alembic.ini migrations/env.py migrations/versions/0001_initial.py tests/test_database.py`
45. `Get-Content -Raw -LiteralPath '<T02 changed file>'` for final source review.
46. `Get-Content -Raw -LiteralPath 'docs/TEST_REPORT.md'`
47. `docker compose --profile test ps`; final image inspection for ID and configured user.
48. `Get-ChildItem -Force -Recurse` with generated/cache directories filtered — final repository inventory.
49. `git diff --check`; `git status --short`; `git diff --stat` — diff check passed; status and stat captured.
50. Presence-only comparison of configured secret values against T02 changed files — `CHANGED_FILE_SECRET_MATCHES=0`; no values were printed.
51. `git diff --check`; `git status --short`; `git diff --stat` — final post-report scope evidence.

Corrections and truthful failure record:

- The initial database test run failed before migration because Pydantic's `PostgresDsn` is a
  multi-host URL and has no `.host` attribute. The guard now parses both URLs with SQLAlchemy and
  strictly permits only `test-db/kaalex_test`.
- That traceback rendered the local test DSN once. It is redacted from this report and is not
  committed. The current safety fixture does not retain or render the application DSN; rotate the
  test-only password if it is reused outside this disposable local database.
- The next run's single failure was a test-code async lifecycle issue after a deliberate rollback,
  not a database atomicity failure. Capturing the scalar key before rollback corrected the test;
  the resulting assertions prove both the message and job counts are zero.
- The first persistence insert wrapper had invalid shell quoting and never reached PostgreSQL. The
  direct `psql` insert, restart, count, and cleanup all succeeded.

#### T02 automated-test totals

- PASS — database suite: 17/17 tests.
- PASS — retained T01 configuration suite: 13/13 tests.
- PASS — final full regression in the isolated container: 30/30 tests in 2.21s.
- PASS — Ruff lint and formatting gates.
- PASS — Alembic/model drift gate.

#### T02 acceptance criteria

1. PASS — an empty isolated database upgraded to `0001_initial` and contained all five application tables plus `alembic_version`.
2. PASS — a second `upgrade head` completed without creating duplicate schema objects.
3. PASS — `downgrade base` removed the application tables and re-upgrade restored the exact schema.
4. PASS — duplicate conversation `wa_id` was rejected by PostgreSQL.
5. PASS — duplicate message `provider_message_id` was rejected by PostgreSQL.
6. PASS — duplicate job `inbound_message_id` was rejected by PostgreSQL.
7. PASS — orphan foreign-key records were rejected by PostgreSQL.
8. PASS — invalid conversation, message, and job enum values were rejected by database checks.
9. PASS — the partial unique index rejected two running jobs for one conversation.
10. PASS — a deliberately failed transaction persisted neither its inbound message nor its job.
11. PASS — three jobs received distinct, monotonically increasing identity-backed enqueue sequences.
12. PASS — all destructive fixtures require `test-db/kaalex_test`; current-database evidence confirmed the target, and the application database was untouched.
13. PASS — the retained T01 suite passed together with T02 (30 total tests).
14. PASS — schema inspection verified identity columns, timezone-aware timestamps, JSONB, and required partial indexes.
15. PASS — duplicate browser `client_request_id` and duplicate bot output for one trigger were rejected.
16. PASS — test-database data survived a service restart on its durable named volume; Docker inspection confirmed the application and test databases use separate named volumes. The application volume itself was not mutated because the acceptance safety rule forbids running tests against `kaalex`.

#### T02 blockers and limitations

- No T02 implementation or automated-test blocker remains.
- The T01 live Hugging Face token/routability blocker is unchanged and is unrelated to T02.
- PostgreSQL integration tests require Docker and the exact isolated `test-db/kaalex_test` target.
- T03 and every later task remain unimplemented.

### T02 security correction — safe database evidence

Correction date: 2026-09-10

Status: PASS. The test database password is no longer rendered into or stored as a visible DSN in
normal pytest evidence. No schema or migration revision was changed, and T03 was not started.

Files modified:

- `tests/test_database.py`
  - Removed `render_as_string(hide_password=False)`.
  - Keeps the parsed SQLAlchemy `URL` object internal for database connections and Alembic.
  - Stores only safe evidence: the application database name and `test-db/kaalex_test` target.
  - Adds `test_safe_database_evidence_excludes_password`, using a synthetic password and proving it
    is absent from the evidence representation.
- `migrations/env.py`
  - Preserves an explicitly supplied SQLAlchemy `URL` object instead of converting its masked
    string representation back into a connection URL.
  - Still accepts configured string/Pydantic URLs by parsing them internally with SQLAlchemy.
- `app/db.py`
  - Extends the existing engine-helper type annotation to accept a parsed SQLAlchemy `URL` directly;
    PostgreSQL/psycopg validation is unchanged.
- `docs/TEST_REPORT.md`
  - Records this correction and the actual verification results.

Files explicitly unchanged:

- `app/models.py`
- `migrations/versions/0001_initial.py`
- `alembic.ini`
- All specification files

Commands actually run for this correction:

1. `Get-Content -Raw -LiteralPath 'tests/test_database.py'`
2. `Get-Content -Raw -LiteralPath 'migrations/env.py'`
3. `Get-Content -Raw -LiteralPath 'docs/TEST_REPORT.md'`
4. `git status --short`
5. `rg -n "render_as_string|hide_password|test_url|connection_url|safe_target_evidence" tests/test_database.py migrations/env.py`
6. `.\.venv\Scripts\ruff.exe check tests/test_database.py migrations/env.py` — passed.
7. `.\.venv\Scripts\ruff.exe format --check tests/test_database.py migrations/env.py` — failed because the new synthetic URL construction required formatting.
8. `.\.venv\Scripts\ruff.exe format tests/test_database.py` — reformatted one file.
9. `docker compose --profile test build test` — passed.
10. `docker compose --profile test run --rm test uv run --frozen python -m pytest tests/test_database.py -q` — 18 passed in 7.19s.
11. `docker compose --profile test run --rm test` — 31 passed in 6.65s.
12. `.\.venv\Scripts\ruff.exe check .` — passed.
13. `.\.venv\Scripts\ruff.exe format --check .` — passed; 16 files already formatted.
14. `docker compose --profile test build test` — passed after the final parsed-URL type annotation.
15. `.\.venv\Scripts\ruff.exe check .` — final run passed.
16. `.\.venv\Scripts\ruff.exe format --check .` — final run passed; 16 files already formatted.
17. `docker compose --profile test run --rm test uv run --frozen python -m pytest tests/test_database.py -q` — final run: 18 passed in 5.32s.
18. `docker compose --profile test run --rm test` — final run: 31 passed in 6.54s.
19. `rg` source scan, final `Get-Content` review, `git diff --check`, `git status --short`, and `git diff --stat` — no password-visible URL rendering remained in application/test code; diff check passed.
20. Added assertions that the internally retained SQLAlchemy URL's ordinary string and repr diagnostics also exclude the synthetic password.
21. `docker compose --profile test build test` — passed with the strengthened regression.
22. `.\.venv\Scripts\ruff.exe check .` — final strengthened-regression run passed.
23. `.\.venv\Scripts\ruff.exe format --check .` — final strengthened-regression run passed; 16 files already formatted.
24. `docker compose --profile test run --rm test uv run --frozen python -m pytest tests/test_database.py -q` — final authoritative run: 18 passed in 5.12s.
25. `docker compose --profile test run --rm test` — final authoritative run: 31 passed in 5.38s.

Final correction evidence:

- PASS — focused regression proves the synthetic test password is absent from `repr(evidence)`.
- PASS — the same regression proves SQLAlchemy's ordinary `str(URL)` and `repr(URL)` diagnostics
  also mask the internally retained password.
- PASS — Alembic's existing downgrade/upgrade lifecycle tests receive the parsed credential-bearing
  URL internally and still pass.
- PASS — no `render_as_string(hide_password=False)` remains in the test or Alembic environment.
- PASS — database suite: 18/18 in 5.12s.
- PASS — full suite: 31/31 in 5.38s.
- PASS — `ruff check .`.
- PASS — `ruff format --check .`.
- No blocker remains for this T02 correction.
