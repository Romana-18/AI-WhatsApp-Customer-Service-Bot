# Locked implementation decisions

Specification date: 2026-09-09. These are implementation selections, not claims that the application has already passed tests.

## 1. Stack

| Component | Exact selection |
| --- | --- |
| Python | 3.12.14; base image `python:3.12.14-slim-bookworm` |
| PostgreSQL | 17.11; image `postgres:17.11-bookworm` |
| Dependency manager | uv 0.12.11; exact direct pins and committed `uv.lock` |
| HTTP application | fastapi 0.141.1; uvicorn 0.52.4 |
| Validation/settings | pydantic 2.13.5; pydantic-settings 2.15.0 |
| Database | SQLAlchemy 2.0.52; psycopg[binary] 3.3.5; alembic 1.19.2 |
| Outbound HTTP | httpx 0.28.1; no provider SDK |
| UI | Jinja2 3.1.6; plain browser JavaScript/CSS; no CDN assets |
| Password hashing | argon2-cffi 25.1.0 |
| Tests | pytest 9.1.1; pytest-asyncio 1.4.0; HTTPX MockTransport |
| Lint/format | ruff 0.16.6 |
| WhatsApp | Official Meta Cloud API; exact Graph version supplied from actual app before enabling |
| AI | Hugging Face Inference Providers chat completions over direct HTTP; initial evaluation model `Qwen/Qwen2.5-7B-Instruct:cheapest` |
| Hosting | Not selected; implement portable Docker Compose only |

No multipart dependency: login and inbox mutations use JSON. Install the project without a build backend (`tool.uv.package=false`). Use `uv run --frozen` in containers. Resolve transitive versions into the lock once, verify build and tests, then do not upgrade automatically. Direct package versions must be checked during Phase 0 for availability and joint compatibility. Record pulled image digests. If a tag or pin fails, stop that setup task and report the specific failure; do not substitute `latest`.

Docker Engine and Compose are host prerequisites, not application libraries. Require Compose v2 supporting profiles and health-check dependencies; record the actual host versions in the report. Do not replace a user's installed Docker version arbitrarily.

Why this stack: one Python application serves both API and small inbox, reducing deployment pieces. PostgreSQL provides durable messages and jobs and coordinates web/worker safely without Redis. Plain UI limits frontend work. No embedding pipeline is needed for this short knowledge file.

Hugging Face is an evaluation/initial provider, not a guarantee of free production capacity. The selected model was chosen as an initial candidate because it is instruction-tuned, supports Arabic, and is suitable for structured/JSON-style output. The `:cheapest` routing policy is intended to conserve the available free credit. Phase 0/T10 must verify that the model is actually routable for the account and that free allowance remains available. No automatic provider/model fallback and no paid usage. If evaluation or quota fails, record the blocker and obtain a new owner decision.

## 2. Processes and configuration

Compose services: `db`, `web`, `worker`; profile `test` adds isolated `test-db` and `test`. Web and worker share one image. One Uvicorn process and one worker process for the pilot. Worker allows at most two concurrent AI tasks, but only one active job per conversation. No process replication in this version.

Web binds `127.0.0.1:8000` locally. Database has no host port and uses a named persistent volume. Test database has a separate disposable volume; tests must reject a database URL equal to the application URL. Health checks are local process/DB checks, not proof that Meta/Hugging Face work. Worker records a heartbeat in logs; inbox shows oldest queued job and integration errors. Images run as a non-root user. No automatic schema migration on every worker/web start.

Required settings: `DATABASE_URL`, `APP_ENV` (`local` or `production`), `PUBLIC_BASE_URL`, `HUGGINGFACE_ENABLED`, `WHATSAPP_ENABLED`. Enabled integrations require `HF_TOKEN`, `HUGGINGFACE_MODEL`, or `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_GRAPH_VERSION`, respectively. `.env.example` contains blank secrets and the selected model ID, never plausible fake credentials. Production requires HTTPS origin. Disabled means no calls or sends and visible disabled status; it does not route to mocks.

Operational constants: worker poll 1 second; UI poll 3 seconds while visible; AI timeout 45 seconds, connect timeout 5 seconds; WhatsApp send total timeout 15 seconds; maximum inbound text 8,000 characters; outbound text 3,000 characters; maximum webhook body 1 MiB. Reject oversized bodies before parsing. Preserve a truncated marker and queue human for oversized customer text; do not silently feed incomplete requirements to AI.

## 3. Relational schema

Use UUID primary keys except conversation `id` as positive BIGINT identity (also advisory lock key). Timestamps use PostgreSQL TIMESTAMPTZ in UTC. Phone numbers are strings. Text uses TEXT, flags BOOLEAN, retry counts INTEGER. Use SQLAlchemy mappings, Alembic migrations, real foreign keys, check constraints for enumerations and lengths, and indexes for inbox/worker queries. No money column because no price catalog or payments exist.

