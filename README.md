# KAALEX WhatsApp assistant — implementation contract

Status: specification only. No application has been implemented or tested by preparing these files.

## Start here

Copy these five Markdown files into an empty repository root. Codex must read `AGENTS.md`, `DECISIONS.md`, `COMPANY_RULES.md`, then implement `task.md` in order. This specification replaces earlier KALAX plans, OpenRouter-specific plans, fixed-package pricing, old working hours, and earlier tutorial implementation instructions.

Build a small single-company WhatsApp assistant with an Arabic employee inbox. Customers and the employee use the same business WhatsApp conversation. The employee uses our browser inbox. The bot answers from approved company knowledge, queues human requests, and stops replying when the employee takes over.

## Scope

- One company, one WhatsApp number, exactly one employee login.
- Text messages, conversation history, human queue, takeover, manual replies, return to bot.
- Hugging Face Inference Providers AI; official Meta WhatsApp Cloud API; Docker Compose.
- Current development/trial AI usage must stay within available free Hugging Face usage/credits. Any later paid usage requires an explicit owner decision.
- Ten simultaneous customer conversations are a test target, not a capacity guarantee.
- Two working days are the implementation target for a pilot. External setup and failed acceptance tests can delay live delivery.
- No Chatwoot, n8n, separate frontend framework, vector database, Redis, Celery, microservices, booking calendar, payments, campaigns, CRM, employee roles or customer account system.
- Unsupported attachments create a human request; no audio transcription or image interpretation in this version.
- Backup/restore automation is deferred from this implementation phase.

## Core ownership behavior

- `bot`: normal grounded AI responses are allowed.
- `waiting`: the human request is already queued; AI may only acknowledge and collect missing details one question per customer turn.
- `human`: AI is completely silent.
- A high-confidence explicit human/handoff request is queued during inbound persistence, before optional AI collection, so an older running AI response becomes stale.
- The employee must explicitly return the conversation to the bot.
- Conversation versioning plus one final locked send gate prevents stale bot output from starting after takeover has committed.

## Planned structure

```text
README.md
AGENTS.md
DECISIONS.md
COMPANY_RULES.md
task.md
pyproject.toml
uv.lock
.python-version
.env.example
.gitignore
.dockerignore
Dockerfile
compose.yaml
alembic.ini
migrations/env.py
migrations/versions/0001_initial.py
app/__init__.py
app/config.py
app/db.py
app/models.py
app/schemas.py
app/security.py
app/policy.py
app/ownership.py
app/jobs.py
app/ai.py
app/whatsapp.py
app/messaging.py
app/worker.py
app/main.py
app/routes/__init__.py
app/routes/auth.py
app/routes/inbox.py
app/routes/webhooks.py
app/templates/login.html
app/templates/inbox.html
app/static/inbox.js
app/static/style.css
scripts/create_employee.py
tests/conftest.py
tests/test_config.py
tests/test_database.py
tests/test_security.py
tests/test_policy.py
tests/test_ownership.py
tests/test_webhooks.py
tests/test_ai.py
tests/test_messaging.py
tests/test_jobs.py
tests/test_inbox.py
tests/test_pipeline.py
tests/live/__init__.py
tests/live/test_huggingface.py
tests/live/test_whatsapp.py
docs/TEST_REPORT.md
docs/LIVE_CHECKLIST.md
```

Each Python directory gets its necessary `__init__.py`. Do not create empty implementation stubs and mark their tasks complete.

Do not add repository/service/factory/plugin layers around this structure unless a current acceptance test requires them and the user approves the change.

## Inputs needed before live connection

Record missing inputs as BLOCKED; continue independent tasks.

| Input | Supplied by | Handling |
| --- | --- | --- |
| Hugging Face token | Owner/developer | Fine-grained token permitted to call Inference Providers; local secret; never commit |
| Hugging Face model | Specification | Initial evaluation candidate `Qwen/Qwen2.5-7B-Instruct:cheapest`; availability/quality must be proven |
| WhatsApp Cloud API token, phone number ID, app secret | Meta account administrator | Local secrets; confirm this is the intended company number |
| Supported Graph API version for the actual Meta app | Developer from app configuration | Required exact value; no default, no guessed version |
| Webhook verification token | Generated locally | Random secret; configure the identical value in Meta |
| Employee login/password | Sole employee during setup | Interactive local creation; no seeded/default password |
| Public HTTPS origin and persistent cloud storage | Owner after host selection | Deployment gate; no cloud vendor chosen by Codex |
| Company profile/portfolio | Owner | Optional; do not invent URLs or delay unrelated features |
| Approved outage notice, Arabic and English | Owner | Ask before enabling customer-facing fallback copy; until then queue internally without a fabricated reply |

No cloud hosting or 24/7 availability is promised for zero money. Free Hugging Face capacity must pass real checks. If free allowance is exhausted or the candidate model is not suitable, Codex reports a blocker; it does not purchase credits or silently choose another provider/model.

This version has no WhatsApp template sending. Free-form bot and employee messages are blocked at or after 24 hours from the latest actual customer message.

## Intended commands after implementation

```bash
cp .env.example .env
docker compose build
docker compose up -d db
docker compose run --rm web uv run --frozen alembic upgrade head
docker compose run --rm web uv run --frozen python -m scripts.create_employee
docker compose up -d web worker
docker compose --profile test run --rm test
```

These are requirements for Codex to implement and validate, not commands already proven to work. Local UI can run while external integration settings are absent; its status must say integration disabled. Enabled integrations must reject incomplete configuration.

## Delivery gate

Deliver the pilot only after automated tests, live Hugging Face evaluation, real WhatsApp send/receive/status checks, employee browser checks, takeover race tests and database restart/persistence checks pass. Record failures, skipped checks, model ID, dependency lock, environment and evidence in `docs/TEST_REPORT.md`. Never call mocked results proof that external services work.

Backup/restore automation and restore testing are not part of the current delivery gate.
