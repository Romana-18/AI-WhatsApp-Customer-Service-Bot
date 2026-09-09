# Codex implementation tasks

Read `AGENTS.md`, `DECISIONS.md` and `COMPANY_RULES.md` first. Implement in order; do not select another technology, provider or paid fallback. All checkboxes intentionally start incomplete. Review every file changed in a task, then run its tests and record evidence before completing it.

## Phase 0 — reproducible empty project

### T01 — dependencies and containers

- [ ] Create `.python-version`, `pyproject.toml`, `uv.lock`, `.gitignore`, `.dockerignore`, `Dockerfile`, `compose.yaml`, `.env.example`, in that order.
- [ ] Use the exact stack in DECISIONS. Pull images and record actual digests; resolve dependency lock. If resolution fails, report exact incompatible pins and ask for a pin correction.
- [ ] Create Python package markers, `app/config.py`, `tests/conftest.py`, `tests/test_config.py`.
- [ ] Implement typed configuration, conditional external credentials, production HTTPS validation, separate test DB and test-only network blocking.
- [ ] Create `docs/TEST_REPORT.md` with sections for task evidence, automated tests, live tests, blockers and limitations. Never prefill a passing result.
- [ ] Verify the configured Hugging Face model is currently routable for this account using an explicitly authorized opt-in check. If the free allowance/model is unavailable, record BLOCKED; do not purchase credits or choose another model.

Acceptance tests:

1. Container builds from lock; `uv sync --frozen` does not alter lock.
2. Enabled provider with missing credential fails with redacted actionable error; disabled provider needs no fake key.
3. Production HTTP origin fails configuration; local loopback HTTP is accepted.
4. Test DB URL matching application DB URL is rejected.
5. Default tests cannot make outbound HTTP calls. No secrets or database data enter image/build context.
6. Hugging Face configuration uses `HF_TOKEN` and `HUGGINGFACE_MODEL`; no OpenRouter configuration remains.

Gate: image/lock proven or precise setup blocker recorded. Host selection is not required to finish this phase. A blocked live provider check does not justify fake responses.

## Phase 1 — persistent data and rules

### T02 — schema and migration

- [ ] Create `app/db.py`, `app/models.py`, `alembic.ini`, `migrations/env.py`, `migrations/versions/0001_initial.py`, `tests/test_database.py`.
- [ ] Implement all six tables and constraints from DECISIONS, including deterministic `jobs.enqueue_sequence`, async session lifecycle and migration connection. Use separate sessions per request/job.

Acceptance tests against PostgreSQL:

1. Empty DB upgrades to head; second upgrade is safe. Rollback and re-upgrade work on disposable test DB.
2. Duplicate `wa_id`, provider message ID and job inbound ID cannot create duplicate records.
3. Foreign keys reject orphan records; invalid states fail; only one running job per conversation.
4. Transaction rollback leaves neither an inbound message nor its job partially saved.
5. Container restart preserves conversation/history in the application volume. Test DB remains separate.
6. Jobs inserted for one conversation have deterministic increasing `enqueue_sequence` values.

### T03 — business policy and ownership

- [ ] Create `app/schemas.py`, `app/policy.py`, `app/ownership.py`, `tests/test_policy.py`, `tests/test_ownership.py`.
- [ ] Encode state/action checks, working-hours calculation, contact collection boundaries, narrow deterministic handoff precheck, advisory gate and version transitions. Business knowledge remains in COMPANY_RULES, not scattered constants.

Acceptance tests:

1. Cairo Saturday 10:00 open; Thursday 21:59 open; 22:00 closed; Friday closed. Test dates across DST transitions with aware datetimes.
2. Handoff queues before contact completion; refusal retains queue and stops questions; known phone is not requested again.
3. Takeover increases version; return increases it again; stale generated response stays invalid after both transitions.
4. Two separate DB connections demonstrate takeover/send serialization. No lock held during simulated AI wait.
5. Human state rejects every automated action. Waiting state rejects general company answers and allows only permitted collection/acknowledgement.
6. High-confidence explicit handoff text is classified deterministically; ambiguous wording is not falsely claimed as deterministic understanding.

