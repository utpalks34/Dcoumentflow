# DocFlow: Technical Requirements Document (TRD)

| | |
|---|---|
| **Version** | 1.0 (draft) |
| **Date** | 2026-09-29 |
| **Implements** | `01_PRD` (every `TR-` row cites the `FR-` IDs it satisfies) |
| **Status** | Draft. Performance numbers are *initial targets* to be revised after the week-2 baselines. |

---

## 1. Scope and reference environment

- **In scope:** the API, worker pipeline, data model, model access, validation, confidence, routing, security, observability, evaluation tooling and test requirements.
- **Reference environment:** a laptop with 8+ GB RAM and no GPU, Docker, Python 3.11. Tier 1 and Tier 2 models are reached through hosted APIs or a local server; the fine-tuning stretch uses a free cloud GPU.
- **Terminology:** *Tier 1* = cheap first extraction; *Tier 2* = stronger, more expensive retry; *critical fields* = vendor_name, invoice_number, invoice_date, total.

## 2. System context

```
Email / upload -> n8n -> DocFlow API -> Postgres + Redis queue -> Worker
                                                   |                |-> OCR engine
                         signed webhooks <---------+                |-> Model gateway -> Tier 1 / Tier 2 models
                              |                                     '-> Traces/metrics (OpenTelemetry)
                              v
                 n8n -> CSV / Google Sheet / Telegram or Slack        Reviewer -> Review UI -> DocFlow API
```

## 3. Interface requirements

### 3.1 API

| ID | Requirement | Traces to |
|---|---|---|
| TR-API-01 | Versioned REST API under `/v1`. JSON everywhere except upload (multipart). OpenAPI generated from code and served at `/docs`. | FR-INT-01 |
| TR-API-02 | Authentication via `X-API-Key`. Keys are random (≥ 32 bytes), stored as SHA-256 hashes, shown once at creation. The key resolves to a `tenant_id`. | FR-SEC-01, FR-SEC-02 |
| TR-API-03 | Upload validation by **magic bytes**, not file extension. Allowed: PDF, JPEG, PNG. Max 10 MB, max 20 pages. Failures: 415 (type), 413 (size), 422 (pages or corrupt file). | FR-INT-03, FR-INT-05 |
| TR-API-04 | Idempotency: unique `(tenant_id, sha256)`. A duplicate returns **200** with the existing `document_id` and `"deduplicated": true`. A new document returns **202**. | FR-INT-02 |
| TR-API-05 | Error envelope for all 4xx/5xx: `{"error": {"code": "STRING_CODE", "message": "...", "request_id": "..."}}`. Codes are stable and documented. | all |
| TR-API-06 | Cursor pagination for list endpoints (`limit` ≤ 100, opaque `cursor`). | FR-REV-01 |
| TR-API-07 | Rate limit 60 requests/min per key; 429 with `Retry-After`. | FR-SEC-01 |
| TR-API-08 | `GET /healthz` (process up) and `GET /readyz` (Postgres, Redis reachable). | TR-REL-01 |

**Endpoints**

| Method and path | Purpose | Success | Notes |
|---|---|---|---|
| `POST /v1/documents` | Upload. Form fields: `file`, optional `callback_url`, `external_ref` (≤ 128 chars), `metadata` (JSON ≤ 2 KB) | 202 or 200 | Idempotent per TR-API-04 |
| `GET /v1/documents/{id}` | Status and result | 200 | While processing, `fields` is omitted |
| `GET /v1/review/queue` | NEEDS_REVIEW documents, oldest first | 200 | Filter `reason`, paginated |
| `POST /v1/documents/{id}/review` | `{"action": "approve" \| "correct" \| "reject", "corrections": [{"field", "value"}], "reviewer", "comment"}` | 200 | See TR-API-09 |
| `POST /v1/documents/{id}/export-ack` | n8n confirms a write: `{"destination", "external_id"}` | 200 | Sets EXPORTED; idempotent |
| `GET /v1/exports` | Rows for AUTO_ACCEPTED, APPROVED, CORRECTED; `format=csv\|json`, `since` | 200 | Read path for n8n and CSV |
| `GET /v1/metrics/summary` | Coverage, review rate, cost per doc, `window=24h` | 200 | Feeds dashboard |
| `DELETE /v1/documents/{id}` | Hard-delete blobs and rows; audit keeps an anonymized tombstone | 204 | FR-SEC-04 |

