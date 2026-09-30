# DocFlow: Product Requirements Document (PRD)

| | |
|---|---|
| **Version** | 1.0 (draft) |
| **Date** | 2026-09-29 |
| **Owner** | You (solo project, mentor-reviewed) |
| **Status** | Draft for self-review |
| **Companion docs** | 02 TRD, 03 Design Requirements, 04 Architecture, 05 Phase Plan, 06 LLM Instructions |

> This is a portfolio project, so the "customers" are simulated. The PRD is still written as if for a real product, because that discipline (requirements with acceptance criteria, traceable to tests) is part of what the project demonstrates.

---

## 0. How this document set works

| # | Document | Answers | ID prefix |
|---|---|---|---|
| 01 | PRD (this file) | What are we building, for whom, and how do we know it worked? | `US-` `FR-` `R-` `Q-` `RG-` |
| 02 | TRD | What must the system technically do, and how well? | `TR-` |
| 03 | Design Requirements | What do screens, messages and API conventions look like? | `DR-` |
| 04 | Architecture | How is it structured, and why these choices? | `ADR-` |
| 05 | Phase Plan | In what order, with what exit criteria? | `P#-T#` |
| 06 | LLM Instructions | How do the model prompts behave, and how should coding assistants work in this repo? | `PR-` `AI-` |

**Rules**

1. Every requirement has an ID. Commits and PRs cite the IDs they implement (`FR-VAL-01`, `TR-PIPE-02`).
2. If documents conflict: the PRD wins on *what*, the TRD on *how well*, the Architecture on *how it is built*. Fix the conflict in the same PR that finds it.
3. Priorities use MoSCoW: **M**ust, **S**hould, **C**ould, **W**on't (this release).
4. Every number in this set is a **target or hypothesis** until a logged test run says otherwise.

---

## 1. Background and problem

Small businesses and finance teams receive invoices as PDFs, phone photos and email attachments. Someone retypes vendor, date, total, tax and line items into a spreadsheet or accounting tool. It is slow and error-prone.

The obvious fix (send the image to a vision-language model) fails **silently**: it returns a well-formatted, confident, wrong total. In finance, a silent wrong number is worse than a slow correct one. Naive automation has no answer to "which of these results can I trust?"

## 2. Product vision and thesis

**Vision.** Turn invoice photos and PDFs into validated, structured data. Auto-approve what the system is sure about, escalate what it is not, and prove every claim on a frozen test set.

**Thesis.** DocFlow is not "an extractor". It is a system that **knows when it might be wrong**. Calibrated confidence plus safe routing is the product. Raw accuracy is an input to that, not the goal.

## 3. Goals and non-goals

### Goals
- **G1.** Extract typed invoice data (header fields and line items) with a per-field confidence and visual evidence.
- **G2.** Route every document to AUTO-ACCEPT, ESCALATE (stronger model, once) or HUMAN REVIEW, using validation rules and calibrated confidence.
- **G3.** Keep silent errors among auto-accepted documents measurably low, and *quantify* how low, with confidence intervals.
- **G4.** Minimize cost per document via a model cascade, with a cost-accuracy Pareto analysis.
- **G5.** Make every result reproducible and auditable (versions, traces, corrections).
- **G6.** Ship an evaluation harness, frozen test sets and CI regression gate as first-class deliverables.

### Non-goals (this release)
- Handwriting-heavy documents, non-Latin scripts, multi-language layouts.
- Direct accounting-software integrations (CSV and Google Sheets only).
- Billing, user management, roles, SSO, multi-tenant self-service.
- Currency conversion, tax-compliance logic, payment execution.
- Real-time streaming, Kubernetes, horizontal autoscaling.

## 4. Success metrics (targets, not promises)

| ID | Metric | Target | Measured on | Notes |
|---|---|---|---|---|
| SM-01 | Header-field F1 | ≥ 0.95 | TEST-clean | Below this, suspect a pipeline bug before blaming models |
| SM-02 | Header-field F1 | report; aim ≥ 0.85 | TEST-hard | Where systems separate |
| SM-03 | Auto-accept precision (all critical fields correct) | ≥ 0.99 **observed, with 95% interval reported** | TEST-clean + TEST-hard (+ TEST-syn if built) | See the resolution note below |
| SM-04 | Auto-accept coverage at the SM-03 operating point | ≥ 0.60 | same | Below ~50% automation barely helps |
| SM-05 | Expected calibration error (per field) | ≤ 0.05 | DEV (out-of-fold), then TEST | Routing only works if confidence is honest |
| SM-06 | Cost per document vs Tier 2 alone | ≥ 5× lower (stretch ≥ 10×) | TEST, from traces | The headline trade-off |
| SM-07 | Median review time per flagged document | ≤ 60 s | ≥ 30 self-timed reviews | Reviewer effort, not just accuracy |
| SM-08 | Duplicate exports from re-sent emails | 0 | Automated e2e test | Idempotency |
| SM-09 | Documents lost (accepted but never reaching a terminal or review state) | 0 | Soak test, 200 docs | Reliability |

