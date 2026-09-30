# DocFlow: Phase-wise Plan

| | |
|---|---|
| **Version** | 1.0 (draft) |
| **Date** | 2026-09-29 |
| **Duration** | 8 phases, one per week, part-time (~10 to 16 h/week, ~115 h total) |
| **Related** | Requirements in `01_PRD` (FR IDs), `02_TRD` (TR IDs), design in `03_Design` (DR IDs) |

Hour estimates are planning guesses for one person. Track actual hours per task from week 1; by week 3 you will know your real multiplier. Plan for it to be 1.3 to 1.5×.

---

## 1. Plan at a glance

| Phase | Week | Theme | Est. h | Headline deliverable | Gate |
|---|---|---|---|---|---|
| **P1** | 1 | Foundations: schema, data, eval harness | 16 | Eval script runs on a dummy predictor; test sets frozen | |
| **P2** | 2 | Baselines and walking skeleton | 14 | Baseline comparison table (A, B, C) with tracing on | **G1** |
| **P3** | 3 | Validators, grounding, error analysis | 12 | `FAILURES.md` taxonomy; validators tested | |
| **P4** | 4 | Confidence and routing | 14 | Risk-coverage curve; thresholds; first logged TEST run | **G2** |
| **P5** | 5 | Cost optimization (+ stretch: fine-tune) | 12 (+8) | Pareto plot | **G3** |
| **P6** | 6 | Real service and n8n integration | 16 | Email in, row out, including failure paths | |
| **P7** | 7 | Review UI, feedback loop, dashboards, CI | 16 | Correction becomes an eval candidate; CI gate live | |
| **P8** | 8 | Hardening, final test run, release | 12 | v1.0 tagged; README, video, write-up | **G4** |

### Gates (go / no-go decisions)

| Gate | When | Question | If the answer is no |
|---|---|---|---|
| **G1** | End of P2 | Do the baselines run on DEV with a defensible comparison, and is at least one baseline usable as Tier 1 or Tier 2? | Do not start P3. Debug normalization, OCR and prompts on DEV-clean first. |
| **G2** | End of P4 | Is the routing viable: does the risk-coverage curve show a region with useful coverage at low error, and is calibration not absurd (ECE within roughly 2× target)? | Fall back to rule-only routing (validators + agreement) and document why calibration failed. Continue to P5 without fine-tuning. |
| **G3** | Start of P5 stretch | Is P4 complete, is a GPU available, and are ≥ 8 spare hours available? | Skip fine-tuning entirely. The cascade Pareto plot is enough. |
| **G4** | End of P8 | Are all release gates RG-01 to RG-10 met? | Tag `v1.0-rc`, list what is missing in the README honestly. Do not hide gaps. |

### Test-set run schedule

TEST sets are touched **only** at these points, each logged automatically in `TEST_RUNS.md`.

| Run | When | Purpose |
|---|---|---|
| T1 | End of P4 | First honest number for the routed system |
| T2 | End of P5 | Cascade (and tuned model, if attempted) for the Pareto plot |
| T3 | P8 | Final numbers for the README |

Anything beyond T3 needs a written reason in `TEST_RUNS.md`. If you catch yourself wanting a fourth run to "check something", that is the leakage temptation; go back to DEV.

### Weekly ritual (30 minutes, every Friday)

1. Run `make eval-dev`; save the report.
2. Update `FAILURES.md` with new error counts.
3. Update this plan: actual hours, what slipped, what gets cut.
4. Tag the repo (`week-N`) and write two sentences in `docs/journal.md`: what you learned, what surprised you.
5. Optional: post a one-paragraph progress note. A public trail of decisions is itself a portfolio asset.

### Cut order if you fall behind

1. Fine-tuning stretch (P5)
2. Keyboard shortcuts, dashboard polish, S5 (P7)
3. Google Sheets export (keep CSV) (P6)
4. TEST-syn (P8)
5. Never cut: eval harness, frozen test sets, validators, tracing, the router, the CI replay gate.

### Definition of Ready and Done (every task)

- **Ready:** the requirement ID is known, the acceptance criterion is written, and any input data exists.
- **Done:** code merged with tests; docs updated if behavior changed; eval report saved if a metric could move; no TODOs left without a ticket line in `docs/backlog.md`.

---

## Phase 1: Foundations (Week 1, ~16 h)

**Objective.** Make it possible to measure anything, before building anything.

**Requirements covered:** FR-EXT-03, FR-EVAL-01, FR-EVAL-02, FR-EVAL-05, TR-EVAL-01..07, TR-ENV-01..04, TR-DAT-02.