| ID | Requirement | Traces to |
|---|---|---|
| TR-API-09 | `review` with `correct`: values are normalized and validated by the same rules as extraction. If a blocking rule fails on the corrected data, the API returns 409 `VALIDATION_FAILED_ON_CORRECTION` with the failing rules unless the request sets `acknowledge_validation_failures: true`. Approving or correcting a document not in NEEDS_REVIEW returns 409. | FR-REV-03 |

### 3.2 Webhooks

| ID | Requirement | Traces to |
|---|---|---|
| TR-API-10 | Payload: `{"event": "document.status_changed", "delivery_id", "document_id", "status", "previous_status", "route": {"decision", "reason_code"}, "occurred_at"}`. | FR-EXP-03 |
| TR-API-11 | Headers `X-DocFlow-Timestamp` and `X-DocFlow-Signature: sha256=<HMAC-SHA256(secret, timestamp + "." + raw_body)>`. Receivers reject timestamps older than 5 minutes. | FR-EXP-03 |
| TR-API-12 | Delivery is at-least-once: retries with exponential backoff and jitter, 6 attempts over roughly 10 minutes, then a `webhook_dead_letters` row. `delivery_id` lets receivers de-duplicate. | FR-EXP-03 |
| TR-API-13 | `callback_url` host must be on a configured allow-list (SSRF protection); private and link-local IP ranges are refused after DNS resolution. | FR-SEC-01 |

## 4. Data requirements

| ID | Requirement | Traces to |
|---|---|---|
| TR-DAT-01 | PostgreSQL 15+ is the system of record. Schema managed by Alembic; migrations are forward-only. Every table except `tenants` carries `tenant_id`. | FR-SEC-02 |
| TR-DAT-02 | **No floating point for money anywhere.** DB type `NUMERIC(18,4)`, JSON as strings, Python `Decimal`. | FR-EXT-03 |
| TR-DAT-03 | Original files stored content-addressed (`blobs/<sha256>`) behind a storage interface: local disk in dev, S3-compatible optional. | FR-INT-01 |
| TR-DAT-04 | `audit_log` is append-only: no `UPDATE`/`DELETE` code path; the app DB role lacks those privileges on the table; a test proves it. | FR-AUD-01 |
| TR-DAT-05 | Retention: a scheduled job deletes originals and OCR text older than `RETENTION_DAYS` (default 30). Extractions and audit rows are retained in anonymized form. | FR-SEC-04 |
| TR-DAT-06 | Every extraction row stores `schema_version`; the API result includes it. | US-06 |

**Core tables (abridged DDL)**