Gate: real DB integration plus ownership tests pass before implementing live send paths.

## Phase 2 — authenticated employee access

### T04 — login and session security

- [ ] Create `app/security.py`, `scripts/create_employee.py`, `app/routes/auth.py`, `app/templates/login.html`, `tests/test_security.py`.
- [ ] Implement interactive sole-employee creation, hashing, opaque sessions, stable-per-session CSRF, expiration and login throttling. No default account, self-registration, roles or second employee.

Acceptance tests:

1. Correct password succeeds; wrong password fails with generic error; hash is never returned.
2. Duplicate/second employee creation is refused; secrets are absent from captured logs.
3. Missing, expired and revoked sessions reject protected requests.
4. Missing/wrong CSRF and cross-origin mutation are rejected; logout invalidates cookie and stored session.
5. Production cookie flags are correct; login throttle triggers after configured failures.
6. Opening/fetching a second authenticated tab does not rotate and invalidate the first tab's valid CSRF token.

## Phase 3 — real integration clients and durable jobs

### T05 — WhatsApp inbound and API client

- [ ] Create `app/whatsapp.py`, `app/routes/webhooks.py`, `tests/test_webhooks.py`.
- [ ] Implement verification challenge, constant-time HMAC verification of raw bytes, event normalization, transactional inbound/job storage, immediate explicit-handoff state transition, status callbacks and real text-send HTTP client.
- [ ] Unsupported media records metadata and queues human; never download attachments in this version.

Acceptance tests using signed synthetic fixtures:

1. Correct challenge succeeds; wrong token or signature fails; valid signature for modified body fails.
2. Duplicate delivery creates exactly one inbound/job. All messages in a batch are processed.
3. A batch containing one previously persisted duplicate and one new message still persists the new message/job.
4. An explicit high-confidence human/handoff request received while the conversation is `bot` atomically persists the inbound/job, changes state to `waiting`, increments version and makes the new job capture that waiting version.
5. If an older AI job had captured the prior version, the inbound handoff transition makes that older job stale immediately.
6. Delivery/read status callback updates outbound state without creating a job; late accepted/delivered callbacks do not regress read.
7. Malformed and oversized requests fail safely. DB failure returns retryable server error instead of acknowledging lost data.
8. Unsupported media queues human; outgoing/status echoes do not produce replies.
9. MockTransport checks actual Meta HTTP path, Bearer header and text payload; rejected/timeout outcomes are distinct from acceptance.

### T06 — Hugging Face AI and grounded responses

- [ ] Create `app/ai.py`, `tests/test_ai.py`, `tests/live/__init__.py`, `tests/live/test_huggingface.py`.
- [ ] Implement direct HTTP to Hugging Face Inference Providers, company/context assembly, strict JSON response validation, bounded repair/retry and structured handoff/contact output.
- [ ] Do not install a Hugging Face/OpenAI provider SDK. Never insert a sample reply when a call fails. No reasoning/provider internals are customer-visible.

Acceptance tests with test-only fixtures:

1. Correct Hugging Face router path, configured model and Bearer authorization are sent; company rules and chronological context are included.
2. Malformed JSON, wrong action, unknown fields and oversized output fail validation; repair cannot loop indefinitely.
3. 401/403 fail immediately; 429/5xx/timeout follow bounded retry schedule and end in visible failure/handoff.
4. Free-credit/quota exhaustion is reported as a provider limitation; code does not change model/provider or enable paid usage.
5. Context cap removes oldest messages without removing knowledge or newest customer question.
6. Human ownership suppresses AI work; stale result is discarded. Waiting cannot resume normal selling.
7. Price request triggers handoff; permitted 50% payment split is not rejected simply for containing numbers.
8. `contact_updates` are narrowly validated against customer conversation content without a generic evidence/provenance framework.