| Task | Description | Est. h |
|---|---|---|
| P1-T1 | Repo scaffold: `uv`/Poetry, ruff, mypy, pytest, pre-commit (secret scan, large-file and dataset-path blocks), Makefile, `docker-compose` with Postgres and Redis | 2 |
| P1-T2 | Pydantic schemas (model output schema with raw strings; canonical schema) and the **normalization module** (dates, amounts with `1.234,56` vs `1,234.56`, currency) with unit and Hypothesis property tests | 3 |
| P1-T3 | Public data: download subsets of SROIE / CORD (or similar); write the manifest builder and label mapper; evaluate only labeled fields per dataset | 3 |
| P1-T4 | **Hard set:** collect ~50 real documents you may legally use (photographed, crumpled, rotated) and generate ~50 synthetic invoices with a template + Faker generator, then degrade them (rotation, blur, noise, perspective, shadow) | 4 |
| P1-T5 | Label: real hard docs by hand (TEST-hard with no model pre-labels; DEV-hard may be model-assisted with every field reviewed). Synthetic docs take labels from the generator. Budget ~7 to 10 h of labeling, spilling into P2 is acceptable | 4 (+3 in P2) |
| P1-T6 | Metrics module with tests: field exact match, header F1, line-item F1 (Hungarian), doc-level, auto-accept coverage and precision, risk-coverage/AURC, ECE, cost and latency aggregates; bootstrap, Wilson, paired bootstrap | 4 |
| P1-T7 | `run_eval` CLI with a dummy predictor; manifest hashing; TEST guard (`--allow-test`); auto-append to `TEST_RUNS.md`; CI check for manifest hash | 2 |

**Deliverables.** `evals/` with manifests and metrics; frozen and hashed TEST sets; a report from the dummy predictor.

**Exit criteria.**
- [ ] ≥ 100 documents labeled across DEV/TEST splits (labeling of the remainder may finish in P2)
- [ ] `run_eval` runs end to end on a dummy predictor and produces intervals
- [ ] TEST manifests hashed and read-only; guard tested
- [ ] Metric code passes unit tests on hand-made cases (including a case with known F1)

**Evals run.** Metrics-on-toy-cases only (no models yet).
**Observability added.** Structured JSON logging convention with the PII rule (TR-SEC-05).
**Risks.** R-01 labeling time; R-03 leakage. **Demo artifact:** the report from the dummy predictor plus the dataset card.

---

## Phase 2: Baselines and walking skeleton (Week 2, ~14 h)

**Objective.** Get real numbers for three simple systems and a thin end-to-end slice with tracing.

**Requirements covered:** FR-EXT-01, FR-EXT-02, FR-EXT-05, FR-EVAL-04, FR-OBS-01, FR-SEC-03, TR-MOD-01..05, TR-OBS-01..04.

| Task | Description | Est. h |
|---|---|---|
| P2-T1 | Model gateway (LiteLLM) with `tier1`/`tier2` aliases, structured output, `live`/`record`/`replay` cache, pricing table | 3 |
| P2-T2 | OCR adapters (Tesseract baseline, PaddleOCR or Docling); choose on DEV (AQ-02) | 2 |
| P2-T3 | Baseline **A**: OCR + regex per field | 2 |
| P2-T4 | Baseline **B**: OCR text → LLM with schema-constrained output (prompts PR-01, PR-03) | 2 |
| P2-T5 | Baseline **C**: image → VLM with schema-constrained output | 2 |
| P2-T6 | OpenTelemetry + Phoenix: trace every model call from day one | 2 |
| P2-T7 | Walking skeleton: FastAPI `POST /v1/documents` (synchronous, runs baseline B) and `GET`; comparison report script | 3 |
| P2-T8 | Finish remaining labeling from P1 | 3 |

**Deliverables.** Baseline comparison table on DEV: accuracy (with intervals), cost per doc, latency p50/p95, for A, B, C. Traces visible in Phoenix. An ADR recording the Tier 1 / Tier 2 choice with DEV numbers (TR-MOD-07).

**Exit criteria (G1).**
- [ ] A, B, C evaluated on DEV-clean and DEV-hard
- [ ] Schema-valid output on 100% of documents (after one repair)
- [ ] Every model call appears as a span with cost and tokens
- [ ] A live spend cap is configured and the response cache is working (a second run costs nothing)

**Evals run.** Full DEV live, three systems. **Observability added.** Tracing, cost per call.
**Risks.** R-02 cost; R-12 provider changes. **Demo artifact:** the comparison table and a screenshot of one trace.

---