```sql
CREATE TABLE tenants (id UUID PRIMARY KEY, name TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now());

CREATE TABLE api_keys (id UUID PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES tenants(id),
  key_hash BYTEA NOT NULL UNIQUE, label TEXT, revoked_at TIMESTAMPTZ);

CREATE TABLE documents (
  id TEXT PRIMARY KEY,                       -- doc_<ulid>
  tenant_id UUID NOT NULL, sha256 CHAR(64) NOT NULL, filename TEXT, mime TEXT, pages INT,
  source TEXT,                               -- email | api
  external_ref TEXT, callback_url TEXT,
  status TEXT NOT NULL,                      -- see state machine
  stage TEXT,                                -- current pipeline stage (informational)
  route_decision TEXT, route_reason TEXT,    -- reason code, see 8.3
  quality_score REAL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, sha256));

CREATE TABLE ocr_results (document_id TEXT REFERENCES documents(id), page INT, engine TEXT, engine_version TEXT,
  words JSONB NOT NULL,                      -- [{text, bbox, conf}]
  PRIMARY KEY (document_id, page));

CREATE TABLE extractions (
  id UUID PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id), tier SMALLINT NOT NULL,  -- 1 | 2
  attempt SMALLINT NOT NULL DEFAULT 1, schema_version TEXT NOT NULL,
  raw_output JSONB NOT NULL,                 -- strings as printed
  normalized JSONB,                          -- canonical values
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE (document_id, tier, attempt));

CREATE TABLE model_calls (
  id UUID PRIMARY KEY, extraction_id UUID REFERENCES extractions(id), provider TEXT, model TEXT, params JSONB,
  prompt_id TEXT, prompt_hash CHAR(64), input_hash CHAR(64), cache_hit BOOLEAN,
  tokens_in INT, tokens_out INT, cost_usd NUMERIC(12,6), latency_ms INT, error TEXT, created_at TIMESTAMPTZ DEFAULT now());

CREATE TABLE validations (extraction_id UUID REFERENCES extractions(id), rule_id TEXT, field TEXT,
  passed BOOLEAN NOT NULL, severity TEXT NOT NULL, detail JSONB);   -- severity: blocking | warning

CREATE TABLE field_scores (extraction_id UUID REFERENCES extractions(id), field TEXT, p_correct REAL NOT NULL,
  signals JSONB, PRIMARY KEY (extraction_id, field));

CREATE TABLE reviews (id UUID PRIMARY KEY, document_id TEXT REFERENCES documents(id), reviewer TEXT NOT NULL,
  action TEXT NOT NULL, comment TEXT, seconds_spent INT, created_at TIMESTAMPTZ DEFAULT now());

CREATE TABLE corrections (id UUID PRIMARY KEY, review_id UUID REFERENCES reviews(id), document_id TEXT, field TEXT NOT NULL,
  model_value TEXT, human_value TEXT, created_at TIMESTAMPTZ DEFAULT now());

CREATE TABLE audit_log (id BIGSERIAL PRIMARY KEY, tenant_id UUID NOT NULL, document_id TEXT, ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  event TEXT NOT NULL, actor TEXT NOT NULL,   -- system | reviewer:<name> | api
  payload JSONB);                             -- includes versions block

CREATE TABLE webhook_dead_letters (id UUID PRIMARY KEY, document_id TEXT, url TEXT, payload JSONB, attempts INT, last_error TEXT, ts TIMESTAMPTZ DEFAULT now());
```

### 4.1 State machine

`status` holds only externally meaningful states. Pipeline steps are recorded as `stage` events in `audit_log`.

| From | To | Trigger |
|---|---|---|
| (none) | RECEIVED | Upload accepted |
| RECEIVED | PROCESSING | Worker picks up the job |
| PROCESSING | REJECTED_UNREADABLE | Quality score below `Q_MIN` |
| PROCESSING | AUTO_ACCEPTED | Router decision |
| PROCESSING | NEEDS_REVIEW | Router decision, or degradation (TR-REL-02) |
| PROCESSING | FLAGGED_DUPLICATE | Duplicate rule R-DUP-01 fires |
| PROCESSING | FAILED | Unrecoverable error after retries or requeue limit |
| NEEDS_REVIEW, FLAGGED_DUPLICATE | APPROVED / CORRECTED / REJECTED | Reviewer action |
| AUTO_ACCEPTED, APPROVED, CORRECTED | EXPORTED | `export-ack` |
| FAILED | RECEIVED | Manual requeue by operator |

Any other transition is rejected in code and tested (TR-TEST-01).

## 5. Pipeline requirements

| ID | Requirement | Traces to |
|---|---|---|
| TR-PIPE-01 | The queue is **at-least-once**. Each stage writes its result keyed by `(document_id, stage, attempt)` and the worker skips stages already completed, so a redelivered job resumes rather than repeats (and never double-bills a model call). | TR-REL-01 |
| TR-PIPE-02 | A per-document **advisory lock** ensures one worker processes a document at a time. | TR-REL-01 |
| TR-PIPE-03 | Stage contracts are as in the table below. Timeouts are configurable. | FR-EXT-01 |
| TR-PIPE-04 | Hard caps per document: at most 2 extraction calls (Tier 1, Tier 2) plus 1 repair retry each, and a `MAX_COST_PER_DOC_USD` cap. Exceeding either routes to NEEDS_REVIEW with reason `COST_CAP_EXCEEDED`. | FR-RTE-03 |
| TR-PIPE-05 | **Preprocessing:** render PDFs at 200 DPI; correct orientation (EXIF or OCR orientation detection); deskew; downscale so the long edge ≤ 2000 px. **Quality score** in [0,1] = weighted blend of normalized sharpness (variance of the Laplacian), resolution and contrast. Documents below `Q_MIN` are REJECTED_UNREADABLE. | FR-INT-04 |
| TR-PIPE-06 | **Page selection for model input:** ≤ 5 pages are sent whole. For 6 to 20 pages, send page 1, the last page, and any page whose OCR text matches `total\|amount due\|subtotal\|balance` (capped at 5). | FR-INT-05 |
| TR-PIPE-07 | **Normalization** is deterministic code after the model call (dates, amounts, currency, whitespace). A field that cannot be normalized becomes `null` with flag `NORMALIZATION_FAILED`. Normalization has property-based tests. | FR-EXT-03 |

