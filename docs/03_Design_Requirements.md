# DocFlow: Design Requirements

| | |
|---|---|
| **Version** | 1.0 (draft) |
| **Date** | 2026-09-29 |
| **Implements** | `01_PRD` user stories US-03 to US-07, US-09; feeds `05_Phase_Plan` Phases 6 and 7 |
| **Scope** | "Design" here means everything a human or another system *touches*: review UI, operator dashboard, notification messages, the n8n workflow, and API conventions. System structure is in `04_Architecture`. |

---

## 1. Design principles

| # | Principle | What it means in practice |
|---|---|---|
| D1 | **Show doubt, not data** | The reviewer's eye goes to what the system is unsure about first. Confident fields are visible but quiet. |
| D2 | **Explain every decision** | Every routing outcome has a plain-language reason. "Needs review" alone is never acceptable. |
| D3 | **Evidence over assertion** | A value is shown next to where it came from on the image. |
| D4 | **One fix, one action** | Correcting a field takes one edit and one save, not a form. |
| D5 | **Never hide a failure** | Errors, degraded modes and validation failures are visible, not swallowed. |
| D6 | **Speed over polish (v1)** | Streamlit is enough. Clarity of information beats visual design. |
| D7 | **Don't rely on color alone** | Every status color also has text and a number. |

## 2. Screen inventory

| ID | Screen | Primary persona | Purpose | Phase |
|---|---|---|---|---|
| S1 | Review queue | P1 Reviewer | Pick the next document | P7 |
| S2 | Review screen | P1 Reviewer | Verify and correct one document | P7 |
| S3 | Document detail and audit | P3, P4 | See everything that happened to a document | P7 |
| S4 | Operator dashboard | P4 Operator | Watch cost, quality proxy, queue | P7 |
| S5 | Eval results (optional) | P4 Operator | Browse the latest eval report and plots | P8 |

## 3. Review UI requirements

### 3.1 S1: Review queue

**Wireframe**

```
+----------------------------------------------------------------------------------+
| DocFlow / Review queue                       7 waiting   oldest 42 min   [refresh]|
+----------------------------------------------------------------------------------+
| Filter reason: [All v]   Source: [All v]   Sort: oldest first                     |
+---------+---------------+--------+----------------------------+------------+-----+
| Age     | Document      | Source | Why it needs you           | Weakest    | Tier|
|         |               |        |                            | field      |     |
+---------+---------------+--------+----------------------------+------------+-----+
| 42 min  | doc_7f3a91    | email  | Models disagree on total   | total 0.41 | 2   |
| 31 min  | doc_c20b17    | api    | Subtotal + tax does not... | total 0.58 | 1   |
| ...     |               |        |                            |            |     |
+---------+---------------+--------+----------------------------+------------+-----+
```

| ID | Requirement | Traces to |
|---|---|---|
| DR-UI-01 | Lists NEEDS_REVIEW and FLAGGED_DUPLICATE documents, oldest first; filters by reason code and source; shows total waiting and oldest age. Clicking a row opens S2. | FR-REV-01 |
| DR-UI-01a | Empty state: "Nothing waiting. New documents that need a human will appear here." with a last-refreshed timestamp. | D5 |

### 3.2 S2: Review screen

**Wireframe**

```
+----------------------------------------------------------------------------------+
| doc_7f3a91  vendor_invoice_0418.jpg            [NEEDS REVIEW]           3 of 7   |
| Why: Tier 1 and Tier 2 disagree on total.  Tier used: 2   Cost: $0.0xx            |
+-----------------------------------------+----------------------------------------+
|  Page 1 / 1        [-] [100%] [+] [fit] |  Fields (doubtful first)               |
|  +-----------------------------------+  |  total          [ 1,298.00 ]  LOW 0.41 |
|  |  ACME SUPPLIES LTD  [vendor 0.99] |  |    T1: 1,298.00   T2: 1,180.00         |
|  |                     INVOICE       |  |  invoice_number [ INV-20418 ] HIGH 0.97|
|  |  ...                [date 0.98]   |  |  invoice_date   [ 2025-03-14 ] HIGH 0.98|
|  |  Subtotal              1,180.00   |  |  vendor_name    [ Acme ...   ] HIGH 0.99|
|  |  TOTAL  [ 1,298.00 ] <- amber box |  |  ...                                    |
|  +-----------------------------------+  |  Line items (3)  [expand]              |
|                                         |  Validation:  OK sum   FAIL tiers agree |
|                                         |  [Approve as is] [Save corrections] [Reject]
+-----------------------------------------+----------------------------------------+
```