| Table | Required columns and relationships |
| --- | --- |
| employees | id, unique username, password_hash, active, created_at; provisioning refuses a second employee in this pilot |
| sessions | id, employee_id FK, unique token_hash, csrf_token_hash, expires_at, created_at; store token hashes, never raw cookies |
| conversations | id, unique wa_id, contact_name nullable, business_field nullable, preferred_contact_time nullable TEXT, project_details nullable TEXT, alternative_phone nullable, state, version BIGINT default 0, assigned_employee_id nullable FK, handoff_reason nullable, summary nullable, collection_asked JSONB array, collection_stopped BOOLEAN, latest_inbound_at, created_at, updated_at |
| messages | id, conversation_id FK, unique provider_message_id nullable, direction, author, body nullable, media_type nullable, status, error_code nullable, client_request_id nullable unique, trigger_message_id nullable self-FK, created_at, provider_timestamp nullable; no raw full webhook dump |
| jobs | id, conversation_id FK, inbound_message_id unique FK, enqueue_sequence BIGINT generated identity unique, status, attempt_count, available_at, lease_until nullable, claim_token nullable UUID, captured_version nullable, last_error nullable, created_at, updated_at |

Enums: conversation state `bot`, `waiting`, `human`; message direction `inbound`/`outbound`; author `customer`/`bot`/`employee`/`system`; message status `received`, `pending`, `sending`, `accepted`, `delivered`, `read`, `failed`, `unknown`, `cancelled`; job status `queued`, `running`, `done`, `failed`, `cancelled`.

Unique partial index: at most one outbound bot message per non-null `trigger_message_id`; at most one running job per conversation. `enqueue_sequence` is the deterministic worker ordering key for jobs from the same conversation. Normal records are never silently deleted. No retention/deletion schedule selected: get an owner decision before enabling automatic deletion.

Backup/restore automation and restore testing are deferred from this implementation phase. Do not add them to the current delivery gate.

## 4. Ownership and dispatch contract

`bot`: ordinary grounded answers allowed. `waiting`: human request is visible immediately; AI may only acknowledge the handoff and collect missing information. `human`: all automation paused. Taking over assigns the sole employee. Return-to-bot increments version and sets `bot`; previous pending bot outputs stay cancelled. Never replay old customer messages automatically on return.

Every state change increments conversation `version`. A job captures the current version before generation. Check state/version before calling AI, after generation, and at final dispatch. This prevents an old reply from becoming valid after takeover then return-to-bot. Cancelling the HTTP generation is best effort; rejecting its stale result is mandatory.

### Immediate explicit handoff

During verified inbound processing, run a small deterministic high-confidence precheck for explicit handoff categories such as a direct request for a human/employee/call/meeting/pricing/detailed quotation/contract/invoice/company visit. It is intentionally narrow; ambiguous semantic requests remain for AI classification.

If the conversation is `bot` and the inbound text matches this precheck, the same transaction that persists the inbound message/job must:

1. transition `bot` to `waiting`;
2. increment `version`;
3. set the handoff reason;
4. make the queue visible immediately; and
5. make the new inbound job capture the resulting waiting version.

This immediately invalidates any older running AI job. If the conversation is already `waiting` or `human`, do not perform an extra ownership transition merely because another trigger phrase arrives.

While `waiting`, AI may acknowledge/collect one missing field per customer turn until takeover. Entering `waiting` never depends on completing collection.

### Model-initiated handoff

When a non-prechecked current job itself identifies a handoff, atomically compare its captured version, transition `bot` to `waiting`, increment the version, and associate its permitted acknowledgement with the new version. A failed comparison cancels the output. Do not refresh a stale job's version merely to make it pass. Inbound collection jobs capture the already-current waiting version.

If a worker crashes after the state transition commits but before a handoff acknowledgement is safely persisted/submitted, the `waiting` transition remains authoritative. Do not replay or regenerate the stale acknowledgement merely to make the old job pass. The inbox remains queued. If an outbound acknowledgement intent had already been persisted/submitted, normal outbound status/unknown recovery rules apply.

Return-to-bot cancels queued pre-release jobs; future inbound messages create new work.

### Final send gate

Use a PostgreSQL session advisory lock keyed by conversation id on a dedicated connection for ownership transitions and the final send gate. All senders and takeover routes use `ownership.py`; no bypass. Acquire the lock, re-read committed state/version, persist outbound intent with status `sending`, commit, call Meta with the bounded timeout while retaining the advisory lock, then persist the observed outcome and release in `finally`. Do not hold a transaction or lock during LLM generation. Close/discard the connection on lock errors. A pending takeover waits for an already-started send to finish; report takeover complete only after its state change commits.