| Stage | Input | Output | Timeout | Retries | On failure |
|---|---|---|---|---|---|
| preprocess | file bytes | page images, quality score | 30 s | 0 | FAILED, or REJECTED_UNREADABLE |
| parse (OCR) | page images | words with boxes, per page | 60 s | 1 | Continue **without OCR**; grounding fails, so routing falls to review (`OCR_UNAVAILABLE`) |
| extract | images and/or OCR text | raw JSON per schema | 60 s per call | 2 on 429/5xx/timeout with backoff and jitter; 1 repair retry on schema failure | Tier 1: escalate. Tier 2: NEEDS_REVIEW |
| normalize | raw JSON | canonical values | 5 s | 0 | Field null plus flag |
| validate | canonical values, OCR | rule results | 5 s | 0 | (deterministic; a crash is FAILED) |
| score | signals | per-field probabilities | 5 s | 0 | Fall back to conservative rules (review) |
| route | probabilities, rules | decision, reason code | 1 s | 0 | (deterministic) |

## 6. Model access requirements

| ID | Requirement | Traces to |
|---|---|---|
| TR-MOD-01 | All model calls go through a gateway (LiteLLM) using aliases `tier1` and `tier2`, mapped in `config/docflow.yaml`. Changing a model is a config change. | FR-EXT-05 |
| TR-MOD-02 | Structured output is enforced (provider JSON-schema mode or tool calling), `temperature = 0`, `max_tokens` capped. Output is parsed with Pydantic; one repair retry with the validation errors (prompt PR-03). | FR-EXT-01 |
| TR-MOD-03 | **Response cache with record/replay.** Key = SHA-256 of (model, params, prompt hash, input hash). Modes: `live`, `record`, `replay`. CI runs `replay` only; a cache miss fails the test. | FR-EVAL-03 |
| TR-MOD-04 | Cost = tokens × versioned price table (`config/pricing.yaml`, with `effective_date`). **Verify prices against the provider before each milestone run**; they change. Stored per call. | SM-06 |
| TR-MOD-05 | Exact model version strings are pinned in config and written into the `versions` block of every result. | US-08 |
| TR-MOD-06 | **Tier 2 independence:** Tier 2 does not receive Tier 1's values, so cross-model agreement is a valid signal. Tier 2 may receive *rule-failure hints* without values (prompt PR-02). | FR-CNF-01 |
| TR-MOD-07 | Model selection criteria: supports schema-constrained output; Tier 1 is the cheapest model that clears your DEV accuracy bar; Tier 2 must be vision-capable. Selection is recorded as an ADR with the DEV numbers. | FR-EVAL-04 |
| TR-MOD-08 | **Data-egress rule:** only synthetic, public or explicitly permitted documents go to third-party hosted models. Real private documents require a locally hosted model. The gateway config has an `allow_hosted_for` list per dataset tag. | PRD §9 |

## 7. Validation requirements

Rules run on normalized values. Tolerances live in config (`abs_tol = 0.02`, `rel_tol = 0.001`).

