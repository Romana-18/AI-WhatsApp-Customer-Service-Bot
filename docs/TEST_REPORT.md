# KAALEX implementation test report

Report date: 2026-09-09

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

- This report covers T01 only.
- No database schema, migrations, application routes, integration clients, worker implementation,
  or UI are implemented yet.
- The `web` and `worker` commands intentionally reference modules scheduled for later tasks; images
  build now, but those services are not expected to start until their modules exist.
- Database startup/migration and persistence testing begin in T02; the T01 test run used
  `--no-deps` intentionally.
- The first failed Compose test run created the project default network and an empty named test DB
  volume. They were left intact rather than deleting Docker state without an explicit request.
- Windows PowerShell emitted a profile execution-policy warning for elevated commands; the commands'
  recorded exit statuses and Docker results were still available.
- Health checks describe local process/database health only and do not prove Meta or Hugging Face
  availability.