Guarantee: a stale bot send cannot start after takeover has committed through this gate. A message already submitted to Meta can arrive later and cannot be recalled. Database/network failure can leave submission outcome unknown; show this truthfully rather than promise exactly-once delivery.

UI displays bot processing, waiting and employee ownership separately. Manual reply requires human state and matching employee. Takeover alone must not automatically send a customer message.

## 5. Durable inbound and outbound processing

Webhook verifies raw-byte HMAC with the app secret before trusting JSON. Persist every supported inbound event and its job in one transaction before returning 200. Duplicate provider IDs do not create new jobs. A batch containing both duplicate and new messages must still persist the new messages; duplicate handling must not roll back unrelated valid events. Iterate all entries/changes/messages, not just index zero. Status events update outbound rows and never create AI jobs. Do not echo outbound messages back into the bot.

Worker claims eligible jobs transactionally with `FOR UPDATE SKIP LOCKED`, excluding conversations with an active running job. Claim lease is 90 seconds. No periodic lease-refresh subsystem is required for this pilot because each claimed external operation is bounded below the lease; if the implementation later needs work that can legitimately exceed the lease, that requires a documented design change. Validate claim token before dispatch. Process a conversation's jobs by `enqueue_sequence`. Leases allow restart recovery; they are not permission to resend an existing outbound intent.

Hugging Face 429/5xx/timeout: up to three total attempts with persisted delays of 5 and 20 seconds, honoring a longer Retry-After up to 300 seconds. Authentication/authorization errors are not retried. A free-credit/quota exhaustion response is a visible provider limitation; do not silently buy credits, change provider or choose another model. After exhausted attempts, or invalid output after one repair attempt, queue human, store error, finish job as failed. Repair uses one of the three total attempts. Never wait/sleep while holding a database transaction. On failure in waiting state, stop collection and leave the queue visible.

WhatsApp: successful API response with message ID means `accepted`, not delivered. Definitive HTTP rejection means `failed`. Timeout, lost response or crash after send admission means `unknown`; do not automatically repeat the send. Recover abandoned `sending` rows as `unknown`. An employee sees the error and can investigate; no automatic resend endpoint in this pilot. Duplicate browser requests reuse `client_request_id` and return the original message outcome.

### Message status transitions

Inbound customer rows use `received`. Outbound transitions must follow these rules:

- `pending -> sending`
- `sending -> accepted | failed | unknown`
- `accepted -> delivered | read | failed`
- `delivered -> read`
- `read` never regresses
- `delivered` never regresses to `accepted`
- a late `accepted` callback must not overwrite `delivered` or `read`
- `failed` must not overwrite an already confirmed `delivered` or `read`
- `cancelled` is terminal and means provider submission did not start
- `unknown` is not permission to resend and must not be guessed into another state; change it only if an exact provider-linked event proves a later state

Status callbacks must correlate to the exact provider message identifier. Delivery receipts do not create AI jobs and do not extend the WhatsApp customer-service window.

## 6. AI request and output

Use `POST https://router.huggingface.co/v1/chat/completions` via HTTPX. Model comes from `HUGGINGFACE_MODEL`; initial evaluation value is `Qwen/Qwen2.5-7B-Instruct:cheapest`. Do not install the Hugging Face or OpenAI SDK. Temperature 0.2, maximum output tokens 1,000.

Use messages with a system instruction, the company rules, state, missing collection fields, and chronological context (last 20 messages, capped at 24,000 characters by dropping oldest complete messages). Never truncate the company rules. No external browsing, tools, embeddings, or autonomous API actions.

Ask for one JSON object and validate strictly with Pydantic; do not assume provider-side JSON schema support. Fields: `action` (`reply`, `handoff`, `collect`), `reply` (string max 3,000), `reason` (nullable enum: pricing, human_request, meeting, contract, invoice, visit, missing_information, unreliable_answer), `summary` (nullable string max 2,000), `contact_updates` (object of nullable strings matching contact fields), `asked_field` (nullable name of one collection field), `collection_declined` (boolean). Forbid unknown fields. Do not display raw JSON, hidden reasoning, provider errors or summaries to customers.

Validate action against state; no general `reply` in `waiting`, no AI output in `human`. Require reason for new handoff. Create queue/state before sending acknowledgement. Backend controls ownership and allowed actions; model cannot set human ownership, close a request, send payment links or confirm bookings. Contact updates must be narrowly validated against customer conversation content; do not build a generic provenance/evidence framework. Preserve existing values unless the customer corrects them. Store known sender phone without asking the LLM to invent it. Never send API keys or internal employee data to AI.