| Rule ID | Definition | Fields | Severity |
|---|---|---|---|
| R-REQ-01 | All critical fields present and non-empty | vendor_name, invoice_number, invoice_date, total | blocking |
| R-SUM-01 | Sum of line `amount` = `subtotal` within tolerance (skipped if either is absent) | line_items, subtotal | blocking |
| R-SUM-02 | `subtotal + tax_total` = `total` within tolerance (`tax_total` absent counts as 0 only if subtotal = total) | subtotal, tax_total, total | blocking |
| R-LINE-01 | `qty × unit_price` = `amount` within tolerance | line_items | warning (discounts and rounding are legitimate) |
| R-DATE-01 | Date parses and lies in [2000-01-01, today + 7 days] | invoice_date | blocking |
| R-CUR-01 | Currency is in the allowed ISO 4217 list, or null | currency | warning |
| R-RANGE-01 | `0 < total < MAX_TOTAL` (config, default 1e9) | total | blocking |
| R-GRD-01 | **Grounding:** each critical value is findable in OCR text. Amounts: numeric equality with an OCR numeric token. Dates: equality with a parsed OCR date token. Strings: normalized token-set similarity ≥ 0.9. | critical fields | blocking for critical fields, warning otherwise |
| R-DUP-01 | Same `(normalized vendor, invoice_number, total)` already exists for the tenant | multiple | blocking (routes to FLAGGED_DUPLICATE) |

| ID | Requirement | Traces to |
|---|---|---|
| TR-VAL-01 | A **blocking** failure prevents AUTO_ACCEPT. A **warning** becomes a feature for the confidence model. | FR-VAL-01..03 |
| TR-VAL-02 | Every rule result is persisted (`validations`) and returned in the API with `rule_id`, `field`, `passed`, `severity`. | FR-VAL-05 |
| TR-VAL-03 | Each rule has unit tests for: pass, fail, edge of tolerance, missing input. | TR-TEST-01 |

## 8. Confidence and routing requirements

### 8.1 Confidence

| ID | Requirement | Traces to |
|---|---|---|
| TR-CNF-01 | **Features per field:** `validation_ok` (no blocking rule involving the field failed), `grounded`, `agreement` (Tier 1 = Tier 2 after normalization; with `agreement_available`), `logprob_mean` (nullable, with missing flag), `image_quality`, `ocr_conf_matched`, field-type one-hot. | FR-CNF-01 |
| TR-CNF-02 | **Model:** logistic regression predicting P(field correct), followed by isotonic (or Platt) calibration. Trained on DEV only; evaluated **out-of-fold** on DEV, then once on TEST. Prefer monotone, few-parameter models; DEV is small. | FR-CNF-01 |
| TR-CNF-03 | Document confidence = **min** over critical fields' probabilities. | FR-CNF-02 |
| TR-CNF-04 | Report ECE (15 equal-mass bins) and a reliability diagram per field type, with the bin counts shown. | SM-05 |
| TR-CNF-05 | The model's own verbalized confidence is **never** used as a feature. | ADR-002 |

### 8.2 Routing

| ID | Requirement | Traces to |
|---|---|---|
| TR-RTE-01 | Decision table below is implemented as a pure function and fully unit-tested. | FR-RTE-01 |
| TR-RTE-02 | **Threshold artifact** `config/thresholds/t_<YYYY_MM>.json` records: `t_auto`, `q_min`, target precision, DEV manifest hash, selection method, date, git SHA. `t_auto` = the lowest threshold whose out-of-fold DEV precision meets the target. Coverage is an outcome, not an input. | FR-RTE-02 |
| TR-RTE-03 | Changing thresholds requires a fresh DEV eval, a new artifact, and a `CHANGELOG` entry. | US-08 |

| Situation | Decision |
|---|---|
| Quality score < `q_min` | REJECT_UNREADABLE |
| Tier 1: no blocking failures and doc confidence ≥ `t_auto` | AUTO_ACCEPT |
| Tier 1: otherwise, Tier 2 available and cost cap not hit | ESCALATE (run Tier 2, then re-validate, re-score) |
| Tier 2: no blocking failures and doc confidence ≥ `t_auto` | AUTO_ACCEPT (Tier 2 result) |
| Tier 2 unavailable, cost cap hit, schema invalid after repair, or still below threshold | HUMAN_REVIEW with the best result and reasons |
| R-DUP-01 fires | FLAGGED_DUPLICATE |

### 8.3 Reason codes

Format `CODE` or `CODE:param`. Stored in `documents.route_reason` and the webhook.