## Phase 3: Validators, grounding and error analysis (Week 3, ~12 h)

**Objective.** Catch wrong answers deterministically, and learn *why* the models are wrong.

**Requirements covered:** FR-VAL-01, FR-VAL-02, FR-VAL-03, FR-VAL-05, FR-EXT-04, FR-INT-05, TR-VAL-01..03, TR-PIPE-05/06/07, TR-SEC-01/02, TR-EVAL-10.

| Task | Description | Est. h |
|---|---|---|
| P3-T1 | Validators R-REQ-01, R-SUM-01/02, R-LINE-01, R-DATE-01, R-CUR-01, R-RANGE-01 with pass, fail, tolerance-edge and missing-input tests | 3 |
| P3-T2 | Grounding R-GRD-01 (amounts, dates, strings) and evidence boxes from OCR coordinates | 3 |
| P3-T3 | Preprocessing: rotation, deskew, quality score; multi-page page selection (TR-PIPE-06) | 2 |
| P3-T4 | Prompt-injection regression suite (PR-T tests) and fixes | 1 |
| P3-T5 | Error analysis tooling: tag failures with the taxonomy; write counts to `FAILURES.md` | 2 |
| P3-T6 | Prompt iteration driven by the taxonomy (each change: DEV eval, per-field diff, CHANGELOG entry) | 1 |

**Deliverables.** Validators and grounding in the core library; `FAILURES.md` with counts per category and one fix hypothesis each.

**Exit criteria.**
- [ ] Validators unit-tested (≥ 80% coverage on `validators/`)
- [ ] For each baseline, the share of wrong fields *caught* by a blocking rule is measured and reported
- [ ] Injection suite passes: no injected instruction changes extracted values
- [ ] `FAILURES.md` exists with the taxonomy and counts

**Evals run.** DEV live after each prompt change. **Observability added.** Per-rule validation-failure metrics.
**Risks.** R-08 injection. **Demo artifact:** "what fraction of model errors do simple rules catch?" chart. This is often a surprising and shareable result.

---

## Phase 4: Confidence and routing (Week 4, ~14 h)

**Objective.** Make the system know when it is wrong, and prove it.

**Requirements covered:** FR-CNF-01, FR-CNF-02, FR-RTE-01, FR-RTE-02, FR-RTE-03, FR-RTE-05, FR-EVAL-06 (risk-coverage), TR-CNF-01..05, TR-RTE-01..03, TR-PIPE-04.

| Task | Description | Est. h |
|---|---|---|
| P4-T1 | Feature extraction per field (validation_ok, grounded, agreement, logprob if available, image quality, OCR confidence, field type) | 3 |
| P4-T2 | Logistic regression + isotonic/Platt calibration, **out-of-fold** on DEV; reliability diagrams and ECE | 3 |
| P4-T3 | Router as a pure function with a full decision-table test; reason-code catalog | 2 |
| P4-T4 | Threshold selection script producing a versioned artifact (`config/thresholds/`) | 2 |
| P4-T5 | Tier 2 escalation path (independent of Tier 1, TR-MOD-06); per-document cost cap and call cap | 2 |
| P4-T6 | Risk-coverage plot script; **TEST run T1** | 2 |

**Deliverables.** Calibrated confidence, thresholds artifact, risk-coverage curve, first logged TEST run.

**Exit criteria (G2).**
- [ ] Reliability diagram and ECE reported, with bin counts
- [ ] Router decision table 100% unit-tested; property test: never more than one escalation
- [ ] Threshold artifact records DEV hash, method, date, git SHA
- [ ] T1 executed and logged; results reported with intervals and the sufficiency bound (TR-EVAL-07)
- [ ] `agreement` decision made (AQ-03, AQ-04)

**Evals run.** DEV out-of-fold; TEST T1. **Observability added.** Route-mix and confidence histograms.
**Risks.** R-06 calibration instability. **Demo artifact:** the risk-coverage curve with the operating point marked.

---

## Phase 5: Cost optimization and (optional) fine-tuning (Week 5, ~12 h, +8 h stretch)

**Objective.** Move down the cost axis without giving up accuracy, and show the trade-off.

**Requirements covered:** FR-EVAL-06 (Pareto), SM-06, FR-FT-01 (stretch), TR-EVAL-09.