Collection asks at most once for each missing field; accept partially supplied information. When no missing unasked fields remain or the customer refuses, stop automated collection and retain waiting state. Prompt asks are generated naturally, not canned business replies. Deterministic explicit handoff phrases are handled before AI when high-confidence; ambiguous semantic requests still use model classification. Do not claim keyword checks understand every phrasing.

Price invention and prompt-injection resistance require live evaluations as well as tests. Do not reject all numbers: approved 50% payment split is valid. Invalid/unsafe output queues human rather than appearing as success. No paid fallback model, retry loop without a cap or fabricated answer on outage.

## 7. HTTP and employee inbox

| Endpoint | Contract |
| --- | --- |
| GET /health/live | Process status only, no secrets |
| GET /health/ready | DB readiness; 503 if DB unavailable; no provider-success claim |
| GET /webhooks/whatsapp | Validate configured verify token/mode; return challenge as plain text |
| POST /webhooks/whatsapp | Verified events; duplicate-safe persistence; invalid signature 401 |
| GET /login | Arabic login page |
| POST /auth/login | JSON username/password; creates session; returns CSRF token |
| POST /auth/logout | Requires session and CSRF; revokes session |
| GET /auth/session | Authenticated; returns current employee identity and current session CSRF token; Cache-Control: no-store |
| GET / | Authenticated RTL inbox |
| GET /api/conversations | Authenticated; state filter, limit 50, cursor pagination; no unbounded histories |
| GET /api/conversations/{id} | Details and integration status |
| GET /api/conversations/{id}/messages | Paginated chronological transcript, cursor, limit 50 |
| POST /api/conversations/{id}/takeover | Atomic ownership transition; expected_version required |
| POST /api/conversations/{id}/release | Human to bot; expected_version required |
| POST /api/conversations/{id}/messages | body, client_request_id UUID, expected_version; human ownership required |

Use 401 for missing/expired authentication, 403 for CSRF, 404 for missing records, 409 for stale version/ownership/window conflicts, 422 for invalid fields. JSON errors use `code` and `detail`; do not expose traces/secrets. Do not automatically retry a manual send with a new request ID.

Sessions: 256-bit random token, SHA-256 hash in DB, 12-hour absolute expiry, HttpOnly SameSite=Strict cookie, Secure in production. Create one strong CSRF token at login and keep it stable for that session until logout/expiry. Store only its hash server-side. CSRF token is required on every authenticated mutation with same-origin validation. Login validates Origin and content type; rate limit five failed attempts per minute per IP in this single web process; reset after success. Argon2id password hashing; interactive employee provisioning, minimum 12-character password. No public registration, password reset, role hierarchy, second employee, invitation or employee-management UI in pilot. Document limiter reset on process restart.

Do not enable permissive CORS. Use only a trusted configured proxy for client-IP/HTTPS forwarding; default to direct socket information locally.

Jinja autoescape on; JavaScript uses `textContent` for messages. No raw HTML rendering of model/customer content. UI has queues, transcript showing author and actual delivery state, contact details, internal summary, takeover/return buttons, composer disabled until takeover, and visible request failures. Poll while tab visible, preserve typed drafts and scroll position. Do not expose internal summary in WhatsApp payloads.

### WhatsApp customer-service window

For this MVP, free-form bot and employee messages are allowed only while the current time is strictly earlier than `latest_inbound_at + 24 hours`, where `latest_inbound_at` comes from the latest actual customer message. At the exact 24-hour expiry or later, block free-form sending and show the employee the reason. Customer inbound messages reopen/reset the 24-hour window. Delivery/read/status receipts do not extend it.

This MVP does not implement template messages. Therefore no free-form send is attempted outside the 24-hour customer-service window. The final send gate must re-check the window immediately before provider submission.

## 8. Testing boundaries

Unit tests mock only external boundaries or time. Integration tests use actual PostgreSQL and migrations plus HTTPX test transport for Meta/Hugging Face. No SQLite substitution. Default tests deny external HTTP. Live Hugging Face tests are opt-in and use the real token; WhatsApp live checks use an explicitly designated test number and real callbacks. Synthetic tests never enter the actual employee inbox.

Report automated, database integration, live model, live WhatsApp and manual browser results separately. Do not require identical LLM wording; evaluate factual correctness, action, language and valid structured output. Safety-critical tests (ownership, duplicate sends, authentication, price invention, handoff) must have zero observed failures before pilot release. Record live latency and quota/free-credit errors; passing ten mocked conversations does not prove ten concurrent real AI completions.

Backup/restore testing is deferred from this phase and must not be reported as a failed or skipped current acceptance requirement.