| Code | Meaning |
|---|---|
| `AUTO_OK` | All checks passed; confidence above threshold |
| `LOW_CONF:<field>` | Field probability below threshold |
| `RULE_FAIL:<rule_id>` | A blocking rule failed |
| `UNGROUNDED:<field>` | Value not found in OCR text |
| `TIER_DISAGREE:<field>` | Tier 1 and Tier 2 differ on a critical field |
| `SCHEMA_INVALID` | Model output invalid after one repair |
| `TIER2_UNAVAILABLE` | Escalation impossible (outage, breaker open) |
| `COST_CAP_EXCEEDED` | Per-document cost cap hit |
| `OCR_UNAVAILABLE` | OCR failed; grounding impossible |
| `LOW_IMAGE_QUALITY` | Below `q_min` |
| `POSSIBLE_DUPLICATE` | R-DUP-01 |

## 9. Performance and reliability requirements

| ID | Requirement (initial target) | Traces to |
|---|---|---|
| TR-PERF-01 | Tier 1 path p95 ≤ 20 s for a single-page document, excluding queue wait | FR-INT-01 |
| TR-PERF-02 | Escalation path p95 ≤ 60 s | FR-RTE-01 |
| TR-PERF-03 | Sustained ≥ 10 documents/min with 2 workers on the reference laptop, with hosted-API models | SM-09 |
| TR-PERF-04 | API: `GET` p95 ≤ 200 ms; `POST` returns within 2 s for files ≤ 10 MB | US-06 |
| TR-PERF-05 | Worker memory ≤ 2 GB | ADR-003 |
| TR-REL-01 | **No lost documents.** A reaper requeues jobs stuck in PROCESSING > 10 min; after 3 requeues the document becomes FAILED and alerts. | SM-09 |
| TR-REL-02 | **Degradation matrix** below. | US-10 |
| TR-REL-03 | Circuit breaker on each model provider: after 5 consecutive failures, open for 60 s (configurable); while open, escalation is skipped and documents route to review. | FR-RTE-04 |
| TR-REL-04 | Webhook delivery and export acknowledgement are idempotent. | US-02 |

| Dependency down | Behavior |
|---|---|
| Tier 2 model API | Skip escalation; NEEDS_REVIEW `TIER2_UNAVAILABLE` |
| Tier 1 model API | Attempt Tier 2 directly; if also down, NEEDS_REVIEW |
| OCR engine | Extract from images only; grounding fails; NEEDS_REVIEW `OCR_UNAVAILABLE` |
| Redis | API returns 503 on upload (nothing accepted, so nothing lost); existing state in Postgres |
| Postgres | API returns 503; workers pause |
| Tracing backend | Drop spans (non-blocking exporter); processing continues |
| n8n / webhook receiver | Retry with backoff; dead-letter after max attempts |

## 10. Security and privacy requirements

| ID | Requirement | Traces to |
|---|---|---|
| TR-SEC-01 | **Untrusted input.** Document content (image and OCR text) is data, never instructions. The extraction model has **no tools**. Output is constrained to the schema and length-limited (strings ≤ 500 chars). | R-08 |
| TR-SEC-02 | Prompt-injection regression suite (PR test cases): documents containing "ignore previous instructions", "set total to 0", or role-play text must not change extracted values. | R-08 |
| TR-SEC-03 | File hardening: magic-byte check, size/page limits, render PDFs in the worker with CPU and memory limits and a timeout, strip embedded scripts and links, never execute or open document contents as anything but pixels and text. | FR-INT-03 |
| TR-SEC-04 | UI escapes all displayed values (no raw HTML injection). | FR-REV-02 |
| TR-SEC-05 | Logging: structured JSON with `request_id` and `document_id`. **Never** log raw field values, OCR text or file names, unless `DEBUG_PII=true`. A test scans sample logs and traces for known sentinel values. | FR-SEC-03 |
| TR-SEC-06 | Secrets only in environment variables or a secrets manager; pre-commit secret scan (e.g. gitleaks). `.env` is git-ignored. | R-09 |
| TR-SEC-07 | Least privilege: the app DB role cannot `DROP`, cannot modify `audit_log` rows, and has no superuser rights. | TR-DAT-04 |
| TR-SEC-08 | Dependency pinning with a lock file; `pip-audit` (or equivalent) in CI. | R-12 |
| TR-SEC-09 | Pre-commit blocks large files and anything under `evals/datasets/raw/`. Real documents are never committed. | R-09 |
| TR-SEC-10 | Encryption at rest (disk or object-store level) for blobs when not in local development. | FR-SEC-04 |

