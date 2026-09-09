# Codex execution instructions

Implement this repository from its specification. Do not assume the app structure already exists. Do not import the unrelated GivingChampion solution files.

## Authority

- `COMPANY_RULES.md`: company facts and customer behavior.
- `DECISIONS.md`: architecture, technology pins, data and API contracts.
- `task.md`: implementation order and acceptance tests.
- `README.md`: entry point and operation summary.
- If these files conflict, report the exact conflict and ask; do not silently reinterpret it.
- No new framework, provider, service, schema feature, paid AI usage or paid fallback without a documented user decision. A broken pin or exhausted free AI allowance is a blocker to report, not permission to choose another stack or spend money.

## Work method

1. Read all five files. Inspect the working repository before editing; preserve unrelated user work.
2. Work on the next incomplete task. Create its files in listed order. Small supporting functions may be added inside those files.
3. Review every changed file for contract correctness, error handling, secrets, and unfinished branches. Then run the task's tests; a file importing successfully is insufficient.
4. Fix failures before the next dependent task. If an external input is missing, document it and continue independent local tasks.
5. Record changed files, actual commands, pass/fail/blocked results and remaining issues in `docs/TEST_REPORT.md`. Mark task complete only with evidence.
6. At phase boundaries run the relevant integration tests. Run the complete automated suite before live testing.

## Keep the implementation simple

Implement the listed modules directly. Do not add repositories, unit-of-work wrappers, generic service layers, factories, event buses, CQRS/mediator frameworks, dependency-injection containers, plugin systems, Redis, Celery, Kafka, WebSockets, microservices, Kubernetes, LangChain, RAG, vector databases or new infrastructure unless a current acceptance test cannot reasonably be satisfied without it and the user approves the change.

- `ai.py` owns Hugging Face request/context/output validation. It never sends WhatsApp messages.
- `whatsapp.py` owns Meta protocol details. It never decides whether the bot is allowed to speak.
- `ownership.py` owns conversation state/version and advisory locking.
- `messaging.py` is the single outbound send gate for both bot and employee messages.
- Routes should not bypass these boundaries.
- One employee is a locked MVP scope decision. Do not add roles, employee management, invitations or multi-agent assignment.

## AI cost and provider rules

- AI provider for this pilot: Hugging Face Inference Providers through direct HTTP.
- Initial configured model candidate: `Qwen/Qwen2.5-7B-Instruct:cheapest`.
- The current development/trial phase must remain within available free Hugging Face usage/credits.
- Do not purchase credits, enable paid usage, silently select a paid fallback, or switch provider/model when quota is exhausted or the model fails evaluation.
- If free usage is unavailable, exhausted, or the selected model fails Arabic/JSON/business-rule evaluation, record the exact blocker and request a model/cost decision.
- Model availability and free allowance are external facts, not application guarantees.

## Truthful behavior

- Production code must call real external clients. No fake mode, fake successful HTTP responses, sample customers, seeded conversations or canned answers masquerading as AI.
- Test doubles belong only in `tests/`; fixtures must clearly be synthetic. Automated tests may deliberately simulate timeouts, failures and model outputs.
- Success logs require an observed successful operation. Sending, accepted, delivered, read, failed and unknown are different states.
- Missing keys, failed tests and skipped live checks must remain visible. Do not replace them with `print("all okay")`.
- Company answers come from the LLM grounded in `COMPANY_RULES.md`. UI labels and truthful operational errors can be static; they are not fabricated company answers. Do not claim an unavailable LLM generated a fallback.
- Never commit secrets, customer transcripts, access tokens or real phone numbers. Redact evidence.
- Never send a live test message without an explicitly designated test recipient and test-run authorization.

## Completion

No deployment claim until the selected real environment passes the live checklist. No passing-test claim without running the command. Do not mark a blocked task complete. Two-day timing must not override correctness of ownership, authentication, persistence or real sending. Backup/restore automation is explicitly deferred from this implementation phase and is not a current completion gate.