> **Statistical resolution warning (important).** With N auto-accepted documents and **zero** observed errors, the 95% upper bound on the true error rate is roughly 3 / N. To *claim* ≥ 99% precision you need on the order of **300 error-free auto-accepted documents**. TEST-clean (~150) plus TEST-hard (~60) will not reach that. So: (a) report Wilson or Clopper-Pearson intervals on every precision number, (b) phrase the claim as "observed X% (95% CI a to b)", and (c) optionally build TEST-syn (~300 synthetic documents with exact generator labels) as an additional stress set, reported separately. Never round a point estimate up to a guarantee.

## 5. Users and jobs to be done

| Persona | Who | Job to be done | What they need from DocFlow |
|---|---|---|---|
| **P1 Finance reviewer** | Accounts-payable clerk | Clear the review queue fast without approving wrong numbers | Only doubtful fields flagged, evidence on the image, one-click fixes |
| **P2 Submitter** | Small-business owner who forwards invoices | Get invoices processed without thinking about it | Email in, nothing else to do; a clear message if a scan is unreadable |
| **P3 Integrator** | Developer wiring DocFlow into other tools | Reliable API | Idempotent uploads, stable schema, signed webhooks, OpenAPI |
| **P4 Operator** | You | Keep quality, cost and latency in check | Traces, dashboards, thresholds, drift alerts, an audit trail |

## 6. User stories and acceptance criteria

| ID | Story | Acceptance criteria |
|---|---|---|
| US-01 | As a submitter, I forward an invoice email and it gets processed. | Given an email with a PDF or image attachment, when it arrives, then a document is created within 60 s and reaches a decision state. |
| US-02 | As a submitter, forwarding the same email twice does not create duplicates. | Given identical file bytes, when re-submitted, then the existing `document_id` is returned and nothing is reprocessed or re-exported. |
| US-03 | As a reviewer, I see only what the system doubts. | Given a NEEDS_REVIEW document, then flagged fields appear first, each with confidence, reason and evidence on the image. |
| US-04 | As a reviewer, I correct a field in one action. | When I edit a value and save, then the corrected value, the model value and my identity are stored, and validators re-run on the corrected data. |
| US-05 | As a reviewer, I understand *why* a document needs me. | Every NEEDS_REVIEW document shows a human-readable reason derived from a machine-readable code. |
| US-06 | As an integrator, I upload via API and get a stable result schema. | `POST /v1/documents` returns 202 with `document_id`; `GET` returns the documented JSON; the schema is versioned. |
| US-07 | As an integrator, I receive signed status callbacks. | Webhooks carry an HMAC signature; retries use backoff; replayed old callbacks are rejected. |
| US-08 | As an operator, I can reproduce any past result. | Each result stores git SHA, prompt ID, model versions and threshold version; re-running with the same versions and replay cache gives the same output. |
| US-09 | As an operator, I see cost and quality drift before users do. | Dashboards show cost per doc, route mix, correction rate per field; at least three alert rules are defined and tested. |
| US-10 | As an operator, a provider outage does not lose documents. | Given the Tier 2 API is down, affected documents go to HUMAN REVIEW instead of failing; nothing is dropped. |
| US-11 | As an operator, I can prove the system works. | `make eval-dev` and CI produce the metrics in section 4 with confidence intervals; TEST runs are logged. |
| US-12 | As a privacy-conscious operator, logs never contain raw invoice values. | Log and trace samples contain hashes, field names and lengths only, unless a debug flag is on. |

## 7. Functional requirements

Phase = the phase in `05_Phase_Plan.md` where the requirement is delivered.

### 7.1 Intake

| ID | Requirement | Pri | Acceptance criterion | Phase |
|---|---|---|---|---|
| FR-INT-01 | Accept PDF, JPEG, PNG via API upload and via email through n8n | M | Both paths create a document and return/emit a `document_id` | P6 |
| FR-INT-02 | Idempotent by SHA-256 of file bytes, per tenant | M | Duplicate upload returns the existing document; test proves no reprocessing | P6 |
| FR-INT-03 | Reject unsupported type, oversize (> 10 MB) or too many pages (> 20) with a clear error | M | 415 / 413 / 422 with error code and message | P6 |
| FR-INT-04 | Reject unreadable images via a quality score and notify the operator (sender reply optional) | S | Blurry/tiny image → REJECTED_UNREADABLE with reason | P6 |
| FR-INT-05 | Support multi-page PDFs up to 20 pages | M | A 3-page invoice with the total on page 3 extracts correctly | P3 |