| Task | Description | Est. h |
|---|---|---|
| P5-T1 | Cost model from traces: cost per doc by tier, by route path | 2 |
| P5-T2 | Cascade tuning: Tier 1 candidates on DEV, choose cheapest that clears the bar; document as an ADR | 4 |
| P5-T3 | Pareto plot script (cost vs header F1 with interval bars); README table draft | 3 |
| P5-T4 | Latency optimization pass (parallel OCR pages, image size, caching) | 2 |
| P5-T5 | **TEST run T2**; write the trade-off analysis | 1 |
| *Stretch* P5-S1 | Build TRAIN-ft from public train splits + reviewed corrections (**no TEST data**) | 2 |
| *Stretch* P5-S2 | LoRA fine-tune a small open VLM on a free GPU | 3 |
| *Stretch* P5-S3 | Serve locally (vLLM or similar); evaluate as Tier 1; add to Pareto | 2 |
| *Stretch* P5-S4 | Write up what worked, what didn't | 1 |

**Deliverables.** Pareto plot, cost-per-doc breakdown, Tier 1 ADR; (stretch) tuned-model point.

**Exit criteria.**
- [ ] Pareto plot generated by a script from run files
- [ ] SM-06 measured (cost vs Tier 2 alone), with interval
- [ ] T2 executed and logged
- [ ] (Stretch) tuned model evaluated on the same splits, TEST not used in training, verified by manifest hash check

**Evals run.** DEV per candidate; TEST T2. **Observability added.** Cost dashboards.
**Risks.** R-10 stretch overrun (**G3** decides). **Demo artifact:** the Pareto plot.

---

## Phase 6: Real service and n8n integration (Week 6, ~16 h)

**Objective.** Turn the pipeline into a reliable service, and connect it to the outside world.

**Requirements covered:** FR-INT-01..04, FR-VAL-04, FR-RTE-04, FR-EXP-01..04, FR-AUD-01, FR-SEC-01/02, TR-API-01..13, TR-DAT-01/03/04/06, TR-PIPE-01/02, TR-REL-01..04, DR-WF-01..06.

| Task | Description | Est. h |
|---|---|---|
| P6-T1 | Alembic migrations for the schema in TRD §4; app DB role with least privilege | 2 |
| P6-T2 | API endpoints per TRD §3.1: auth, upload validation, idempotency, error envelope, health | 3 |
| P6-T3 | Worker: queue, stage checkpoints, advisory lock, state machine with transition tests, reaper and sweeper | 4 |
| P6-T4 | Audit log with versions block; append-only enforcement test | 1 |
| P6-T5 | Signed webhooks: HMAC, timestamp window, retries, dead letters, SSRF allow-list | 2 |
| P6-T6 | Export endpoints, `export-ack`, duplicate detection R-DUP-01 | 1 |
| P6-T7 | n8n Workflows A and B; export JSON to `n8n/` | 2 |
| P6-T8 | Circuit breaker; fault-injection tests for the degradation matrix (Tier 2 down, OCR down, Redis down) | 1 |

**Deliverables.** Running stack via `make up`; email in, decision out, row written, `export-ack` received.

**Exit criteria.**
- [ ] Scripted e2e: email → decision → export, for AUTO_ACCEPTED and NEEDS_REVIEW paths
- [ ] Duplicate email: one document, one row
- [ ] Kill a worker mid-document: it resumes, no double model call
- [ ] Tier 2 fault injection routes to review with `TIER2_UNAVAILABLE`
- [ ] Cross-tenant access test fails closed; unauthenticated calls get 401

**Evals run.** DEV via the API path must equal DEV via the harness (integration check). **Observability added.** Full trace per document; stage-duration metrics.
**Risks.** R-11 licence (local only); scope creep in n8n. **Demo artifact:** a screen recording of forwarding an email and watching it flow.

---

## Phase 7: Review UI, feedback loop, dashboards and CI (Week 7, ~16 h)

**Objective.** Close the human loop and make regressions impossible to miss.

**Requirements covered:** FR-REV-01..05, FR-OBS-02/03, FR-EVAL-03, DR-UI-01..34, DR-NTF-01..03, TR-EVAL-08, TR-OBS-05/06, TR-ENV-05.

| Task | Description | Est. h |
|---|---|---|
| P7-T1 | Streamlit S1 queue and S2 review screen (image with evidence boxes, doubtful-first field list, validation panel, actions, timing) | 5 |
| P7-T2 | Review endpoint semantics (re-validation, 409 flow), Undo as compensating record | 2 |
| P7-T3 | Corrections export script producing candidate manifest rows (never into TEST) | 1 |
| P7-T4 | S3 audit view and S4 dashboards; metrics endpoint | 3 |
| P7-T5 | Alert rules with fault-injection tests (≥ 3) | 1 |
| P7-T6 | CI: lint, types, unit and integration tests, replay-only eval gate on a 30-doc DEV subset, `pip-audit` | 3 |
| P7-T7 | Time 30 reviews to compute SM-07; keyboard shortcuts if time remains | 1 |