| ID | Requirement | Traces to |
|---|---|---|
| DR-UI-02 | **Layout:** two panes. Left: the page image with evidence boxes and zoom/fit controls, page switcher for multi-page. Right: fields, validation results, actions. Header shows document ID, filename, status chip, position in queue, the reason sentence, the tier that produced the shown values, and cost. | FR-REV-02 |
| DR-UI-03 | **Field ordering:** blocking-rule failures first, then lowest confidence ascending, then the rest. Confident fields are collapsed into a compact row but remain editable. | D1 |
| DR-UI-04 | **Field row:** field name, editable value input, confidence chip (band label plus number), and when relevant a one-line note (for example "T1: 1,298.00  T2: 1,180.00 (matches subtotal)"). Clicking a field highlights its evidence box; clicking a box focuses its field. | D3 |
| DR-UI-05 | **Evidence boxes** are drawn from OCR word coordinates. Color by band (green, amber, red) with the field name and number in a label so color is not the only signal. If no evidence exists: "No evidence found on the page" in the field note. | D3, D7 |
| DR-UI-06 | **Model disagreement:** when Tier 1 and Tier 2 differ, both values show under the field as click-to-adopt suggestions. Adopting sets the input value; it does not save. | D4 |
| DR-UI-07 | **Validation panel:** each rule with OK / FAIL / WARN, rule name in plain language, and the numbers involved ("Subtotal 1,180.00 + tax 118.00 = 1,298.00, printed total 1,298.00"). | D2 |
| DR-UI-08 | **Actions:** *Approve as is*, *Save corrections* (enabled only if a value changed), *Reject*. Reject requires a short reason. If a correction fails a blocking rule, show the failing rule and require an explicit "Save anyway" (maps to `acknowledge_validation_failures`). | TR-API-09 |
| DR-UI-09 | **Line items** in a collapsible table (description, qty, unit price, amount), each cell editable, with the running sum against subtotal shown. | FR-EXT-02 |
| DR-UI-10 | **Timing:** record `seconds_spent` from open to action, to compute SM-07. | SM-07 |
| DR-UI-11 | After an action, advance to the next queue item and show a brief confirmation with an **Undo** for 10 seconds (implemented as a compensating review record, never by editing history). | D5 |
| DR-UI-12 | **Keyboard shortcuts** (Could): `J`/`K` next/previous, `A` approve, `S` save, `E` focus first doubtful field, `Esc` cancel edit. Streamlit needs a small custom component for this; ship without it if it costs more than an hour. | FR-REV-05 |

### 3.3 Confidence chips

Display bands are a *presentation* choice, separate from the routing threshold.

| Band | Range (configurable) | Label | Color | Rule |
|---|---|---|---|---|
| HIGH | ≥ 0.95 | `HIGH 0.97` | Green | Text always present |
| CHECK | 0.70 to < 0.95 | `CHECK 0.82` | Amber | |
| LOW | < 0.70 | `LOW 0.41` | Red | |

| ID | Requirement |
|---|---|
| DR-UI-13 | Chip shows band label and two-decimal number. Contrast between chip text and background meets WCAG AA (4.5:1). |
| DR-UI-14 | A tooltip explains: "Estimated probability this value is correct, calibrated on labeled data." |

### 3.4 States

| State | Requirement |
|---|---|
| Loading | Skeleton for image and field list; never a blank screen |
| Image failed to load | "Could not load the page image" with a retry button; fields remain usable |
| Save failed | Inline error with the API error message and request ID; entered values are preserved |
| Concurrent edit | If the document changed state since opening, show "This document was already handled" and return to the queue |
| Degraded mode | Banner: "Tier 2 model unavailable. Documents will route here until it recovers." |

### 3.5 Accessibility and localization