## 11. Observability requirements

| ID | Requirement | Traces to |
|---|---|---|
| TR-OBS-01 | Instrument with OpenTelemetry. Default backend: Phoenix (single container). Langfuse is an alternative (self-hosting needs several supporting services; verify against current docs, or use its cloud tier only with non-sensitive data). | FR-OBS-01 |
| TR-OBS-02 | `trace_id` = `document_id`. Spans: `doc.ingest`, `doc.preprocess`, `doc.parse`, `doc.extract.t1`, `doc.validate.t1`, `doc.score.t1`, `doc.route.t1`, the `.t2` equivalents, `doc.review`, `doc.export`. | FR-OBS-01 |
| TR-OBS-03 | Root-span attributes: `git_sha`, `prompt_id`, `prompt_hash`, `model_t1`, `model_t2`, `thresholds_version`, `schema_version`. | US-08 |
| TR-OBS-04 | Per model-call attributes: model, tokens in/out, cost, latency, cache_hit, output hash (not the output). | SM-06 |
| TR-OBS-05 | **Metrics** (Prometheus style): `docflow_documents_total{status}`, `docflow_stage_duration_seconds{stage}`, `docflow_model_cost_usd_total{tier,model}`, `docflow_schema_failures_total{tier}`, `docflow_route_decisions_total{decision}`, `docflow_review_queue_age_seconds`, `docflow_field_corrections_total{field}`, `docflow_field_confidence{field}` (histogram), `docflow_validation_failures_total{rule}`. | FR-OBS-02 |
| TR-OBS-06 | **Alert rules** (each with a fault-injection test): schema failures > 2% in 1 h; escalation rate > 2× its 7-day baseline; correction rate for any field > baseline + 10 points; cost per doc over budget; review queue age over SLA; stuck jobs. | FR-OBS-03 |

## 12. Evaluation requirements

| ID | Requirement | Traces to |
|---|---|---|
| TR-EVAL-01 | **Dataset manifest** (JSONL), one row per document: `doc_id, path, sha256, split, tags[], source (public\|real\|synthetic), labels{}, label_source (hand\|model_assisted\|generator\|dataset), labeler, labeled_at`. The manifest file hash is recorded on every run. | FR-EVAL-02 |
| TR-EVAL-02 | Splits: DEV-clean (~60), DEV-hard (~40), TEST-clean (~150), TEST-hard (~60), optional TEST-syn (~300). Public datasets label only some fields; **evaluate only fields a dataset labels**. | FR-EVAL-01 |
| TR-EVAL-03 | **Test protection.** TEST manifests and labels are read-only in the repo; `run_eval` refuses TEST splits without `--allow-test`, and each such run appends (date, git SHA, system, dataset hash, headline metrics) to `TEST_RUNS.md` automatically. CI fails if a TEST manifest hash changes. TEST documents never appear in prompts, few-shot examples, calibration or fine-tuning data. | FR-EVAL-02 |
| TR-EVAL-04 | `run_eval --system <A\|B\|C\|cascade> --split <name> --out runs/<ts>.json` outputs metrics, per-document predictions and per-field diffs, plus run metadata (git SHA, prompt hashes, model versions, thresholds version, manifest hash). Seeds fixed. | FR-EVAL-01 |
| TR-EVAL-05 | **Metrics implemented** (definitions in the blueprint §6.2): field exact match, header-field micro-F1, line-item F1 (Hungarian assignment on description similarity), doc-level critical-correct, auto-accept coverage and precision, risk-coverage curve and AURC, ECE, cost per document, latency p50/p95, cost-weighted score. | FR-EVAL-01 |
| TR-EVAL-06 | **Intervals.** 95% bootstrap (≥ 10,000 resamples, resampling *documents*) for accuracy and F1; Wilson or Clopper-Pearson for proportions such as precision; **paired** bootstrap when comparing two systems on the same documents. Reports never show a point estimate alone. | FR-EVAL-05 |
| TR-EVAL-07 | **Sufficiency check.** Reports include the number of auto-accepted documents and the resulting upper bound on error rate if zero errors were observed (≈ 3 / N). | SM-03 |
| TR-EVAL-08 | **CI gate.** On every PR: unit tests; replayed eval on a 30-document DEV subset. Fail if schema-valid rate < 100%, if header-field micro-F1 (≈ 200 fields) drops more than 2 points versus `evals/baselines/main.json`, or if any replay cache miss occurs. Changes to prompts, models or thresholds require a local live eval and committed cache entries. | FR-EVAL-03 |
| TR-EVAL-09 | Scripts generate the Pareto plot (cost per doc vs header F1 with interval bars) and the risk-coverage curve as PNGs for the README. | FR-EVAL-06 |
| TR-EVAL-10 | Error analysis tooling: a script tags failures with the taxonomy (OCR miss, wrong field, hallucination, format/locale, layout, line-item merge/split, multi-page carry), produces counts, and writes `FAILURES.md` sections. | RG-03 |
| TR-EVAL-11 | LLM-as-judge is **not** used for any reported accuracy metric. | ADR-002 |