Live quality evaluation is performed in T10; mocked tests are not a substitute.

### T07 — worker and safe dispatch

- [ ] Create `app/jobs.py`, `app/messaging.py`, `app/worker.py`, `tests/test_jobs.py`, `tests/test_messaging.py`.
- [ ] Implement job claims, 90-second lease recovery, retry scheduling, central final-send gate, outbound intent, delivery status and shutdown handling.
- [ ] Do not build a periodic lease-refresh framework in this pilot.
- [ ] Route both employee and AI sends through the same gateway. Do not call the raw WhatsApp client directly from routes or AI code.

Acceptance tests:

1. Two customers process independently; two messages from one customer process by `enqueue_sequence` with one active job.
2. Worker restart recovers a leased job without duplicating a previously submitted message.
3. Takeover during slow generation prevents later dispatch; takeover immediately before send wins if committed first.
4. Explicit customer handoff arriving during an older slow AI generation invalidates that generation before it can dispatch.
5. Takeover then release does not make a pre-takeover AI output valid again.
6. Send already admitted causes takeover to wait; UI must not report completed takeover early.
7. Meta timeout/exception releases the advisory lock; a following takeover can acquire it.
8. Pending/sending intent followed by timeout/crash becomes `unknown` and is not automatically resent.
9. Repeated manual `client_request_id` returns original outcome; no second provider request.
10. Claim-token loss or changed conversation version blocks dispatch.
11. Free-form sending is allowed only while `now < latest_inbound_at + 24h`; at exactly 24h or later both bot and employee free-form sending are rejected. Receipts do not extend the window.
12. Provider acceptance displays `accepted`; only callback displays `delivered/read`.
13. Late status callbacks follow the transition rules and never regress confirmed delivery/read.
14. Exhausted AI retries queue human with visible error and no invented customer message.
15. If a job commits `waiting` then crashes before its handoff acknowledgement is safely persisted/submitted, the queue remains valid and the stale acknowledgement is not regenerated merely to pass the old version.

Gate: persistence, webhook, AI client and dispatch integration tests all pass.

## Phase 4 — usable Arabic inbox

### T08 — HTTP composition and inbox

- [ ] Create `app/routes/inbox.py`, `app/templates/inbox.html`, `app/static/inbox.js`, `app/static/style.css`, `app/main.py`, `tests/test_inbox.py`.
- [ ] Implement every endpoint in DECISIONS, dependency wiring, authenticated pages, pagination, poll refresh, queue filters, contact data, summary, delivery state and ownership controls.
- [ ] Arabic RTL UI, same business-number sending, no frontend build pipeline. Keep draft text when polling or an API call fails.

Acceptance tests:

1. Anonymous user cannot read messages, details or summaries, or mutate ownership.
2. Version conflict returns 409 and refreshes state without losing typed draft.
3. Manual composer is blocked until takeover; server enforces the same rule even if UI is bypassed.
4. Customer HTML/script and AI HTML render as text. Internal summary never enters outbound customer payload.
5. Pagination retrieves history without missing or duplicating rows at cursor boundaries.
6. Polling leaves scroll/draft stable; visible failures do not appear as sent bubbles.
7. Waiting state is visibly distinct from bot processing and employee ownership.
8. Manual browser check at desktop and phone width: Arabic text, mixed English, queue navigation, login/logout and takeover/release work.

## Phase 5 — whole-system proof and delivery

### T09 — automated pipeline and recovery

- [ ] Create `tests/test_pipeline.py`; use real PostgreSQL and mocked external HTTP only.
- [ ] Exercise signed inbound webhook → DB/job → worker → AI → dispatch → status callback → employee inbox.

Acceptance tests:

1. Ten synthetic customers submit concurrently: every inbound persists once, no cross-conversation context leaks, max AI concurrency remains two, all jobs reach a terminal state.
2. Pricing request queues human, collects missing details, employee takes over during collection, replies, then releases. No stale AI reply appears after release.
3. Explicit human request arrives while an earlier AI generation is running: the inbound transition invalidates the old generation and no old bot send starts afterward.
4. Duplicate webhook, mixed duplicate/new batch, provider outage, delayed callback and worker restart cause no silent loss or false delivery status.
5. A hostile prompt cannot change ownership/backend permissions or expose secrets. Evaluate model-specific factual resistance separately live.
6. Run `ruff check`, `ruff format --check` and full pytest suite through Compose test profile. Record actual counts, not an invented coverage percentage.

Backup/restore testing is intentionally not part of T09.

### T10 — real integration and owner acceptance

- [ ] Create `docs/LIVE_CHECKLIST.md` from the checks below. Keep missing setup inputs visible.
- [ ] With the user-provided Hugging Face token, run opt-in live tests. Explicit marker `live` is excluded by default; require `RUN_LIVE_TESTS=1`.
- [ ] Confirm the configured model uses only the currently available free allowance for this trial. If free allowance is exhausted/unavailable, record BLOCKED and stop the live model test; do not buy credits or switch model/provider.
- [ ] With designated test recipient and explicit live-run authorization, connect official WhatsApp callbacks and test actual sending/receiving.
- [ ] Record model ID, date, provider response evidence, redacted message IDs, latency, quota/free-credit errors and owner review. Do not publish real transcripts or phone numbers in git.

Live checks:

1. Egyptian Arabic service question and English service question: correct service facts and matching natural language.
2. Model returns consistently parseable structured JSON under the application prompt.
3. Price/discount request: no invented number; human queue. Payment question: approved methods and 50/50 split only.
4. Unknown warranty duration, company address, portfolio URL and exact delivery deadline: no invented facts; human handoff.
5. Explicit human/call/meeting, contract and invoice requests all queue without confirming an actual booking.
6. Follow-up uses prior context; one customer cannot see another's data.
7. Collection accepts missing details/refusal without trapping the customer. Employee takeover stops all AI collection.
8. Takeover during a real slow AI response suppresses stale bot output.
9. Real inbound message, bot reply, delivery callback, manual employee reply and return-to-bot all work on the same business number.
10. Safe controlled provider failure is shown truthfully; no fake success, paid usage or automatic model/provider switch.
11. Submit ten authorized test conversations where available. If real quota or available test numbers cannot support this, record the live concurrency target as unverified; do not label it passed from mocks.
12. The sole employee completes the Arabic inbox workflow without developer assistance. Customer-facing wording and factual outputs are reviewed by the owner.

Gate: zero observed failures in critical ownership, authentication, duplicate-send and business-rule checks. Failure blocks pilot release until fixed or a documented scope change is approved. Model changes require a new owner decision and repeating model-dependent live cases.

### T11 — selected-host deployment

- [ ] BLOCKED until owner selects hosting and supplies HTTPS origin/persistent storage. Do not select a provider or spend money automatically.
- [ ] Deploy the same locked images/configuration. Run migration once, provision the sole employee privately, configure the real webhook, verify cookies and public endpoint behavior.
- [ ] Repeat live smoke checks on the deployed origin. Document restart, integration-disable and key-rotation commands actually supported by the implementation.
- [ ] Complete TEST_REPORT with remaining limits, failed/skipped cases and actual deployment state. Never describe a local-only build as deployed.

Backup/restore automation is deferred beyond this implementation phase and is not a T11 gate unless the owner later changes that decision.

## Two-day work allocation

Day 1 target: T01–T07, provided dependencies and API setup are available. Day 2 target: T08–T10, fixes and T11 only if hosting is ready. If behind schedule, defer deployment or optional cosmetic work; do not omit authentication, durable messages, takeover safety or real verification. Contact/profile assets can be supplied later without fabricating them.