**Deliverables.** Working review flow; CI gate that fails on a deliberately introduced regression (prove it).

**Exit criteria.**
- [ ] Reviewer path: open → fix → save works, ≤ 3 clicks after opening
- [ ] A correction appears as a candidate row in the export
- [ ] CI blocks a PR that breaks a validator or drops F1 by > 2 points, and blocks on any replay cache miss
- [ ] ≥ 3 alerts fire in fault-injection tests
- [ ] SM-07 measured on ≥ 30 reviews

**Evals run.** CI replay each PR; DEV live for any prompt or model change. **Observability added.** Correction rate per field, queue age, dashboards.
**Demo artifact:** the review screen (GIF) and a PR that CI rejected.

---

## Phase 8: Hardening, final test run and release (Week 8, ~12 h)

**Objective.** Close the gaps, run the final numbers once, and package the project so others can verify it.

**Requirements covered:** FR-SEC-04, FR-EVAL-07 (optional), RG-01..RG-10, TR-SEC-01..10, TR-TEST-05..08.

| Task | Description | Est. h |
|---|---|---|
| P8-T1 | Security pass: log-scan test, upload spoofing test, SSRF test, retention job and delete endpoint, dependency audit | 2 |
| P8-T2 | Soak test: 200 documents with random worker kills (SM-09) | 1 |
| P8-T3 | Optional TEST-syn (~300 synthetic docs) to tighten the precision interval | 2 |
| P8-T4 | **TEST run T3** (final). Fill the README results table with intervals and the sufficiency bound | 1 |
| P8-T5 | README: architecture diagram, results, how to run, limitations; `FAILURES.md` final; ADR index | 2 |
| P8-T6 | 3-minute demo video; blog post on the hardest trade-off | 3 |
| P8-T7 | Buffer for slipped work from earlier phases | 1 |

**Exit criteria (G4).** Release gates RG-01 to RG-10 in the PRD are all checked, or the README lists what is missing.

**Demo artifact:** the release itself.

---

## 2. Requirements to phase traceability

| Area | P1 | P2 | P3 | P4 | P5 | P6 | P7 | P8 |
|---|---|---|---|---|---|---|---|---|
| Intake (FR-INT) | | | INT-05 | | | 01-04 | | |
| Extraction (FR-EXT) | 03 | 01, 02, 05 | 04 | | | | | |
| Validation (FR-VAL) | | | 01, 02, 03, 05 | | | 04 | | |
| Confidence and routing (FR-CNF, FR-RTE) | | | | all except RTE-04 | | RTE-04 | | |
| Review (FR-REV) | | | | | | | all | |
| Export (FR-EXP) | | | | | | all | | |
| Audit, obs, sec | | OBS-01, SEC-03 | | | | AUD-01, SEC-01/02 | OBS-02/03 | SEC-04 |
| Evaluation (FR-EVAL) | 01, 02, 05 | 04 | | 06 (risk-coverage) | 06 (Pareto) | | 03 | 07 |
| Stretch (FR-FT) | | | | | 01 | | | |

## 3. Risk watch by phase

| Phase | Top risk | Early-warning sign | Response |
|---|---|---|---|
| P1 | Labeling drags | < 40 docs labeled by mid-week | Shift more of the hard set to synthetic; cap real docs at 30 |
| P2 | Cost overrun | Spend > 50% of cap by end of week | Use the cheap model for iteration; rely on replay cache |
| P3 | Endless prompt tinkering | > 5 prompt versions with no F1 gain | Stop; fix with validators and routing instead |
| P4 | Calibration unstable | Reliability diagram is noisy or non-monotone | Fewer features; rule-based fallback (G2) |
| P5 | Fine-tuning rabbit hole | Training data still not ready by day 2 | Cancel stretch (G3) |
| P6 | n8n scope creep | Adding "just one more" node types | Freeze workflows A and B; anything else goes to the backlog |
| P7 | Streamlit fighting you | > 3 h on shortcuts or layout polish | Ship without; note in backlog |
| P8 | Test-set temptation | Wanting a fourth TEST run | Write the reason in `TEST_RUNS.md` first; if it is "the number looks bad", do not run |

## 4. After v1.0 (not committed)

- A second document family (bank statements or purchase orders) to test generalization of the design.
- Scheduled recalibration from accumulated corrections; shadow evaluation of new models.
- Batch API usage for cost; self-hosted Tier 1 on a rented GPU.
- A React UI if the review workflow needs real shortcuts and latency.