## 13. Environment and tooling requirements

| ID | Requirement |
|---|---|
| TR-ENV-01 | Python 3.11; dependency management with `uv` or Poetry and a lock file; `ruff` (lint and format), `mypy --strict` on `validators/`, `router/`, `normalize/`, `evals/`; `pytest`. |
| TR-ENV-02 | `docker-compose.yml` runs: `api`, `worker`, `postgres`, `redis`, `phoenix`, `n8n`, `review-ui`. One command (`make up`) starts everything; `make down` stops it. |
| TR-ENV-03 | Make targets: `up`, `down`, `test`, `lint`, `eval-dev`, `eval-ci`, `eval-test` (guarded), `migrate`, `seed-demo`, `report`. |
| TR-ENV-04 | Pre-commit: ruff, mypy (core), secret scan, large-file block, dataset-path block. |
| TR-ENV-05 | CI (GitHub Actions): lint, type-check, unit tests, integration tests with a fake gateway, replayed eval gate, `pip-audit`. No secrets and no live model calls in CI. |
| TR-ENV-06 | Configuration in `config/docflow.yaml` (models, timeouts, caps, tolerances, critical fields) with environment overrides; secrets in env. |

## 14. Testing requirements

| ID | Requirement |
|---|---|
| TR-TEST-01 | **Unit:** validators (pass, fail, tolerance edge, missing input), normalization, metrics, router decision table, state-machine transitions, HMAC signing and verification. |
| TR-TEST-02 | **Property-based** (Hypothesis): amount and date normalization across locale formats never produce a float, never change value semantics, and round-trip. |
| TR-TEST-03 | **Integration:** API + Postgres + worker + fake model gateway. Cover idempotent upload, escalation once, degradation matrix rows, checkpoint resume after a killed worker, audit-log immutability, cross-tenant isolation. |
| TR-TEST-04 | **Contract:** webhook payload schema and signature; API response schema against OpenAPI. |
| TR-TEST-05 | **Security:** prompt-injection suite (TR-SEC-02), log-scan for sentinel values (TR-SEC-05), SSRF allow-list, upload magic-byte spoofing. |
| TR-TEST-06 | **End to end** (scripted, docker compose): email with attachment → n8n → DocFlow → review → export acknowledgement, including duplicate, unreadable and provider-down paths. |
| TR-TEST-07 | **Soak / smoke:** 200 documents with random worker kills; verify zero lost documents (SM-09). |
| TR-TEST-08 | Coverage ≥ 80% on `validators`, `normalize`, `router`, `evals/metrics` (Should). |

## 15. Requirements traceability (summary)

| PRD area | TRD sections |
|---|---|
| Intake (FR-INT) | 3.1, 5 (TR-PIPE-05/06), 10 (TR-SEC-03) |
| Extraction (FR-EXT) | 5, 6, TR-PIPE-07 |
| Validation (FR-VAL) | 7 |
| Confidence and routing (FR-CNF, FR-RTE) | 8, TR-PIPE-04, TR-REL-02/03 |
| Review (FR-REV) | TR-API-09, 3.1 |
| Export and integration (FR-EXP) | 3.1, 3.2 |
| Audit, observability, security | 4, 10, 11 |
| Evaluation (FR-EVAL) | 12, 13, 14 |