### 7.2 Extraction

| ID | Requirement | Pri | Acceptance criterion | Phase |
|---|---|---|---|---|
| FR-EXT-01 | Extract header fields: vendor_name, invoice_number, invoice_date, currency, subtotal, tax_total, total | M | Schema-valid output on 100% of processed docs (after one repair retry) | P2 |
| FR-EXT-02 | Extract line items: description, qty, unit_price, amount | M | Line-item F1 reported on DEV and TEST | P2 |
| FR-EXT-03 | Normalize to canonical formats (ISO 8601 dates, Decimal amounts, ISO 4217 currency) | M | Normalization unit and property tests pass, including `1.234,56` vs `1,234.56` | P1 |
| FR-EXT-04 | Return per-field evidence (page + bounding box) when OCR grounding exists | S | Evidence present for ≥ 90% of grounded critical fields on DEV | P3 |
| FR-EXT-05 | Two extraction tiers, models swappable by configuration | M | Changing a model alias in config changes the model with no code change | P2 |

### 7.3 Validation

| ID | Requirement | Pri | Acceptance criterion | Phase |
|---|---|---|---|---|
| FR-VAL-01 | Arithmetic rules: subtotal + tax = total; line amounts sum to subtotal; qty × unit_price = amount | M | Rules unit-tested with pass, fail and tolerance cases | P3 |
| FR-VAL-02 | Format and plausibility rules: date range, currency, positive total | M | Same | P3 |
| FR-VAL-03 | Grounding: every critical value must be findable in OCR text | M | Hallucinated-vendor test case is caught | P3 |
| FR-VAL-04 | Duplicate detection: same vendor + number + total | S | Flag raised, routed to review | P6 |
| FR-VAL-05 | Every rule result stored with rule ID, field, pass/fail, detail | M | Visible in API response and audit log | P3 |

### 7.4 Confidence and routing

| ID | Requirement | Pri | Acceptance criterion | Phase |
|---|---|---|---|---|
| FR-CNF-01 | Calibrated per-field probability of correctness | M | Reliability diagram and ECE reported | P4 |
| FR-CNF-02 | Document confidence = minimum over critical fields (vendor, number, date, total) | M | Unit test on the aggregation | P4 |
| FR-RTE-01 | Route to AUTO_ACCEPT, ESCALATE or HUMAN_REVIEW by policy | M | Router decision table fully unit-tested | P4 |
| FR-RTE-02 | Thresholds configurable, versioned, chosen on DEV only | M | Threshold artifact records DEV set hash, method, date | P4 |
| FR-RTE-03 | Escalate at most once per document, under a per-document cost cap | M | Test: no third extraction call is ever made | P4 |
| FR-RTE-04 | If Tier 2 is unavailable, route to HUMAN_REVIEW | M | Fault-injection test | P6 |
| FR-RTE-05 | Route reason is machine-readable and shown to humans | M | Reason-code catalog in TRD; UI mapping in Design doc | P4 |

### 7.5 Review

| ID | Requirement | Pri | Acceptance criterion | Phase |
|---|---|---|---|---|
| FR-REV-01 | Queue of documents needing review, oldest first | M | Ordered list with reason filter | P7 |
| FR-REV-02 | Review screen: image, evidence highlights, doubtful fields first | M | Matches DR-UI-02 | P7 |
| FR-REV-03 | Approve, correct or reject; store model value vs human value | M | `corrections` rows created; status transitions valid | P7 |
| FR-REV-04 | Corrections exportable as eval and fine-tuning candidates | S | Export script produces a manifest | P7 |
| FR-REV-05 | Keyboard shortcuts for common actions | C | Shortcuts documented and working | P7 |

### 7.6 Export and integration

| ID | Requirement | Pri | Acceptance criterion | Phase |
|---|---|---|---|---|
| FR-EXP-01 | Export accepted and approved documents as CSV and JSON | M | `GET /v1/exports` returns correct rows | P6 |
| FR-EXP-02 | Append rows to Google Sheets via n8n | S | e2e demo run | P6 |
| FR-EXP-03 | Signed, retried status webhooks | M | Signature test; retry test; dead-letter after max attempts | P6 |
| FR-EXP-04 | Notify the operator/reviewer on Telegram or Slack for NEEDS_REVIEW | S | Message contains reason and link | P6 |