| ID | Requirement |
|---|---|
| DR-UI-15 | Fully operable by keyboard for the core path (open, edit, save). Visible focus rings. |
| DR-UI-16 | Numbers and dates are displayed in the **document's** format alongside the canonical value, so reviewers can compare against the page ("1.234,56 -> 1234.56"). |
| DR-UI-17 | English only in v1; all user-visible strings live in one `messages` module so localization is possible later. |

### 3.6 Human-readable reason messages

Mapping from TRD reason codes (TRD §8.3) to the sentence shown in the header and queue.

| Code | Message |
|---|---|
| `AUTO_OK` | Accepted automatically: all checks passed. |
| `LOW_CONF:<field>` | The system is not confident about **{field}**. |
| `RULE_FAIL:R-SUM-02` | Subtotal plus tax does not equal the total. |
| `RULE_FAIL:R-SUM-01` | Line items do not add up to the subtotal. |
| `RULE_FAIL:R-DATE-01` | The date looks implausible. |
| `RULE_FAIL:R-REQ-01` | A required field is missing. |
| `UNGROUNDED:<field>` | **{field}** could not be found on the page. It may have been guessed. |
| `TIER_DISAGREE:<field>` | Two models disagree on **{field}**. |
| `SCHEMA_INVALID` | The model's answer was malformed. |
| `TIER2_UNAVAILABLE` | The stronger model was unavailable. |
| `COST_CAP_EXCEEDED` | Processing hit the per-document cost limit. |
| `OCR_UNAVAILABLE` | Text recognition failed; values could not be checked against the page. |
| `LOW_IMAGE_QUALITY` | The image is too blurry or small to read. |
| `POSSIBLE_DUPLICATE` | This looks like an invoice already processed. |

## 4. S3: Document detail and audit

| ID | Requirement |
|---|---|
| DR-UI-20 | Timeline of `audit_log` events: time, actor, event, and a one-line summary (stage, tier, decision, reviewer). |
| DR-UI-21 | Side-by-side of Tier 1 and Tier 2 normalized values, validation results, and field scores. |
| DR-UI-22 | A **versions** block (git SHA, prompt ID, model versions, threshold version) and a link to the trace. |
| DR-UI-23 | Raw values are hidden behind a "show values" toggle that respects `DEBUG_PII`; default shows values only inside the authenticated UI, never in exported logs. |

## 5. S4: Operator dashboard

Three panels plus summary tiles. Values below are layout only.

| ID | Requirement |
|---|---|
| DR-UI-30 | **Summary tiles:** documents today, auto-accepted %, in review queue, cost per document, p95 latency. |
| DR-UI-31 | **Operations panel:** throughput, latency by stage, cost per document per day, error and schema-failure rates. |
| DR-UI-32 | **Quality-proxy panel:** correction rate per field, confidence distribution per field, route mix over time (auto / escalated / review). A drifting field is called out in text ("total confidence falling 5 days"). |
| DR-UI-33 | **Queue panel:** backlog size, age of oldest item, median time to review. |
| DR-UI-34 | Every chart states its window and denominator (for example "last 7 days, n = 212"). Small n (< 30) shows a "low sample" note. |

## 6. Notification design

Channel: Telegram or Slack (via n8n). Messages are short, contain a reason and a link, and never contain full invoice contents.

**NEEDS_REVIEW**

```
Review needed: doc_7f3a91
Why: Two models disagree on total (confidence 0.41)
Waiting since 14:02   Source: email
Open: http://localhost:8501/?doc=doc_7f3a91
```

**REJECTED_UNREADABLE** (to the operator by default)

```
Could not read: vendor_invoice_0418.jpg
Why: image too blurry or small
Suggested action: ask the sender for a clearer copy
```

**Optional sender reply** (`NOTIFY_SENDER=false` by default)

```
Subject: We could not read your invoice
Hello, we could not read the attached file (it looks blurry or very small).
Could you resend a clearer scan or a PDF copy? Thank you.
```

| ID | Requirement |
|---|---|
| DR-NTF-01 | Sender replies are **off by default**. When on: never reply to automated mail (`Auto-Submitted` header, `Precedence: bulk`, no-reply addresses), and cap at one reply per sender per 24 hours, to prevent auto-reply loops. |
| DR-NTF-02 | Notification text is generated from reason codes via the same message table as the UI (§3.6). |
| DR-NTF-03 | Notifications are rate-limited: when more than 10 documents need review within 10 minutes, send one digest instead of individual messages. |