### 7.7 Audit, observability, security

| ID | Requirement | Pri | Acceptance criterion | Phase |
|---|---|---|---|---|
| FR-AUD-01 | Append-only audit trail of state changes, decisions and versions | M | No update or delete path exists; test proves it | P6 |
| FR-OBS-01 | One trace per document with a span per stage | M | Trace visible for a sample doc end to end | P2 |
| FR-OBS-02 | Metrics and three dashboards (Operations, Quality proxy, Queue) | S | Dashboards render from real data | P7 |
| FR-OBS-03 | Alert rules defined and tested | S | ≥ 3 rules fire in a fault-injection test | P7 |
| FR-SEC-01 | API-key authentication, keys stored hashed | M | Unauthenticated calls get 401 | P6 |
| FR-SEC-02 | Every query scoped by tenant_id | M | Cross-tenant access test fails closed | P6 |
| FR-SEC-03 | PII-safe logging | M | Log-scan test finds no raw field values | P2 |
| FR-SEC-04 | Retention job and deletion endpoint | S | Originals removed after N days; delete endpoint works | P8 |

### 7.8 Evaluation

| ID | Requirement | Pri | Acceptance criterion | Phase |
|---|---|---|---|---|
| FR-EVAL-01 | Harness computes all section 4 metrics for any system on any split | M | `run_eval` produces a JSON report | P1 |
| FR-EVAL-02 | Frozen, hashed test sets and a logged run history | M | TEST_RUNS.md entry per run; CI fails if manifests change | P1 |
| FR-EVAL-03 | CI regression gate using replayed model responses | M | PR that worsens a metric beyond threshold fails CI | P7 |
| FR-EVAL-04 | Baseline comparison (A, B, C) on accuracy, cost, latency | M | Comparison table with intervals | P2 |
| FR-EVAL-05 | Bootstrap intervals for accuracy; Wilson or Clopper-Pearson for proportions; paired comparisons | M | Every reported metric carries an interval | P1 |
| FR-EVAL-06 | Generate Pareto plot and risk-coverage curve from run data | S | Scripts produce PNGs for the README | P4 to P5 |
| FR-EVAL-07 | Optional TEST-syn set (~300 synthetic documents) for precision resolution | C | Set built, reported separately | P8 |

### 7.9 Stretch

| ID | Requirement | Pri | Acceptance criterion | Phase |
|---|---|---|---|---|
| FR-FT-01 | LoRA-tuned small open VLM evaluated against the baselines | C | Point on the Pareto plot with an interval; gate G3 passed | P5 |

## 8. Scope and release plan

| Release | Contents | When |
|---|---|---|
| **MVP slice** | Eval harness, baselines, validators, routing on DEV | End of Phase 4 (week 4) |
| **v1.0** | Everything Must and Should above, including service, n8n flow, review UI, CI gate | End of Phase 8 (week 8) |
| **Later (not committed)** | Second document family, multilingual, active learning automation, React UI, accounting integrations | After v1.0 |

## 9. Assumptions, constraints, dependencies

**Assumptions**
- Documents are English or another Latin-script language, printed or photographed, up to 20 pages.
- A hosted vision-capable model is available for Tier 2 within a spending cap you set.
- 10 to 15 hours per week over 8 weeks.

**Constraints**
- Runs on a laptop with no GPU, except the optional fine-tuning stretch (free Colab or Kaggle GPU).
- **n8n is used locally for personal, non-commercial purposes.** If this ever becomes commercial, replace the trigger layer with a permissively licensed alternative or review n8n's licensing. The architecture keeps the trigger layer swappable for this reason.
- **Privacy.** Real business or personal invoices must not be sent to third-party hosted APIs or committed to a public repository. Use public datasets, synthetic documents, or documents you have the right to process. For real documents, use a locally hosted model.
- A hard monthly spend cap on the API key.

**Dependencies**: public datasets (SROIE, CORD, or similar), an OCR engine, a model gateway (LiteLLM), Postgres, Redis, n8n, an OpenTelemetry-compatible tracing backend.

## 10. Risks

| ID | Risk | L | I | Mitigation | Phase |
|---|---|---|---|---|---|
| R-01 | Labeling takes longer than planned | H | M | Synthetic documents with generator labels; cap real hand-labeled set at ~50; start in week 1 | P1 |
| R-02 | API cost overrun | M | M | Spend cap; response cache; live runs on DEV only; cheap models while iterating | P2 |
| R-03 | Test-set leakage | M | H | Hashed read-only manifests; CLI guard; run log; no TEST docs in prompts, few-shot examples or fine-tuning | P1 |
| R-04 | Public benchmark docs already seen by frontier models | H | M | Report clean and hard separately; hard set is unseen | P1 |
| R-05 | Test sets too small to resolve 99% precision | H | M | Report intervals; phrase the claim honestly; optional TEST-syn | P8 |
| R-06 | Confidence calibration unstable on small DEV | M | H | Simple model (logistic + isotonic), cross-validation, monotone features; fallback to rule-based routing | P4 |
| R-07 | Scope creep | H | M | Non-goals list; any addition must displace something of equal size | all |
| R-08 | Prompt injection via invoice text | M | H | Schema-constrained output, no tools for the extraction model, document text treated as data, injection tests | P3 |
| R-09 | PII in logs or repo | M | H | Redaction, `.gitignore` for datasets, secret and large-file pre-commit hooks | P2 |
| R-10 | Fine-tuning stretch eats the schedule | M | M | Gate G3; first thing cut | P5 |
| R-11 | n8n licence misuse if commercialized | L | H | Local personal use only; swappable trigger layer | P6 |
| R-12 | Provider deprecates or changes a model | M | M | Pin exact versions; gateway abstraction; replay cache | P2 |

## 11. Open questions

| ID | Question | Needed by | Default if unanswered |
|---|---|---|---|
| Q-01 | Which document families: retail receipts, vendor invoices, or both? | Week 1 | Both, invoices weighted higher |
| Q-02 | Which Tier 2 model, and what monthly cap? | Week 2 | A hosted vision model, cap you set before week 2 |
| Q-03 | Is a GPU (Colab/Kaggle) available for the stretch? | Week 4 | No; skip fine-tuning (gate G3) |
| Q-04 | Google Sheets needed, or CSV only? | Week 6 | CSV only |
| Q-05 | Public repo or private? | Week 1 | Public with synthetic data only |
| Q-06 | Do you want the optional TEST-syn set? | Week 7 | Yes if time allows |

## 12. Changes from Blueprint v1.0

These corrections come from turning the blueprint into requirements. This PRD and the TRD supersede the blueprint where they differ.

| # | Blueprint said | Now | Why |
|---|---|---|---|
| 1 | Target ≥ 0.99 auto-accept precision | Report observed precision with an interval; ~300 clean accepted docs needed to claim ≥ 99% | Test sets are too small to prove 99% |
| 2 | Intermediate states (PREPROCESSED, PARSED, …) as document states | Only externally meaningful states in `status`; pipeline steps are `stage` events in the audit log | Simpler state machine, fewer invalid transitions |
| 3 | API had six endpoints | Added `POST /v1/documents/{id}/export-ack`, `GET /v1/exports`, health endpoints | n8n needs a way to confirm exports; export needs a defined read path |
| 4 | Extraction returned normalized values | The model returns raw strings as printed; **code** normalizes | Fewer locale and arithmetic errors, and grounding checks work on raw strings |
| 5 | CI gate: "no regression beyond 2 points" on ~30 docs | Gate on field-level micro-F1 (about 200 fields), not doc-level | One document is ~3 points at doc level; too coarse |
| 6 | n8n replies to the sender when a scan is unreadable | Off by default; notify the operator | Avoids auto-reply loops and messaging external addresses without consent |
| 7 | Langfuse self-hosted as the tracing default | OpenTelemetry + Phoenix (single container) as default; Langfuse optional | Self-hosting Langfuse needs several supporting services; verify against current docs |

## 13. Release gates (definition of done for v1.0)

| ID | Gate |
|---|---|
| RG-01 | Frozen, hashed TEST-clean and TEST-hard sets; every test run logged |
| RG-02 | Baselines A, B, C compared on accuracy, cost, latency with intervals |
| RG-03 | FAILURES.md: error taxonomy with counts and what fixed each category |
| RG-04 | Risk-coverage curve, chosen operating point justified, ECE reported |
| RG-05 | Cost-accuracy Pareto plot (including the tuned small model if attempted) |
| RG-06 | Email → export works, including duplicate, unreadable and provider-down paths |
| RG-07 | A trace for every document, with prompt, model and threshold versions |
| RG-08 | CI blocks regressions; replay-only, no live calls |
| RG-09 | Log-scan test shows no raw invoice values |
| RG-10 | README with results table, architecture diagram, demo video (≤ 3 min) and one write-up on the hardest trade-off |