## 7. n8n workflow design

n8n is transport only (ADR-005). No prompts, thresholds or business rules live in it.

| ID | Requirement |
|---|---|
| DR-WF-01 | **Workflow A, intake:** Email trigger (IMAP) → filter (PDF/JPEG/PNG only; skip inline signature images below 30 KB; skip auto-generated mail) → HTTP Request `POST /v1/documents` with `callback_url` pointing at Workflow B's webhook and `external_ref` = email message ID → done. |
| DR-WF-02 | **Workflow B, status callbacks:** Webhook node (verifies HMAC signature and timestamp) → IF on `status` → branches: AUTO_ACCEPTED or APPROVED or CORRECTED → append to Google Sheet or write CSV → HTTP Request `POST /export-ack`; NEEDS_REVIEW → Telegram/Slack message; REJECTED_UNREADABLE → operator notice (and optional sender reply); FAILED → operator alert. |
| DR-WF-03 | Every HTTP node has retry on failure (3 tries, exponential backoff) and an **error workflow** that notifies the operator. |
| DR-WF-04 | Workflows are exported to `n8n/*.json` and committed. Credentials are never in the export (n8n credential IDs only). |
| DR-WF-05 | Idempotency: Workflow B de-duplicates on `delivery_id` (for example a Sheets lookup or a small key-value store) before writing a row. |
| DR-WF-06 | Sheet columns fixed and documented: `document_id, exported_at, vendor_name, invoice_number, invoice_date, currency, subtotal, tax_total, total, status, route_reason, reviewer`. Line items export as a separate sheet keyed by `document_id`. |

## 8. API design conventions

| ID | Convention |
|---|---|
| DR-API-01 | Resource-oriented nouns, plural (`/documents`), verbs only for actions on a resource (`/review`, `/export-ack`). |
| DR-API-02 | JSON keys are `snake_case`. Timestamps are ISO 8601 UTC with `Z`. IDs are opaque prefixed strings (`doc_`), never sequential integers. |
| DR-API-03 | Money and quantities are **strings** in JSON, with a fixed decimal scale of 2 for money. |
| DR-API-04 | Every response carries `request_id` (header `X-Request-ID`); errors follow TR-API-05; error codes are UPPER_SNAKE and never change meaning. |
| DR-API-05 | The result object is **additive-only** within `/v1`: new fields may appear, existing fields never change type or meaning. Breaking changes require `/v2`. |
| DR-API-06 | Field object shape is uniform: `{"value", "p_correct", "evidence"?}`. Absent values are `null`, never empty strings. |
| DR-API-07 | Each document result includes `schema_version` and the `versions` block. |
| DR-API-08 | Long-running work is asynchronous: `POST` returns 202 and a `document_id`; clients poll `GET` or use the webhook. No long-held HTTP requests. |

## 9. Design decisions

Short, UI-level decisions (system-level ones are ADRs in `04_Architecture`).

| ID | Decision | Alternatives considered | Reason |
|---|---|---|---|
| DD-01 | Streamlit for the review UI in v1 | React + FastAPI | Speed; reviewers are a handful, not thousands. Revisit only if shortcuts and latency become blockers. |
| DD-02 | Two-pane layout with linked highlighting | Single column form | Evidence next to the value is the main efficiency gain. |
| DD-03 | Flag doubtful fields first, do not hide confident ones | Hide confident fields | Hiding creates automation bias; a wrong-but-confident field must still be one glance away. |
| DD-04 | Undo implemented as a compensating record | Editing history | The audit trail is append-only. |
| DD-05 | Canonical value shown next to the printed format | Canonical only | Reviewers compare with the page; locale confusion is a real error class. |

## 10. Design acceptance checklist

- [ ] S1 to S4 implemented per the wireframes; empty, loading and error states exist
- [ ] Every reason code has a message (§3.6), covered by a unit test that iterates the code catalog
- [ ] Chips show text and number; contrast checked
- [ ] A reviewer completes open → fix one field → save with mouse only in ≤ 3 clicks after opening
- [ ] Notification templates render from the same message table
- [ ] n8n workflows exported to `n8n/`, importable on a clean instance, no credentials inside
- [ ] SM-07 timing data is being recorded
