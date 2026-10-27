  - **Not done yet**: the publish gate's **second reader** (independent OCR) and **independent AI solve** (§21.3), so nothing is live. The extra 650 questions below are not yet tagged with topics (only the 520 from 2022–2026 are).
- **Paper ingestion, extended to 2013, 2014, 2016 and 2018**: **650 more questions** (18 sittings and **1,170 questions** in total), each with its official key, all as `draft`. Every sitting shows 65 parsed, 65 keyed and `publishable`; none is live.
  - **What was needed beyond the modern papers**: the file holds several sets (2013: booklets A–D; 2014: three sessions; 2016: two GA sets), so the tool cuts the file into sittings by page; the answer-key pages printed inside the files are skipped; numbering restarts for the CS part in 2014, 2016 and 2018 (GA is slots 1–10, CS is printed number + 10); options can sit inline on one row (`(A) x (B) y ...`) and must come in order A–D; "Common Data" / "Linked Answer" blocks are copied into every question they name (2013); 2013 writes its headers as `Q.1 to Q.25`.
  - **Text is unreliable in 2013 and 2014**: formulas are images and a large diagonal watermark sits in the text layer, so **all 455 questions are shown from the page image** (`display = image`, flag `text_layer_unreliable`). Their option count is a flag, not a refusal (one 2014 option label is an image). Checked by eye: a 2013 common-data crop, a 2014 crop with set notation. Elsewhere the text is usable: 2018 (38 of 65 as text), 2016 (76 of 130).
  - **Independent key check**: the 2014 papers contain their own printed answer key. All **195 answers match** the separately downloaded key file, which also confirms the set order (SET-1/2/3 = CS1/CS2/CS3).
  - **Regressions caught while extending**: lowering the page-header cutoff made 2025's repeated page header look like a section header and cut a question short. It is now matched as a running header, and 2022–2026 pass unchanged.
  - **Still not ingested**: **2015 and 2017** are scans with no text layer (OCR needed; `tesseract` is installed on this machine), as are 2007–2011, 2019 and 2021. 2020 and 2012 have text layers but need their own layouts (2012 has no key).
# aceIt — System Design (v0.1, GATE-first)

## 0. Decisions locked (v0.2)

| # | Decision | Consequence in this design |
|---|---|---|
| 1 | **GATE CS only** at launch | One taxonomy, one blueprint, and one normalisation model. The data model stays multi-paper |
| 2 | **Inputs are GATE PYQ question papers (no keys inside the PDFs).** Official GATE answer keys are public, so they are imported separately | Keys come from the official source. LLM solving is only a fallback and a solution-writer. See §7.1 |
| 2b | **We have an in-house expert reviewer team** to resolve disputes | A reviewer role and queues (§7.2) replace the "maybe one editor" assumption |
| 2c | **PDFs are scanned**, we have papers for almost all years, **no answer keys yet** | Vision-LLM page reading becomes the primary extractor (§7). Key sourcing is a Phase 0 task (§7.1) |
| 2d | **One reviewer, 24 h turnaround** | Ingestion is throttled to reviewer capacity, key overrides are approved by the admin, and the launch scope is a subset of years (§7.2) |
| 3 | **Free for students** | No payments, plans or entitlements in v1. Cost control moves to rate limits, a per-user daily test cap and a Bedrock budget cap |
| 4 | **On-demand tests only** | No scheduled live windows, so no pre-warming. Load is spread out. Rank is a rolling percentile against everyone who has already taken that test |
| 5 | **English only** | No i18n layer. UI strings are still kept in one file |
| 6 | **FastAPI (Python 3.12)** | One language for API, ingestion workers and analytics |
| 7 | **AWS ap-south-1 (Mumbai)** | Single region, Multi-AZ. Cross-region backup copy goes to ap-southeast-1 (Singapore) |

## 1. Goal and scope

aceIt is a timed mock-test and analytics platform for GATE aspirants.

- **Content**: our team uploads question-bank PDFs. The system turns them into a structured, tagged question bank.
- **Exam fidelity**: tests mirror the real GATE format, learned from analysing PYQs (previous-year questions) per paper.
- **Experience**: a GATE-style exam console with a hard, server-enforced timer.
- **Insight**: deep post-test analysis, with weak-topic detection and a practice loop.
- **Hosting**: AWS.

**Out of scope for v1**: other exams (design for them, don't build them), live classes, video content, a native mobile app (the web app must be mobile-responsive), a social or community feed.

## 2. GATE facts the system must encode

These live in data (the exam blueprint), never in code, so other exams can be added later.

| Item | Value |
|---|---|
| Duration | 180 min (extra time for PwD candidates) |
| Questions | 65 questions, 100 marks |
| Sections | General Aptitude (GA): 10 questions, 15 marks (5×1 + 5×2). Subject: 55 questions, 85 marks (Engineering Maths is part of this for most papers) |
| Question types | MCQ (1 correct), MSQ (≥1 correct, no partial marks), NAT (numerical answer, with a tolerance range) |
| Negative marking | MCQ only: −1/3 on 1-mark questions, −2/3 on 2-mark questions. No negative marking for MSQ or NAT |
| Tools | Virtual scientific calculator. NAT answers are typed on an on-screen keypad |
| Console | Question palette with states: not visited, not answered, answered, marked for review, answered and marked. Section switching is free |
| Scoring | Marks, then a normalised score for multi-session papers (CS, ME, EE, EC, CE). Rank (AIR) and percentile estimated against our own cohort |

Everything above sits in one `exam_blueprint` JSON per paper (CS, DA, EC, EE, ME, CE, ...), versioned by year.

## 3. Learning from the market (ideas, not copies)

| Platform category | Idea we take | How aceIt does it differently |
|---|---|---|
| Testbook, BYJU'S Exam Prep, Unacademy | Real-exam-like console, all-India rank, topic-wise tests | Rank/percentile is computed from our cohort with explicit confidence labels. Test blueprints are derived from PYQ stats, not hand-set |
| GATE Overflow, community banks | Per-question discussion, PYQ tagged by topic | Moderated explanations only in v1. Topic tags come from the ingestion pipeline plus human review |
| Coaching test series (ACE, Made Easy) | Full-length, subject-wise and topic-wise ladder | Auto-generated "next test" based on the student's weak topics |
| Duolingo and Anki | Streaks, spaced repetition | Revision queue re-surfaces wrongly answered questions on a spaced schedule |
| Adaptive engines (Khan, Magoosh) | Mastery model per topic | Simple Bayesian or Elo mastery per (student, topic). Full IRT is deferred |

## 4. Users and roles

- **Student**: takes tests, reviews results, practises.
- **Reviewer / reviewer lead**: our in-house experts. They work the queues in §7.2 (extraction, key disputes, solutions, student reports).
- **Admin**: uploads PDFs, manages exams, blueprints, test series, users and pricing.
- **Support** (later): read-only access to a student's attempts for debugging.

## 5. Feature set

### 5.1 Student-facing
1. **Onboarding**: pick the target exam and paper (CS, ...), the target year, and the weak/strong subjects (self-reported).
2. **Test types**:
   - Full mock: exact blueprint, 180 minutes.
   - Subject test: all topics within one subject.
   - Topic or chapter test: short, with an optional timer.
   - PYQ mode: a past paper exactly as it appeared (year and session).
   - Custom test: the student picks topics, count, difficulty and type mix.
   - Auto-recommended test: built from the weak-topic profile.
   - **Topic-name test**: the student types any topic and gets a timed test on it (§20.1).
   - **My-own-PDF test**: the student uploads any question-paper PDF and is tested on it under a timer (§20.2).
3. **Exam console**:
   - Server-authoritative timer.
   - Palette, mark-for-review, clear response, section nav, calculator, rough-work notepad.
   - Autosave and resume after a disconnect.
   - Auto-submit at timeout.
   - Fullscreen and tab-switch logging in a "strict mode" flag.
4. **Result and analysis** (details in §9).
5. **Review mode**: every question with the student's answer, the correct answer, the solution, the topic, time spent and a "why wrong" tag.
6. **Practice and revision**: a wrong-answer notebook, a spaced-repetition queue, and bookmarks.
7. **Dashboard**: streak, score trend, topic heatmap, and "what to do today".
8. **Leaderboard and rank predictor**: cohort rank and percentile per test, plus an estimated GATE score band.

### 5.2 Admin and content
1. **PDF ingestion pipeline** (§7) with a review UI.
2. **Question bank manager**: search, filter, edit, deprecate, and version history.
3. **Exam and blueprint manager**: PYQ-derived blueprints, with manual override.
4. **Test builder**: create fixed tests (a published series) or define dynamic generation rules.
5. **Analytics for ops**: question quality (discrimination, difficulty drift, flagged-as-wrong rate), usage, and revenue.
6. **Question-report queue**: students flag a wrong key or a bad question, and editors resolve it.

## 6. High-level architecture (AWS)

**Principle**: start as a modular monolith plus a few workers. Split services only when a measured bottleneck demands it. Microservices on day one add cost and failure modes for no user benefit.

```
                 ┌────────────── Route 53 ──────────────┐
                 │                                      │
        CloudFront (CDN, WAF, TLS)              Admin (same app, role-gated)
         │             │                                 │
   S3: web assets    ALB ───────────────────────────────┘
   (Next.js static)    │
                       ▼
          ┌────────────────────────────┐          ┌───────────────────┐
          │ API  (ECS Fargate, N tasks) │◄────────►│ ElastiCache Redis │
          │ auth, tests, exam-session,  │          │ session state,    │
          │ results, admin              │          │ timers, rate-limit│
          └──────┬────────────┬─────────┘          └───────────────────┘
                 │            │
                 │            └──► SQS queues ──► Workers (ECS Fargate)
                 ▼                   ingest | score | analytics | email
        Aurora PostgreSQL                │
        (primary + read replica)         ├──► S3 (PDFs, extracted images, exports)
                                         ├──► Textract / Bedrock (OCR + LLM extraction)
        Cognito (auth)                   └──► SES (email)
        Secrets Manager, KMS
        CloudWatch + X-Ray, EventBridge Scheduler
```

### 6.1 Technology choices

| Layer | Choice | Why |
|---|---|---|
| Frontend | Next.js (React, TypeScript), Tailwind. KaTeX for math rendering | SSR for marketing and SEO, SPA behaviour for the console. KaTeX is fast and offline-capable |
| API | One TypeScript service (NestJS) or Python (FastAPI) | One codebase, strongly typed. Pick whichever the team knows. **Recommendation: FastAPI**, because the ingestion and analytics code is Python-heavy and sharing the language removes a boundary |
| DB | Aurora PostgreSQL | Relational integrity for attempts and scoring. JSONB for blueprints and question content. Full-text search is built in, so there is no OpenSearch in v1 |
| Cache and session | ElastiCache Redis | Exam session state, autosave buffer, leaderboards (sorted sets), rate limits |
| Queue | SQS (with DLQs) | Decouples ingestion, scoring and analytics from user-facing latency |
| Scheduler | EventBridge Scheduler | One-shot "force-submit at deadline" jobs per attempt, as a safety net behind the timer |
| Storage | S3 (versioned, SSE-KMS) | PDFs, cropped figures, and exported reports |
| Auth | Cognito (email OTP, Google sign-in) | No custom password handling. JWT is verified at the API |
| OCR and LLM | Textract, Amazon Bedrock (Claude) | Managed, no GPUs to run |
| Observability | CloudWatch logs and metrics, X-Ray, Sentry | Alarms on error rate, autosave latency and queue depth |
| IaC and CI/CD | Terraform or CDK, GitHub Actions → ECR → ECS blue/green | Reproducible environments: dev, staging, prod |
| Security edge | WAF (rate limit, bot control), Shield Standard | Weekend mock-test spikes attract abuse |
| Payments | **None in v1 (free product).** `plan` / `entitlement` / `payment` tables are deferred | Add later behind the same "can this user start this test" check |

## 7. PDF → question bank ingestion pipeline

This is the highest-risk component. PDFs are messy: two columns, math, diagrams, scanned pages. **Never auto-publish extracted content.**

```
Admin uploads PDF ─► S3 (raw/) ─► SQS:ingest
   │
   ▼
1. Classify      scanned (all our PDFs). Quality probe: resolution, skew, noise, page count
2. Page prep     each page → PNG at 300 dpi, deskew, denoise, contrast fix, de-speckle. Store originals untouched
3. Read          TWO independent readers per page: (a) vision LLM (Bedrock) reading the page image straight to Markdown + LaTeX,
                 (b) Textract for text and layout. Math and diagrams are where Textract is weak, so the vision LLM is primary.
                 Per-question agreement between (a) and (b) on the words and numbers becomes the confidence score.
4. Segment       split into question units (number markers, "(A)…(D)", "Answer:"), keep page + bbox for each
5. Structure     Bedrock LLM, one question at a time, schema-constrained JSON:
                 { stem_md, options[], type: MCQ|MSQ|NAT, marks, answer?, solution?, figures[], year?, paper? }
                 Math is emitted as LaTeX. Figures are cropped by bbox and stored in S3.
6. Tag           LLM + embedding classifier: subject → topic → subtopic (from a controlled taxonomy per paper),
                 difficulty prior, and concept tags
7. Validate      rule checks: option count matches type, NAT has a numeric answer, marks in {1,2}, LaTeX compiles in KaTeX,
                 duplicate detection (embedding similarity + normalised-text hash)
8. Review queue  every item lands as DRAFT with a confidence score and a side-by-side view (original page crop | parsed result).
                 Editors fix and approve. Low-confidence items are prioritised.
9. Publish       status → ACTIVE and versioned. Immutable once used in a published test (edits create a new version).
```

Design rules:
- **Idempotent and resumable per page**: a retry never duplicates questions. Every record keeps `source_pdf_id`, page and bbox.
- **Answer keys**: see §7.1. Our PDFs have none, so keys are produced and graded by trust level.
- **Taxonomy** is a managed table (`topic`, with parent and paper mapping), seeded from the official GATE syllabus.
- **Scanned-input rules**: scans are the hardest case, so every page keeps its source image, and the reviewer UI always shows the original crop beside the parsed text. Figures and circuit/graph diagrams are cropped, not transcribed. Digits, signs, subscripts and option letters get an extra check (the two readers must agree character-for-character, or the question is flagged). A 5-page sample from each year is read first to catch bad scans early.
- **Cost control**: about 20 pages per paper × roughly 25 paper-sessions is only ~500 pages, so a one-off vision-LLM pass is cheap. Cache by page hash so a re-run costs nothing.
- Start with a golden set (about 100 questions across 3 different years, hand-verified by the reviewer) to measure extraction accuracy before scaling up. Do not ingest the rest until the character-level accuracy on this set is acceptable.

### 7.1 Answer keys when the PDFs have none

All inputs are GATE PYQs, so the **official answer key** exists for every question. It is the source of truth. Keys are imported from the official key files (paper, year, session/set) and matched by question number.

`key_status` values:

| key_status | Meaning | Scored? |
|---|---|---|
| `OFFICIAL` | Matches the final official key (single answer, a set for MSQ, or a numeric range for NAT) | Yes |
| `OFFICIAL_MTA` | The official key gives marks to all candidates (question flawed). Recorded as such | Yes, everyone gets the marks |
| `OFFICIAL_DROPPED` | Official key says the question was dropped or cancelled | No. Kept for reference, excluded from tests |
| `REVIEWER_VERIFIED` | A reviewer resolved a mismatch or a missing key (§7.2) | Yes |
| `DISPUTED` | Parsed key and the AI check disagree, or a mapping problem exists. Waiting for a reviewer | No |

**Sourcing the final keys (Phase 0 task, owner: you).** The keys are not in the PDFs, and you do not have them yet. The organising IIT's GATE site for each year publishes the answer key, and the key marked **final** is the one to use. Collect one key file per `(year, session)`, keep the original file in S3 untouched, and record the source link and download date. I have not verified where each year's final key is hosted, so the first step is a short sourcing sheet listing every year and session, the key file found, and whether it is provisional or final. I can search for these and build that sheet if you want.

**If a year's final key cannot be found**, the fallback is a visible one:
- Import whatever key exists as `PROVISIONAL` and run the AI cross-check on every question.
- A paper-year with only `PROVISIONAL` keys is **practice-only** and labelled "Key not final", and it is excluded from full mocks, rank and percentile.
- Questions where the provisional key and the AI disagree go to the reviewer, who decides.
- Add this status to the table: `PROVISIONAL` (official key exists but is not confirmed final), not scored in rank-bearing tests.

Import details:
- **Use the final key, not the provisional one.** The organising IIT publishes a provisional key, accepts challenges, then a final key. Store which one was imported, and `OFFICIAL` means final only.
- **Session mapping**: CS has multiple sessions (sets) per year, and the question order differs between them. The key file is per session, so the import is keyed by `(paper, year, session)`. Our PDFs must be tagged with their session at upload, and an upload without it is rejected.
- **NAT ranges and MSQ sets** are stored as structured values, not strings. NAT scoring uses the official range.
- **Match check**: after import, every question must have exactly one key. A count mismatch (for example 64 keys for 65 questions) blocks publishing that paper.
- **Key-history table**: every key change is recorded, and a change triggers a re-score of past attempts (§7.2).

**AI cross-check (cheap safety net, not the source of truth).** For every question the LLM solves independently, with code execution for numeric problems:
- If the AI agrees with the official key, nothing happens.
- If it disagrees, the question is flagged `DISPUTED` for a reviewer. This catches **OCR and parsing errors** (for example a misread option or a wrong digit in the stem), and the occasional wrong official key. A disagreement is a signal, not a verdict.

**Solutions.** GATE does not publish worked solutions. The LLM writes one for each question, but **only a solution whose final answer matches the official key is kept**. If 5 attempts cannot reproduce the official answer, the question goes to a reviewer for a manual solution. Each solution carries a label: "AI-generated" or "Reviewer-written". Solutions are written once, offline, and stored. No LLM call happens in a student's request path.

**Cost**: about 1 extraction, 1 tagging, and up to 5 solve calls per question. With only PYQs the bank is bounded (about 65 questions × the years of papers), so this is a one-off cost and small. Still set a monthly cap.

### 7.2 Reviewer system (our expert team)

> **Update (§21):** the platform must run with **no human in the loop**. The reviewer is an optional quality boost. Nothing below blocks test creation, conduct or scoring, and the 24-hour SLA and admin-approval steps apply only when a reviewer exists.

The reviewer role resolves every anomaly. It is a first-class part of the product, with its own queues, in the admin app.

| Queue | What lands here | Reviewer action |
|---|---|---|
| **Extraction review** | Low-confidence parses, OCR doubts, figure crops, LaTeX that fails to render | Fix the stem, options, figures and tags, then approve |
| **Key disputes** | AI vs official-key mismatch, key-count mismatch, missing session key | Decide the correct key (with a written reason), or confirm the official key stands |
| **Solution review** | Questions where the AI could not reproduce the official answer | Write or fix the solution |
| **Student reports** | "Wrong key", "unclear question", "typo" from students | Triage: reject, fix, or escalate to a key dispute |
| **Quality flags** | Questions with negative discrimination or an unusual solve rate | Investigate and decide |

Workflow rules:
- Every queue item has an **owner, status, SLA timer, and a reason field**. All decisions go to the `audit_log` and `question_key_history`.
- **Approval for key changes (single-reviewer setup).** With one reviewer there is no second reviewer, so the reviewer **proposes** a key override with a written reason and the **admin approves** it in one click. No override takes effect without both. When the team grows, this becomes the two-reviewer rule.
- **Re-scoring**: an approved key change triggers a background job that re-scores every affected attempt, updates ranks and percentiles, and notifies the students concerned. The result page shows "This question's key was corrected on <date>".
- **Auto-hold**: a question with ≥3 independent student reports in 7 days is hidden from new generated tests until reviewed, but stays in attempts already started.
- **Reviewer tooling**: side-by-side original page crop vs parsed question, the official key and the AI answers with their reasoning, and one-click actions. Keyboard-first, since reviewers process hundreds of items.
- **Roles**: `reviewer` (resolves items) and `admin` (approves key overrides, assigns roles). `reviewer_lead` is added when there is more than one reviewer.
- **24-hour SLA, single reviewer**: the SLA applies to student reports and key disputes on live content, and these go to the top of the queue. Extraction review is a separate backlog worked in batches. A SLA breach alerts the admin. Plan a named backup (even part-time) so one absence does not stall the platform.

**Reviewer capacity and launch scope.** There are roughly 25 paper-sessions of 65 questions each, about 1,600 questions. Reviewing every one costs roughly 25 minutes per 65-question paper if the parse is clean and the reviewer only confirms (about 20 s per question), and more for flagged questions. Plan for about 2–3 weeks of part-time reviewer work for the full set. So:
- Ingestion is **throttled**: only as many papers enter the review queue as the reviewer can clear, a few papers per week.
- **Launch with a subset** (for example the 8–10 most recent years that have confirmed final keys), publish more years as they clear review.
- Questions whose two readers agree and whose AI check agrees with the official key are shown in a fast **"confirm"** lane. Everything else is in the slower **"fix"** lane. Nothing is published without the reviewer's confirmation.

**Rights note**: GATE papers are copyrighted by the organising IIT, and the earlier "our IP" assumption in §13 applies only to what we author (solutions, tags, analytics). Please confirm you are cleared to reuse the PYQ papers on a public platform before launch.

### 7.3 Source files collected (status as of 2026-10-22)

The per-year detail is in [pyq-sourcing-sheet.csv](pyq-sourcing-sheet.csv). The files are in `~/Downloads/GATE/pyq/` (a local working copy, not yet in S3).

- **Papers**: all CS papers 2007–2026 (official bulk archive, 24 PDFs). 2007–2011, 2019 and 2021 are scans. The rest have a text layer (to be spot-checked).
- **Keys found**: 2013–2026 (14 years). 2022–2026 are text PDFs that parse directly. Keys for 2013–2019 are Internet Archive copies of the official organisers' files.
- **Key import status**: official keys for **2013, 2014 and 2016–2026 (22 files, 1,430 answers)** are parsed by [../tools/import_keys.py](../tools/import_keys.py) into the `official_key_entry` table. The importer **refuses** any file that does not have exactly 65 questions, 100 marks and 10 GA questions, and it handles four layouts (one row per question; two tables side by side in 2014; four paper-code columns in 2013; GA listed last in 2017), marks-to-all (`MTA`, including the spelled-out "Marks to All" of 2013), keys that accept two answers, and numbering that restarts for the CS section (2018–2020).
  - **Caveats**: (1) the 2013 key has no marks or type column, so marks follow the standard 2013 layout and types come from the answer's shape. The 100-mark total checks it, but it is an inference and the real paper must confirm it. (2) 2013 is four sittings (`CS-A` to `CS-D`, the four paper codes, each a different question order), and each has 2 marks-to-all questions. (3) 2014's CS1/CS2/CS3 are matched to exam sessions 7/8/9 by file name.
  - **Not importable as text**: **2015** (the key files are scans with the MCQ answers inside images; only the NAT answers are text) and **2021** (a scan). Both need OCR.
- **Topic list**: the GATE CS taxonomy is built from the official syllabus ([../data/taxonomy/gate_cs.json](../data/taxonomy/gate_cs.json), loaded by [../tools/load_taxonomy.py](../tools/load_taxonomy.py)): **12 subjects, 62 topics, 56 subtopics, 620 aliases** (originally 11, 59, 56, 594; grown by the General Aptitude additions and the out-of-syllabus subject). The loader refuses to produce anything unless every topic name appears in the syllabus PDF text, every meaningful syllabus word is covered by some topic, and no alias points to two topics. Two exceptions are flagged in the data: **General Aptitude** is not in the syllabus PDF (it is general GATE knowledge, to be verified), and a few grouping labels (`Data structures`, `Graph algorithms`) are marked `derived`. Aliases are stored **normalised** (lowercase, punctuation to spaces), so the topic resolver (§20.1) must normalise what the student types the same way (`banker's algorithm` becomes `banker s algorithm`). Exact alias match is the first step. Fuzzy and embedding match come after it.
- **Paper ingestion status (text-layer papers, 2022–2026)**: **520 questions** (8 sittings × 65) are ingested by [../tools/ingest_papers.py](../tools/ingest_papers.py) as `draft`, each with its official key attached. All 8 sittings show 65 parsed, 65 keyed and `publishable`, and **0 are visible to students**, because publishing is the gate's job (§21.3), not the importer's.
  - **How a paper is read**: word positions from the PDF text layer locate every question; each question is also cut out of the page as a PNG (595 images, about 55 MB, in `pyq/ingest/`) because maths does not survive text extraction (checked: `L1, L2, L3` came out as `L , L ... 1 2 3`). The tool **refuses** a paper unless it finds exactly questions 1–65, and each question's type, option count (4 for MCQ/MSQ, none for NAT) and marks agree with the official key.
  - **Display mode per question**: 204 are text-clean (`display = text`). 316 contain maths symbols, stacked fractions, figures or other doubts and are shown as the **original image** (`display = image`). Crops contain the faint GATE page watermark, as in the original.
  - **Boundary fixes found while tagging**: some papers print the `Q.n` marker lower than, or centred on, its own stem (2024 CS2 Q38, Q11, Q42), which put stem lines under the wrong question. The segmenter now pulls contiguous stem lines above a marker into that question, and a new `stem_start_unclear` flag marks any stem that begins mid-sentence. Only 2 stems (both legitimate) still start in lowercase.
  - **Not done yet**: the publish gate's **second reader** (independent OCR) and **independent AI solve** (§21.3), so nothing is live. Questions are not yet tagged with topics. Papers for 2012–2018 (text layer) are ready for the same tool once their layouts are added (2018–2020 restart numbering in the CS section; 2013's four paper codes), and the scanned papers (2007–2011, 2019, 2021) need OCR.
- **Topic tags (2022–2026)**: all **520 questions** carry a primary topic from the syllabus taxonomy, in [../data/tags/gate_cs_2022_2026.txt](../data/tags/gate_cs_2022_2026.txt), loaded by [../tools/load_tags.py](../tools/load_tags.py) into `question_topic` (5 also have a second topic). The loader refuses any unknown or ambiguous topic name, any sitting that is not exactly questions 1–65, and any aptitude question tagged with a subject topic or the reverse (the section comes from the official key). 72 tags are marked low-confidence (`?`, stored as 0.5) and 11 are tagged only at subject level because no specific syllabus topic fits (3 Compiler Design, 2 each Algorithms, COA, Maths, 1 each Networks, Databases).
  - **What these labels are, and are not**: they were written by Claude reading each question against the syllabus (source `claude-bootstrap`). They have **not** been independently checked, and where the extracted text was garbled by maths I tagged from what was readable. They are good enough to drive topic tests and to give a first topic analysis, and they are the **training and test set** for the automatic tagger the pipeline needs (§7). Before relying on them for student-facing analytics, check a random sample (about 50 questions) against the page images, and measure the automatic tagger against all 520.
  - **Sanity check**: marks per subject are plausible for GATE CS in every sitting (aptitude exactly 15, maths 12–19, algorithms 4–10, and so on), and "test by topic name" works end to end: `dp` resolves through the alias table to the two dynamic-programming questions.
- **Topic tags, extended to 2013–2018**: all **1,170 questions** now carry a primary topic ([../data/tags/gate_cs_2013_2018.txt](../data/tags/gate_cs_2013_2018.txt); the loader reads every `data/tags/gate_cs_*.txt`). Of these, 195 tags are low-confidence (17%) and 33 questions are tagged only at subject level (10 Networks, 9 Algorithms, 6 Compiler Design, 5 COA, 2 Maths, 1 Databases).
  - **Old syllabus content**: 11 questions (Software Engineering, in the 2013 and 2014 papers) are not in today's syllabus. They are tagged under a new explicit subject, `Out of Current Syllabus`, rather than forced into a wrong topic. Test generation should exclude that subject.
  - **2013 tagged once, carried three times**: booklets A–D hold the same 65 questions in different orders, so booklet A was read and its tags were carried to B, C and D by [../tools/map_booklets.py](../tools/map_booklets.py), which pairs questions one-to-one by text (rare words count for more, so paired "common data" questions are told apart) and refuses unless marks and question type also agree. All 195 pairings verified (mean similarity 0.98, lowest 0.66). The lower scores came from stray page-header text on one side, and the pairs were checked by eye.
  - **Same caveat as before**: bootstrap labels written by Claude, not independently checked. 2014's text is partly lost (formulas are images), so some 2014 tags rest on a partly readable stem.
- **Final status confirmed**: only **2024** (heading says Final) and **2016** (IISc folder is named final). All others are `UNCONFIRMED` until the reviewer checks them against the importing rules in §7.1.
- **Missing keys**: **2007–2012** (6 years). Not on any official page we could reach. GateOverflow was ruled out: its robots.txt disallows Claude's crawlers and it sits behind a bot check, so it is **not** to be scraped by us. Decision: rebuild keys with AI consensus plus full reviewer verification, practice-only (§7.4).
- **Launch set (recommendation)**: **2022–2026**. Both papers and keys are text PDFs, the keys are the easiest to parse, and the years are the most relevant to current students. 2013–2019 follow next, and the scanned years (2007–2011, 2021) come last.
- **Known quirks**: the 2013 key is organised by ORS code (A–D), so questions are matched by code. 2022 and 2023 have two different copies of the paper (direct download vs bulk archive) that must be compared. The 2015 key files are 24–27 pages each and need inspection.

### 7.4 Reconstructed keys for GATE CS 2007–2012 (decision: AI consensus + full reviewer verification)

> **Status: held back (§21.6).** These six years are not published. This section is the route back in, used only when a person is available to verify them or an official key is found.

No official key could be sourced for these six years (§7.3), so the keys are rebuilt and **every question is checked by the reviewer**.

**Pipeline**
1. Extract the questions (2007–2011 are scans, 2012 has a text layer) through the normal ingestion flow (§7) and the reviewer's extraction check.
2. **AI consensus**: the LLM solves each question 5 independent times, with code execution for numeric problems. At least 4 of 5 must agree. Otherwise the question is `DISPUTED`. All questions, agreed or not, go to the reviewer.
3. **Blind-first review**: the reviewer sees the question and records their own answer **before** the AI answer is revealed, which avoids anchoring on the AI. If the reviewer and the AI agree, the key is confirmed. If they differ, the reviewer re-solves and decides, with a written reason.
4. The confirmed key gets `key_status = REVIEWER_VERIFIED` and the paper gets `key_provenance = ai_reconstructed`.

**Rules for these papers**
- **Practice-only**: `rank_eligible = false` at paper level. They never feed ranks, percentiles, cohort comparisons or the mastery model's calibration. They are shown with the label "Key reconstructed (AI + expert review), practice only".
- **Never visible before review**: an `AI_CONSENSUS` key that the reviewer has not verified is hidden from students entirely.
- **Format differences**: older papers use different formats and marking from today's GATE (for example linked-answer question pairs, no MSQ or NAT questions, different negative marking). The blueprint is versioned by year (§2), so each old paper is shown in **PYQ mode only** with its own marking scheme. It is never mixed into generated mocks. The exact per-year question counts and marking rules are to be read from the papers during extraction.
- **If an official key turns up later**, it replaces the reconstructed one. Any differences go to the reviewer, and attempts are re-scored (§7.2).

**Measure before trusting it**: run the same consensus method blind on about 200 questions from years that have official keys (for example 2018–2020) and compare. That gives the AI's real accuracy by topic and how often the reviewer corrects it. Do this before starting the 2007–2012 review, so the reviewer knows which topics deserve extra care.

**Scheduling**: this is about 390+ questions (the real count comes from the papers), which at 3–5 minutes each is roughly 20–30 hours of the single reviewer's time. It is a **post-launch backlog**: the reviewer first clears the 2022–2026 launch set, then 2013–2021, and then these six years. It never competes with the 24-hour SLA on live student reports (§7.2).

## 8. PYQ pattern analysis and test generation

### 8.1 Blueprint derivation (offline job)
For each paper, over the PYQ years:
- Marks per subject and per topic, with the average and the trend (recent years weighted higher).
- Split of MCQ / MSQ / NAT and of 1-mark / 2-mark questions.
- GA vs subject split, and difficulty distribution (from the empirical solve rate where PYQ data exists, otherwise from the tagging prior).
- Output: a **blueprint** with `topic → (min, target, max)` marks, type mix and difficulty mix. Editors can override it.

### 8.2 Test assembly (online, deterministic)
Constraint-based selection:
1. Start from the blueprint (full mock) or the user's custom parameters.
2. Candidate pool = ACTIVE questions for that paper, excluding questions the student has already seen (where possible).
3. Greedy fill with randomisation: satisfy the marks per topic, then the type mix, then difficulty. If the pool is thin, relax in order (difficulty first, then topic bounds) and log it.
4. Freeze the result as a `test_instance` (the question IDs and versions). Fixed series tests are pre-built and shared. Generated tests are per-student.
5. Pool-health alarm: warn admins when any topic's pool is too small for N tests.

### 8.3 Difficulty calibration
After enough attempts, update each question's difficulty and discrimination from real data (a 2-parameter IRT-lite or a simple solve rate adjusted for ability). Flag questions with negative discrimination as probable bad keys.

## 9. Performance analysis (the product's core value)

Computed asynchronously on submit, and the result page shows instantly from the scoring step.

**Scoring step (synchronous, under 2 seconds)**: marks per question using the type rules, negative marking, and total, section and subject scores.

**Analysis step (async worker)**:
- **Topic and subtopic accuracy**, with the attempt rate and marks lost.
- **Time analysis**: time per question versus the peer median, with a "too slow", "rushed" or "ideal" label. Time spent per section.
- **Attempt strategy**: order of attempts, skipped-then-returned questions, marked-for-review usage, and last-30-minutes behaviour.
- **Error taxonomy**: wrong versus unattempted. Negative-mark loss. A guess-likelihood flag (answered fast and wrong). Concept versus calculation versus silly-mistake tagging, where the student self-tags it in review.
- **Cohort comparison**: rank, percentile, a score histogram, and topper versus you on each topic.
- **Mastery model** per topic: Elo or Bayesian update after every attempt, with trend arrows.
- **Predicted GATE score band** from the mastery profile and the blueprint weights, with an honest uncertainty range.
- **Action plan**: top 3 topics by `expected marks gained per hour`, a recommended next test, and revision-queue items.

**Normalisation**: for multi-session papers, apply a GATE-style normalisation to the cohort's raw marks to *estimate* a normalised score. This is clearly labelled an estimate.

## 10. Exam session engine (the part that must not fail)

### 10.1 Rules
1. **Server owns time**. At start, the server writes `started_at` and `deadline_at = started_at + duration (+ accommodations)`. The client timer is a display only and re-syncs on every request using server time.
2. **Autosave**: the client batches changes and sends them every 5–10 seconds, and immediately on question change. Each payload carries `{question_id, response, status, time_spent_delta, client_seq}`. The server dedupes by `client_seq`, so retries are safe.
3. **Hot state in Redis**: `attempt:{id}` holds responses and palette state. The write path is Redis only. It is flushed to Postgres every 30 seconds, and again on submit, by a background flusher. A crashed task loses at most the last flush, and Redis persistence (AOF everysec, Multi-AZ) bounds that further.
4. **Resume**: reload or reconnect returns the saved state and the remaining server time. One active session per attempt (a new device takes over and the old one is told).
5. **Submit**: the student clicks Submit, or the deadline passes. Submission is idempotent. A per-attempt EventBridge one-shot at `deadline_at + grace(30s)` force-submits abandoned attempts, so a student who closes the tab still gets a scored attempt.
6. **Grace and fairness**: if the server was unreachable around the deadline, accept the final batch whose `client_ts` is under `deadline_at + 30s` and flag it for audit.
7. **Integrity (optional per test)**: fullscreen enforcement, tab-blur counting, copy/paste disabled, and per-question time logging. These are signals for review, not auto-bans.

### 10.2 Load plan
Tests are on-demand, so there is no synchronized start. Design point for v1: **5k concurrent examinees** (weekend evenings cluster), with autosave every 8 seconds, so about 600 writes/sec at peak. Design headroom is 4× that (20k).
- Redis handles this easily. The API tier is stateless on Fargate behind the ALB, with autoscaling on CPU and request count.
- No pre-warming is needed. Keep a minimum of 2 tasks across 2 AZs, and scale on request rate.
- Question payloads for a test are **pre-packaged to S3/CloudFront** as one signed JSON per `test_instance`, with answers excluded. The exam start is then a CDN fetch, not 65 DB reads.
- Answer keys never reach the client during the exam.
- Use RDS Proxy for Postgres connections. Scoring on submit is a queue-buffered worker, so a thundering herd at 3:00 pm doesn't hit the DB directly.
- Load-test with k6 at 2× target before launch.

## 11. Data model (core tables, PostgreSQL)

> **Implemented draft:** [../db/schema.sql](../db/schema.sql) (the question bank, keys, tests and attempts, plus the visibility views), [../db/seed_paper_sessions.sql](../db/seed_paper_sessions.sql) (all 30 GATE CS sittings we hold) and [../db/tests/invariants.sql](../db/tests/invariants.sql) (21 rule checks). The sketch below is the earlier overview and the SQL is authoritative.

```
users(id, cognito_sub, email, name, role, created_at)
student_profile(user_id, target_exam_id, target_year, preferences jsonb)

exam(id, name)                         -- GATE
paper(id, exam_id, code, name)         -- CS, DA, EC, ...
exam_blueprint(id, paper_id, version, spec jsonb, source: 'derived'|'manual')
topic(id, paper_id, parent_id, name, slug, weight_hint)

source_pdf(id, s3_key, paper_id, year, uploaded_by, status, page_count)
question(id, paper_id, topic_id, type, marks, difficulty, status, current_version_id,
         source_pdf_id, source_page, year, session)
question_version(id, question_id, version, stem_md, options jsonb, answer jsonb,
                 nat_tolerance jsonb, solution_md, figures jsonb, created_by, created_at)
question_tag(question_id, tag)         -- concept tags
question_embedding(question_id, vector)  -- pgvector for dedupe/similar
question_stats(question_id, attempts, correct_rate, avg_time, discrimination, updated_at)
question_report(id, question_id, reporter_id, reason, status, resolved_by)

test_template(id, paper_id, kind: 'full'|'subject'|'topic'|'pyq'|'custom', blueprint jsonb, ...)
test_instance(id, template_id, owner_id|null, question_version_ids int[], duration_s,
              published_at, starts_at, ends_at)     -- null owner = shared series test
attempt(id, test_instance_id, user_id, started_at, deadline_at, submitted_at, status,
        score, section_scores jsonb, rank, percentile)
attempt_response(attempt_id, question_version_id, response jsonb, palette_status,
                 time_spent_s, visits, is_correct, marks_awarded, updated_at)
                 -- PK (attempt_id, question_version_id)

analysis_snapshot(attempt_id, topic_breakdown jsonb, time_breakdown jsonb, insights jsonb)
topic_mastery(user_id, topic_id, rating, confidence, updated_at)
revision_item(user_id, question_id, due_at, interval, ease)
bookmark(user_id, question_id, note)

question_key_history(question_version_id, key, key_status, changed_by, reason, at)   -- see §7.1
audit_log(id, actor_id, action, entity, entity_id, at, meta jsonb)
```

Notes:
- Tests reference `question_version_id`, so editing a question never rewrites history.
- `attempt_response` can grow large (about 65 rows × every attempt). Partition by month, and index `(user_id, created_at)`.
- Analytics-heavy reads go to the read replica. If it becomes the bottleneck, export to S3/Athena later, not before.

## 12. API surface (REST + JSON, versioned `/v1`)

```
Auth        POST /auth/session (Cognito token exchange)   GET /me
Catalog     GET /exams, /papers/{id}/topics, /tests?paper=&kind=
Tests       POST /tests/generate              (custom/recommended)
            GET  /tests/{id}                  (meta, entitlement check)
Attempts    POST /attempts                    (start → deadline_at, package URL)
            PUT  /attempts/{id}/responses     (autosave batch, idempotent by client_seq)
            GET  /attempts/{id}               (resume: state + server time)
            POST /attempts/{id}/submit
Results     GET  /attempts/{id}/result        (instant score)
            GET  /attempts/{id}/analysis      (async, 202 until ready)
            GET  /attempts/{id}/review
Practice    GET  /revision/queue    POST /bookmarks
Insights    GET  /me/dashboard      GET /me/mastery
Reports     POST /questions/{id}/report
Admin       POST /admin/pdfs (presigned S3 upload)   GET /admin/ingest/{id}
            GET/PUT /admin/review-queue/{item}   POST /admin/questions/{id}/publish
            CRUD /admin/blueprints, /admin/tests    POST /admin/blueprints/derive
```

Rules: every route is authz-checked server-side (role plus ownership), responses are validated against schemas, and rate limits apply per user and per IP.

## 13. Security, privacy, compliance

- **Exam integrity**: answer keys and solutions are never sent during an attempt. Signed, short-lived URLs for test packages. Server-side scoring only.
- **Auth**: Cognito, MFA optional for admins (required for the admin role). Short-lived JWTs, with refresh tokens handled by Cognito.
- **Data**: encryption at rest (KMS) and in transit (TLS 1.2+). Private subnets for the API, workers and databases, with only the ALB public. VPC endpoints for S3 and SQS.
- **PII**: minimal collection (name, email, optional phone). India's DPDP Act applies, so keep a privacy policy, consent records, and a delete-my-data flow.
- **Content protection**: uploaded PDFs are PYQ papers (see the rights note in §7.2). Private buckets, watermarking of exported or downloaded content, and a rate limit on review-mode scraping.
- **Abuse**: WAF bot control, per-account concurrent-session limits, and anomaly flags (identical answer sequences across accounts).
- **Auditability**: an `audit_log` for admin and content changes.
- **Backups and DR**: Aurora PITR (7–35 days), cross-region snapshot copy, and S3 versioning. Targets: **RPO ≤ 5 min, RTO ≤ 1 h**. Multi-AZ everywhere.

## 14. Non-functional targets (initial)

| Metric | Target |
|---|---|
| Exam page load (test package) | p95 < 2 s |
| Autosave API latency | p95 < 150 ms, p99 < 400 ms |
| Submit to score displayed | < 3 s |
| Detailed analysis ready | < 30 s |
| Availability during a scheduled test window | 99.95% |
| Lost responses on server failure | ≤ 1 autosave interval (≤ 10 s) |
| Scale design point | 20k concurrent examinees (v1), 100k (v2) |

## 15. Environments, delivery and cost notes

- **Environments**: dev, staging (prod-like, smaller), prod. All from IaC. Per-PR preview deploys are optional.
- **CI/CD**: lint, tests, build, push to ECR, deploy to staging, smoke test, then manual promote to prod with ECS blue/green and automatic rollback on alarms.
- **Testing**: unit tests for scoring and blueprint logic (the highest-risk pure logic), contract tests for the API, E2E exam-flow tests (Playwright) covering disconnect/resume and timer expiry, and load tests (k6).
- **Rough cost shape at launch**: two small Fargate tasks plus workers, one Aurora instance with a small read replica, one Redis node (Multi-AZ), S3, and CloudFront. Expect low hundreds of USD per month idle. The real variable cost is Bedrock and Textract during bulk PDF ingestion, so budget it per page and cap it.
- **Scale levers**: Fargate autoscaling, Aurora read replicas, and CDN-served test packages. Don't add Kafka, Kubernetes, or OpenSearch until a metric demands them.

## 16. Phased roadmap

**Phase 0 — Foundations (2 weeks)**: repo, IaC (ap-south-1), CI/CD, Cognito auth, schema, GATE CS taxonomy seed. **In parallel (you): key sourcing sheet and final-key files for each year and session.**
**Phase 1 — Content engine (5–6 weeks, scanned input and one reviewer)**: scanned-page pipeline with dual readers, golden-set accuracy gate, review UI, the answer-key pipeline (§7.1) with official-key import for PYQs, a golden set to measure LLM-key accuracy, launch-scope years ingested and key-verified, the remaining years released in batches as the reviewer clears them.
**Phase 2 — Exam engine (3–4 weeks)**: console, session engine, autosave/resume/timer, scoring, PYQ-mode tests. *First internal full mock.*
**Phase 3 — Analytics (3 weeks)**: result page, topic and time analysis, cohort rank, review mode, blueprint derivation, and the generated-test builder.
**Phase 4 — Practice loop and polish (2–3 weeks)**: mastery, revision queue, dashboard, reports, abuse limits, load test, security review. *Closed beta.*
**Phase 5 — Launch and expand** (also the backlog of §7.4 for 2007–2012): more GATE papers (DA, EC, EE, ME, CE), then other exams via new blueprints. A payments phase slots in here if the business model changes.

## 17. Key risks and mitigations

| Risk | Mitigation |
|---|---|
| PDF extraction quality (math, diagrams, scans) | Human review gate, confidence scoring, golden-set metrics, vision-LLM fallback |
| Wrong answer keys destroying trust | Unverified keys can't be scored, question-report loop, and discrimination-based auto-flagging |
| Weekend spike or a failure mid-exam | Pre-warming, Redis-first writes, resumable sessions, force-submit safety net, game-day drills |
| Timer disputes | Server-authoritative time and an audit trail of every autosave |
| Thin question pool per topic, so repeated questions | Pool-health dashboard and an ingest-first content plan |
| Rank and percentile credibility on a small cohort | Label as "estimated", show cohort size, and blend with historical GATE distributions |
| LLM cost and hallucination in extraction | Schema-constrained output, validation rules, per-page caching, and a budget cap |

## 18. Open questions (remaining)

1. **Unconfirmed final status** of most official keys (§7.3): the reviewer checks each key's heading or source. Who owns this, and by when?
2. **Scan quality**: are the scans clean 300 dpi images, or phone photos and photocopies? A sample of 3 pages from different years would let me check readability before we commit to a timeline.
3. **Years and sessions**: the exact list of GATE CS years you have, and whether all sessions (sets) are present for each.
4. **Backup for the single reviewer** (even part-time), and who is the admin that approves key overrides?
5. **PYQ usage rights**: confirm you are cleared to reuse the GATE papers on a public platform (§7.2 rights note).
6. **Free-tier limits**: acceptable daily cap per user (suggested: 3 full mocks/day)?
7. **Extra time for candidates with disabilities**: in v1 or later? It is a cheap per-user duration multiplier.
8. **Bedrock region availability**: confirm the chosen Claude model is available in ap-south-1.
9. **Team size and timeline**, so the roadmap weeks become real.

---

## 20. Student-created tests: by topic name and from an uploaded PDF

Two new ways to start a test, both on the same exam console, scoring and analysis as everything else. The difference is **how much we can trust the questions and keys**, so every question carries a visible trust badge (§20.3).

### 20.1 Test by topic name

**Flow**
1. **Resolve the topic.** The student types free text ("deadlock", "dp on trees", "normal forms"). We match it to the GATE CS topic taxonomy using aliases plus embedding search, and show the match for confirmation ("Operating Systems › Deadlocks"). Several matches are allowed. If nothing in the syllabus matches, we say so and suggest the nearest topics. We do not make up a topic.
2. **Choose the options.** Number of questions, difficulty, time limit (default derived from marks, like GATE's ~1.8 min per mark), type mix (MCQ / MSQ / NAT), and a source switch:
   - **Past papers only** (default): official-key and reviewer-verified questions.
   - **Include AI-generated practice questions**: fills any shortfall.
3. **Assemble** with the existing test assembler (§8.2). The bank is used first.
4. **Generate only the shortfall** (if the student allowed AI questions), asynchronously, with a progress bar. Generated questions are cached, so the next student asking for the same topic gets them instantly.

**Generating a question** (offline worker, never in the exam request path)
- **Style grounding**: the generator receives the topic, the PYQ blueprint for it (typical marks, type mix and difficulty from §8.1), and a few real PYQs on that topic as style examples. So generated questions look like GATE's, not like a textbook.
- **Structured output**: stem, options, type, marks, answer, and a worked solution, all in a strict schema.
- **Independent verification**: a separate solve pass runs 5 times with code execution for numeric problems. At least 4 of 5 must reproduce the generator's answer, or the question is discarded. Options must be distinct, and an MCQ must have exactly one correct option.
- **Duplicate check** against the bank by embedding similarity.
- **Label and scope**: `origin = ai_generated`, `key_status = AI_CONSENSUS`, `rank_eligible = false`. Questions are shown with an "AI-generated" badge and a report button.
- **Quality loop**: the reviewer audits a random 10% sample and any question with student reports. A reviewer-approved question is promoted (`REVIEWER_VERIFIED`) and joins the public bank. Reports from students demote a question and hide it.
- **Cost control**: a daily cap per user (suggested: 100 generated questions) and a global monthly budget cap. Cached questions cost nothing to reuse.

### 20.2 Test from the student's own PDF

**Flow**
1. **Upload**: the browser uploads straight to S3 through a presigned URL. Accepted: PDF only, up to 25 MB and 40 pages (suggested), not password-protected. The student ticks a box confirming they have the right to use the file.
2. **Scan and queue**: magic-byte check, malware scan (GuardDuty Malware Protection for S3), then a message on a **separate low-priority queue and worker pool**, so student uploads can never starve the reviewer's ingestion work.
3. **Process** with the same pipeline as §7 (scanned or text, vision-LLM and OCR readers, structuring, topic tagging). Progress is shown ("Reading page 7 of 22").
4. **Detect the format**: the pipeline reads the instructions page, or infers from the questions, the duration, total marks, sections, question types and negative-marking rules. The student sees a **"Detected format"** form and can edit it. If nothing is detected, it falls back to the GATE CS format scaled to the paper's marks.
5. **Fingerprint match against our bank**: if the PDF, or individual questions, closely match a paper we already hold (for example a GATE PYQ), we offer the verified version with its official keys instead of re-deriving. Question-level matches use embedding similarity and are shown for confirmation, never applied silently.
6. **Answer keys**, in this order:
   - the student supplies a key (a second PDF, or a simple answer grid they type in): `USER_PROVIDED`;
   - a match in our bank (step 5);
   - otherwise AI consensus: `AI_UNVERIFIED`, with a clear warning banner.
   Questions where the AI cannot reach consensus are marked **"key uncertain"** and left **unscored** (shown separately), and the student may enter the key themselves.
7. **Review screen before the test**: original page crop beside the parsed question, so the student can fix a misread digit or drop a question. This is cheap, self-service quality control that does not use reviewer time.
8. **Take the test** in the normal exam console under the detected or edited format, then get the usual analysis. Results are labelled **"Your own paper: not ranked"** and are kept out of cohort statistics and the mastery model's calibration (they may still update the student's *own* topic mastery, marked as lower confidence).

**Privacy and rights**
- Uploaded papers and everything derived from them are **private to the uploading student**: `scope = private`, `owner_id` set, never shown to anyone else, and **never auto-added to the public bank**.
- Retention: the file and parsed questions are deleted after 30 days unless the student deletes them sooner. Deleting an upload deletes the S3 object, the parsed questions and the attempts' question text.
- Terms of use state the student's responsibility for the right to use the file, and we have a takedown process. Third-party coaching material is the likely legal risk here, and it needs a lawyer's read before launch.

**Security**
- PDFs are untrusted. Parsing runs in an isolated, short-lived worker with no internet egress (only VPC endpoints to S3 and Bedrock), with time and memory limits.
- **Prompt-injection defence**: text inside a PDF is only ever *data*. The prompts mark it as such, outputs are validated against a strict schema, and the LLM in this path has no tools with side effects.
- Per-user quotas (suggested: 3 uploads per day, 5 concurrent processing jobs platform-wide per user) and the global budget cap from §20.1.

**Scope limit**: aceIt is GATE CS only in v1. An uploaded paper is tagged against the CS taxonomy, and if most of its questions fall outside the syllabus (for example a biology paper), the student is told so and can choose to proceed with only the in-scope questions or cancel.

### 20.3 Trust ladder (shown to students as a badge)

| Badge | Source | Key | Counts towards rank / percentile? |
|---|---|---|---|
| Official | GATE PYQ with official key | Official | Yes (final-confirmed keys only, §7.1) |
| Verified | Reviewer-confirmed, including 2007–2012 reconstructed keys (§7.4) | Reviewer-verified | No for reconstructed papers, yes for reviewer-confirmed official-key conflicts |
| AI-generated | Generated for a topic test (§20.1) | AI consensus | No |
| Your paper | Uploaded by the student (§20.2) | User-provided or AI | No |

A test mixing badges is allowed (for example a topic test that includes AI questions), and its result page shows a per-badge split. A test is rank-eligible only if **every** question in it is Official.

### 20.4 Data model additions

```
question.origin          'official_pyq' | 'reviewer_verified' | 'ai_generated' | 'user_upload'
question.scope           'public' | 'private'            -- private rows are visible to owner only
question.owner_id        null for public
question.rank_eligible   boolean
question_version.key_status  adds 'AI_UNVERIFIED' | 'USER_PROVIDED' | 'UNCERTAIN'

topic_alias(topic_id, alias, source)         -- free-text -> taxonomy mapping, grows from usage
generation_job(id, user_id, topic_id, params jsonb, status, requested, produced, discarded, cost)
user_upload(id, user_id, s3_key, sha256, pages, status, progress, detected_format jsonb,
            consent_at, expires_at, matched_paper_id null)
user_quota(user_id, day, uploads, generated_questions)
test_template.kind       adds 'topic_ai' | 'upload'
```

Row-level rule: every query that returns questions filters `scope = 'public' OR owner_id = :me`. This is enforced in one repository layer and covered by a test that tries to read another user's private question.

### 20.5 API additions

```
Topics     POST /topics/resolve            {q}           -> ranked taxonomy matches
Tests      POST /tests/generate            adds {topic_text|topic_ids, include_ai, type_mix, count, duration}
           GET  /generation-jobs/{id}      progress
Uploads    POST /uploads                   -> presigned PUT + upload id
           POST /uploads/{id}/confirm      (starts processing, records consent)
           GET  /uploads/{id}              status, progress, detected format, parsed questions
           PUT  /uploads/{id}/format       edit detected format
           PUT  /uploads/{id}/questions/{n}  fix text, drop, or set the key
           POST /uploads/{id}/key          second PDF or answer grid
           POST /uploads/{id}/start-test
           DELETE /uploads/{id}            deletes file, questions, derived data
```

### 20.6 UI additions (fits §19)

- A **"Create a test"** card on the dashboard with two pill tabs: **By topic** and **From my PDF**.
- By topic: a search box with suggestions, then the options card, then a "Generating questions…" state.
- From PDF: a drop zone, a progress card, a **Detected format** card, a side-by-side question review, and a "Start test" button. A rose banner shows "Key not verified" where it applies.
- The trust badge sits next to the question number in the exam console and in review mode.

### 20.7 Roadmap placement

- **Topic test from the existing bank**: Phase 3, with the test builder (§8.2).
- **AI-generated questions**: Phase 4, after the answer-key pipeline (§7.1) proves its accuracy on the official-key years.
- **Upload your own PDF**: **Phase 4b (about 3 weeks)**, because it reuses the ingestion pipeline and needs the format detection, review screen, quotas and malware scanning on top.

### 20.8 Risks specific to this section

| Risk | Mitigation |
|---|---|
| AI-generated questions with a wrong key mislead students | 5-solve verification, discard on disagreement, badge, report loop, 10% reviewer audit |
| Third-party copyrighted papers uploaded | Private-only, consent box, 30-day retention, takedown process, legal review |
| Malicious or oversized PDFs | Size and page limits, malware scan, isolated no-egress workers, time limits |
| Prompt injection inside a PDF | Document text treated as data, schema-validated output, no side-effect tools |
| Cost runaway | Per-user daily caps, global budget cap, caching generated questions |
| One reviewer overloaded by student content | User content never enters the reviewer queue except through sampled audits and reports |
| Poor extraction on messy uploads | Self-service review screen, key-uncertain questions left unscored |

---

## 21. Autonomous operation: no human in the loop

**Requirement (from the product owner):** no one will be available to operate the platform. The system itself randomises, generates and conducts tests, scores them and analyses results.

**Interpretation and what it overrides.** Nothing in the live path (creating a test, starting it, running the timer, submitting, scoring, analysing, re-scoring) may wait for a person. This changes earlier decisions:

| Earlier decision | New position |
|---|---|
| Reviewer verifies every extracted question (§7, §7.2) | Replaced by **automatic publish gates** (§21.3). A reviewer, if one exists, only improves quality and never blocks anything |
| Admin approves key overrides (§7.2) | Removed. A key changes only through a scripted **official-key import**, or automatically through the rules in §21.3 |
| 24-hour SLA on disputes | Removed. Disputed or suspect content is **auto-quarantined**, not queued for a person |
| 2007–2012 keys verified by the reviewer (§7.4) | **Held back** until a human verifies them or an official key is found (see §21.6, decision A) |
| Admin builds and publishes tests (§5.2) | Replaced by the automatic **Test Factory** (§21.1). The admin app shrinks to read-only metrics and feature flags |

### 21.1 Test Factory (automatic generation and randomisation)

- **Always-stocked shelf**: a scheduled job (EventBridge Scheduler, nightly) keeps a ready stock of test instances of each kind: full mocks, subject tests, topic tests, in several difficulty bands. A shelf-health check regenerates whatever is running low. Students can also generate on demand (§8.2, §20.1).
- **Seeded randomisation**: every test is produced by a random number generator with a stored **seed**, so any test can be reproduced and audited exactly. Selection follows the blueprint (§8.2), then shuffles question order within each section. Option order is shuffled **only for questions flagged `shuffle_safe`**. Options such as "both A and B" or "none of the above" refer to positions, so they are never shuffled.
- **Per-student freshness**: a student does not see a question twice until the pool is exhausted (a per-student "seen" set). Difficulty is steered by that student's topic mastery.
- **Multi-session realism**: full mocks are produced as **pairs of sets** (like GATE's CS1 and CS2) built from the same blueprint.
- **Automatic validator** before any test goes on the shelf, and it rejects and regenerates on failure:
  - total marks, question count and section split match the blueprint;
  - every question in a rank-bearing test is `Official` (§20.3), with no quarantined or `DISPUTED` question;
  - no duplicate or near-duplicate questions inside a test (embedding similarity);
  - topic coverage and difficulty distribution inside the blueprint's bounds.
  If a valid test cannot be built, the factory relaxes the rules in a fixed order and marks the result **unranked** and labelled. It never ships a broken test.

### 21.2 Autonomous conduct (extends §10)

- Students start tests themselves, on demand. The server owns the timer, autosave, resume and auto-submit, with the force-submit safety net. A **sweeper** job closes any attempt left open past its deadline plus grace, so nothing stays stuck waiting for a person.
- **No proctor.** Integrity signals (tab switches, fullscreen exits, impossible answer speed, two simultaneous sessions) are recorded and used automatically:
  - they appear as a note on the student's own analysis;
  - an attempt with severe anomalies is **excluded from cohort statistics, rank and percentile** automatically, but the student still sees their own result;
  - nothing is punitive, because there is nobody to hear an appeal.
- **Scoring, analysis and re-scoring** are automatic, as in §9 and §7.1. When an official key is re-imported and differs, affected attempts are re-scored by the job and the students are notified.

### 21.3 Replacing the reviewer with automatic quality gates

**Auto-publish gate (extraction).** A question reaches students only if **all** of these hold:
1. the two readers (vision LLM and Textract) agree on the words, digits and option letters above a threshold;
2. the question passes the schema and rendering validators (LaTeX renders, option count matches the type, marks valid);
3. the independent AI solve (5 runs, code execution for numeric questions) **agrees with the official key**.

If any check fails, the question is `HELD`: it is not used in rank-bearing tests. It may still appear in practice tests with an "unverified text" flag **only if** checks 2 and 3 pass. Disagreement between the AI and the official key mostly signals a misread, so holding is the safe default. Expect to lose some questions this way. The extraction spike (Phase 0) measures how many.

**Auto-quarantine (after publication).** A question is removed from newly generated tests, with no person involved, when:
- 3 or more students report it within 7 days, **and** a fresh 5-solve check does not support the official key;
- its measured discrimination is negative on enough attempts;
- a takedown claim is received. The content is hidden first, and a person looks later if one exists.

Quarantined questions stay hidden until a person restores them. There is no automatic un-quarantine.

**Official key is the authority.** For scoring, the official key always wins. The system never overrides an official key on its own. A reviewer can only influence a **practice-only** reconstructed key.

**Generated and uploaded content** (§20) is already autonomous: AI questions pass the 5-solve gate, carry a badge, and are excluded from ranking. Uploads are private and self-reviewed by the student.

### 21.4 Autonomous operations (keeping it running unattended)

- **Self-healing**: ECS health checks and automatic task replacement. SQS dead-letter queues with automatic retry and backoff. A job sweeper that retries stuck ingestion and generation jobs.
- **Automatic rollback**: the pipeline deploys with canary checks, and alarms roll the release back with no manual step.
- **Kill-switches**: a budget alarm on Bedrock automatically turns off AI generation and uploads and serves cached content only. A DB-trouble alarm switches the app to a read-only "practice from cache" mode instead of failing exams.
- **Degrade, don't die**: in-progress attempts always keep working (Redis-first state, §10), even if analysis or generation is down.
- **Honest limit**: AWS-managed services remove most routine work, but a real incident cannot be fixed by the system itself. **At least one alert recipient is needed** (an email address or phone for CloudWatch alarms), even if nobody checks the dashboards day to day.

### 21.5 Human work that cannot be removed (one-time or rare)

1. **Initial ingestion** of the PYQs: a scripted batch run by a developer, not a student-facing admin task.
2. **The golden set**: about 100 questions hand-checked once, to measure how often the auto-publish gate is wrong. This can be done by any CS-literate person in a few hours. Without it, the gate's error rate is unknown.
3. **Legal review** of the PYQ reuse rights and the upload terms.
4. **Receiving alerts** (§21.4).

### 21.6 Decisions needed

- **A. 2007–2012 (no official keys): DECIDED, held back.** These six sittings are `availability = held_back` in the database and cannot be made live: a database rule forbids it while they have no key. They are published only after a person verifies them or an official key is found. The 2007–2012 reconstruction plan in §7.4 stays as the route back in.
- **B. Is the reviewer now fully out, or "optional if available"?** The design above works either way. If a reviewer exists, they work the quarantined and held queues at their own pace, and restored or fixed questions return to the pool.

### 21.7 Effect on Phase 0 and the roadmap

- Drop the admin review UI and the admin test builder from v1. The admin app is **read-only metrics and feature flags**.
- **P0-20** (confirming each key's final status) becomes a **script** that reads each key's heading and records the result in the sourcing sheet.
- **P0-17 and P0-18 (the spikes) become gating**: they measure how many questions the auto-publish gate holds back, which decides whether the scanned years are worth ingesting at all.
- Add: **Test Factory and validator** (Phase 3), **sweeper and kill-switches** (Phase 2/4), **auto-quarantine rules** (Phase 4).

---

## 22. Build status (2026-10-27)

**Data (done, in `db/`, `data/`, `tools/`)**: question-bank schema with invariants (25 database rule checks), 18 sittings and 1,170 questions of GATE CS 2013–2026 ingested as drafts with official keys, a 62-topic taxonomy, topic tags for every question, a derived exam blueprint ([../data/blueprints/gate_cs_v1.json](../data/blueprints/gate_cs_v1.json)) and a 975-question development pool ([../data/pool/gate_cs_dev_pool.json](../data/pool/gate_cs_dev_pool.json)). Nothing is live through the publish gate (§21.3): it is built but its AI-solve check has not been run.

**Exam engine core (done, pure Python, `apps/api/src/aceit/`, 25 tests)**
- `scoring/`: marking for MCQ (negative one-third of the question's marks), MSQ (all or nothing), NAT (range), alternative accepted answers, marks-to-all and dropped questions, in exact fractions; whole-attempt totals with section and topic breakdowns.
- `testing/assembler.py`: builds a full mock from a seed to the blueprint (65 questions, 100 marks, 10 GA + 55 subject, marks per subject and the MCQ/MSQ/NAT mix inside real ranges), with freshness per student, near-duplicate groups, rank-only pools and topic or subject tests. It builds in a few milliseconds and is reproducible from its seed. A separate validator judges every test, and an impossible request fails loudly instead of returning a broken test.
- `session/attempt.py`: server-owned deadline, idempotent autosave by sequence number, a 30-second grace period, idempotent submit, the sweeper that closes abandoned attempts, and the rule that integrity anomalies only exclude an attempt from cohort statistics.

**HTTP API (done, `apps/api/`, 35 tests in all)**: FastAPI on PostgreSQL. Endpoints: topic lookup from free text, create a full mock or a topic test, start/resume an attempt, autosave, submit, result. Verified against a real PostgreSQL loaded with the real schema, the real topic list and a synthetic copy of the real 975-question pool. Checked behaviours: students never see keys or solutions; users cannot read each other's tests or attempts; repeated start resumes and never restarts the clock; autosave is idempotent, validated and cut off after the grace period; submit is idempotent and scores once; the sweeper closes abandoned attempts; invalid IDs are a 422, not a 500. Sign-in is a Cognito-style RS256 JWT (expired, wrong issuer, wrong audience, wrong signer and `alg: none` tokens are all refused); the insecure dev mode must be switched on explicitly. Full mocks use 2018+ questions only (the policy above, now adopted).

**Web app (done, `apps/web/`, dependency-free)**: sign-in, home (test by topic with free-text lookup, or a full mock, plus recent tests), the exam console, and the result page with a review. Verified in a real browser against real data: a topic test answered by number pad, option buttons and mark-for-review, then submitted and scored against the official keys (the deadlock question came out correct); a full mock built from the real questions in 20 ms (65 questions, 100 marks, 3 hours); the phone layout; no leftover dialog after submitting (found and fixed). The exam console follows §19: flat and calm, black timer pill that turns rose in the last 10 minutes, palette colours with text labels for every state, keyboard use, spoken warnings at 30, 10 and 5 minutes. Original page images are shown for any question whose text is unreliable (about 40 of 65 in a real mock). The console has a floating scientific calculator (sin/cos/tan and inverses, log, ln, sqrt, powers, factorial, pi, e, Deg/Rad, Ans) built on a small parser rather than eval; It also has a floating rough-work pad (pen, eraser and clear, or typed notes, kept per question in the browser only and never sent to the server). 9 tests cover the console and calculator logic; the pad was checked by hand in a real browser (drawing kept per question, text kept, no console errors). **API additions for it** (38 tests in all): `/v1/config`, `/v1/attempts` (history), `/v1/attempts/{id}/review` (official answers, only after submission) and a question-image endpoint that serves only to people holding that test and never leaves the images folder.

**Analysis and rank (done, `apps/api/src/aceit/analytics/`, 8 tests plus 1 API test)**: `GET /v1/attempts/{id}/analysis` (after submission only) returns marks earned, lost to negative marking and left unattempted; topic and subject tables sorted by marks lost; time used against the 108 s per mark pace, slowest questions and wrong answers given in under a quarter of the expected time; plain-rule insights (skipped, negative marking, time sink, weakest topic, rushed, strong) and the top three topics to practise. For a rank-bearing full mock it adds an estimated rank and percentile against other students' best scores on the same blueprint (ties count half; marked low-confidence under 30 students). `GET /v1/me/progress` gives per-subject totals and a predicted-score band, which stays empty until 60 questions of evidence exist and is labelled an estimate. No AI is involved: every line is a rule over the student's own numbers. The result page shows the insight and practise-next cards. All 46 API tests pass.

**Publish gate (built, `apps/api/src/aceit/gate/`, 6 tests; run with `python -m aceit.gate`)**: the three checks of §21.3 plus one decision rule. (2) Structural validators: marks, four labelled A-D options with text for text-mode questions, no options on numerical ones, the original page image present, and a key that is official, current and fits the question type (letters inside A-D, numeric range not reversed). (1) Second reader: tesseract on the page image against the PDF text layer, passing at 90% agreement of words and digits; skipped for image-mode questions because the student is shown the original image anyway. (3) AI solve: five independent solves, at least four must agree and the agreed answer must score as correct against the official key (marks-to-all keys need none); evidence goes to `ai_check`. Decision: all pass = live; text doubted by the second reader but solve passes = live, practice-only (never ranked); anything else, including "AI solve not run", = held. It only handles draft and held questions, so it never re-holds a live one and never restores a quarantined one. Applying it requires `--solver anthropic` (`ANTHROPIC_API_KEY`, five calls per question); without a solver only `--dry-run` works. **Measured on the real bank (dry run, 1,170 questions): 1,087 pass checks 1 and 2; 83 text-mode questions fail the second reader (practice-only candidates); nothing can go live until the AI solve runs.** The Anthropic solver is written but has not been exercised against the live API; the logic around it is tested with fake solvers. The golden-set measurement of the gate's own error rate (§21.5) is still to do.

**Automatic quarantine (built, `apps/api/src/aceit/quarantine/`, 5 tests; run with `python -m aceit.quarantine run --refresh [--solver anthropic]`)**: three triggers, each leaving a `question_flag` row as the audit trail. A takedown claim hides the question at once (`python -m aceit.quarantine takedown <question_id> "reason"`; deliberately no public endpoint, because an open one could be abused to hide questions). Three different students reporting within seven days quarantines it only if a fresh five-solve check does not support the official key; if the AI backs the key the reports are closed and the question stays live, and without a solver such cases are only listed as pending. Negative discrimination below -0.1 on at least 30 attempts quarantines it (discrimination = correlation between getting the question right and the score on the rest of that test, recomputed into `question_stats` by `--refresh`). Quarantine removes a question from newly built tests and from ranking; attempts already started keep it and are still scored. Nothing ever un-quarantines automatically. Students report from the review page (`POST /v1/questions/{version_id}/report`, only for a question in one of their finished tests, once per student while open). The thresholds (3 reports, 7 days, 30 attempts, -0.1) are starting values, not calibrated on real data; the refresh rescans all attempts and should become incremental at scale. As with the gate, the report-based rule cannot decide until the AI solve is run with a key.

**Scheduled job runner (built, `apps/api/src/aceit/jobs/`, 5 tests; run with `python -m aceit.jobs`)**: one process that runs the sweeper every minute, the quarantine rules (stats refresh plus the three triggers) every 15 minutes and the publish gate hourly, for a bounded batch (100 by default) so AI spend is capped. Each job runs in a single transaction under a Postgres advisory lock, so several copies of the runner can run at once and a job never runs twice at the same time; a job that fails rolls back completely, is logged with its error and is retried on its next turn without stopping the others. The AI-backed work (the gate, and the solve step of quarantine) runs only when `ACEIT_JOB_SOLVER=anthropic` is set; otherwise the gate is skipped and report-based quarantine cases are listed as pending. `python -m aceit.jobs --once <sweep|quarantine|gate>` runs one job and exits, which is the hook for EventBridge and ECS on AWS. The dev server runs the loop in a background thread. Run history is only in the log; a `job_run` table and a CloudWatch alarm on repeated failures are still to do (§21.4).

**Nightly test shelf (built, `apps/api/src/aceit/testing/shelf.py`, 4 tests; job `shelf`, daily)**: shared ready-made tests (no owner, tagged by the new `test_instance.shelf_key`): 4 `full:rank` mocks built only from ranking-eligible questions (never relaxed), 4 `full:practice` mocks, and 2 twenty-question tests for each of the 10 subjects. They come from the same seeded assembler and validator as on-demand tests. Each night it retires shelf tests that hold a question that is no longer servable (quarantined or held) or are older than 14 days, then tops every key back up; tests that students have attempted are only taken off the shelf, never deleted. `POST /v1/tests` serves a full mock or a whole-subject test (one topic that is a subject, count 20) straight from the shelf when it has one the student shares no question with, and otherwise builds a fresh one as before; passing a seed skips the shelf. Everyone on the same shelf test is ranked on the same questions. On the real bank the first run built 28 tests in 0.35 s. Not built: difficulty bands (there is no difficulty data yet). Existing databases need `ALTER TABLE test_instance ADD COLUMN shelf_key text`.

**Paired mock sets (built: `build_pair` in `testing/assembler.py`, `POST /v1/test-pairs`, shelf keys `pair:rank` and `pair:practice`; 3 tests)**: like GATE's CS1 and CS2 sittings, a pair is two full mocks from the same blueprint with no question in common, linked by `test_instance.pair_id` and `pair_set` (1 or 2). Set 2 is built only from the questions set 1 left unused, and a pair is all or nothing. The shelf keeps 2 pairs of each kind; a pair is served only if the student has met no question in either set, is retired as a whole when any question in it stops being servable or it is 14 days old, and `POST /v1/test-pairs` builds an owned pair on demand when the shelf cannot serve (a seed skips the shelf). Each set is a normal test with its own attempt and score out of 100; the home page's Full mock tab offers "One paper" or "A pair of papers" (Start Set 1), and the result page of a paired set shows a pair card with both scores, a Start/Resume button for the other set and, once both are done, a plain combined total out of 200 with no adjustment between the sets (`GET /v1/test-pairs/{pair_id}` backs it; recent tests are labelled Set 1 / Set 2). There is no cross-set normalisation yet. **Real-bank finding: practice pairs build fine, but a ranked pair cannot be built today** (the ranking-eligible pool is only the 2016 and 2024 sittings, too few for two disjoint blueprint-valid mocks), so `pair:rank` stays empty and the job reports it; this improves as more sittings get final official keys. Existing databases need `ALTER TABLE test_instance ADD COLUMN pair_id uuid, ADD COLUMN pair_set smallint`.

**Production sign-in with Cognito (built, not yet connected to a real pool; `apps/web/js/auth.js`, `infra/cognito.yaml`, `tools/fake_cognito.py`)**: the web app signs in on Cognito's hosted page with the authorization-code flow and PKCE (no secret in the browser, no tokens in the URL), keeps the ID token and refresh token in the browser, refreshes the ID token silently when under a minute is left, checks the `state` value so a forged callback is refused, and signs out through Cognito's logout. The API accepts only an RS256 ID token with the right signature, issuer, audience and `token_use = id` (an access token is refused), and now refuses to start in production mode if the issuer or audience is not configured (before, it would have skipped those checks). Setting `ACEIT_COGNITO_REGION`, `ACEIT_COGNITO_POOL_ID` and `ACEIT_COGNITO_CLIENT_ID` is enough: issuer, key URL and audience follow, and `/v1/config` tells the browser the hosted domain and client id. `infra/cognito.yaml` is a CloudFormation template for the pool (email sign-up and verification, 10-character passwords, a public app client with the code flow only, 60-minute tokens, 30-day refresh, the pool retained on stack deletion); it passes AWS template validation and is **deployed** as the stack `aceit-auth` in account <aws-account-id>, ap-south-1 (pool `ap-south-1_CZ5wARQb1`, hosted page `aceit-prep.auth.ap-south-1.amazoncognito.com`, callback `http://localhost:8000/` only, so it works for local testing until a real address is added with `--parameter-overrides AppUrl=...`); the public settings are in `apps/api/cognito.env`. Checked against the real pool: the API serves the Cognito config, refuses a request with no token, the key set is reachable and the hosted page loads; a real sign-up and sign-in is still to be tried by a person, because creating an account needs a real email. Verified end to end with `tools/fake_cognito.py`, a local stand-in that checks the PKCE verifier and issues Cognito-shaped RS256 tokens: sign-in, the user shown, silent refresh with 34 seconds left, sign-out and a forged-state callback all behaved correctly. Not covered: the real Cognito hosted page and its email verification, which need an AWS account, and a social sign-in (Google) option. Tokens in `localStorage` are readable by any script on the page; the app renders question text as text only, but a strict Content-Security-Policy header should be added when it is served from CloudFront.

**Design refresh (done, `apps/web/styles.css`)**: the web app moved from the lavender, pill-shaped look to a sharper direction taken from new references: a warm off-white canvas (`#F3F3EF`), white panels with a hairline border, square-cornered controls, monospace uppercase micro-labels with a dot, a tall condensed display face for headings and big numbers (system fonts only, no font download: Avenir Next Condensed, Roboto Condensed or Arial Narrow), flat lime blocks (`#DCF21C`) for emphasis, and one deep-green card (`#0C3B36`, lime numerals) for the headline figure. Primary actions are lime with an arrow; secondary ones are black or outlined. The login page has a lime hero beside a green card with the real exam shape (65 questions, 100 marks, 3 hours); the home page opens with a lime greeting card. The exam console keeps its flat, calm layout in the new type, with square palette tiles (state is still shown by colour, border style and a text label, never colour alone). Fixed on the way: `.span-4` was spanning 5 columns. Muted text is about 7:1 on the canvas; the old rounded-pill and gradient styles are gone.

**Landing page (done, `apps/web/js/landing.js`)**: signed-out visitors now land on a front page modelled on the first reference instead of the bare sign-in form (the sign-in page is still at `#/login`, and sign-out returns to the landing page). It has a top bar with section links and "Login / Sign up", a hero ("Sit the exam before the exam") with a lime panel holding an exam-screen preview drawn in CSS, a strip of true product facts, an about statement with a greyed tail, four numbered cards (180 minutes, 62 syllabus topics, 100 marks, 2 papers per pair; the third in deep green), three feature rows with small example mock-ups (build a test, analyse a result, paired papers), an FAQ of 11 answers (cost, where questions come from, official keys, marking, paired papers, pausing, rank accuracy, calculator, reporting, data, affiliation) built on native `<details>` so it works by keyboard and screen reader, a closing lime-to-olive call to action and a footer saying the site is independent and not affiliated with GATE or its organising institutes. The FAQ answers are written to match what the product does today (for example, they say not every year is in yet, and that rank is an estimate), so they must be edited whenever the product changes. Deliberately left out from the reference: user counts, star ratings and partner logos, because none of those are real yet. Mock-up figures are labelled as examples. Checked at desktop and 375 px phone width (no horizontal scroll); no automated test covers it, and the copy has not been reviewed for the legal point in §21.5 about reusing past papers.

**Passwords and privacy (done)**: the app now starts in real sign-in mode by default: `apps/api/dev_server.py` loads `cognito.env` unless `ACEIT_AUTH_MODE=dev` is set, so students need an email and a password (Cognito: at least 10 characters with upper case, lower case and a number, email verification, "forgot password" by email). aceIt never receives or stores a password; only Cognito does. In this mode the server answers 401 to the old `X-Dev-User` header, so the name-only shortcut cannot be used by mistake. Each student's tests, answers, results, rough work and reports are scoped to their own account on the server (another student's attempt or private pair returns 404). Not done: a self-service "delete my account and data" and "download my data" function, optional two-step sign-in (MFA), and styling of Cognito's plain hosted page to match the app; the privacy wording on the landing page's FAQ should be checked against these once they exist.

**Bug fixed**: searching for a topic showed `[object HTMLButtonElement]` instead of the matching topics (a list of buttons was appended as one array); it is fixed and was the only place with that pattern.

**AWS prototype deployment (DEPLOYED 2026-10-27 as stack `aceit-proto`, ap-south-1, account <aws-account-id>: https://d10meumccwrsq5.cloudfront.net/ , instance `i-0f4b108aba6c4a626`; 1,170 questions loaded, 585 (2018+) live through the development shortcut, 585 draft; the Cognito callbacks include this address; the deployed build includes the "Retry, improve and past papers" features below (updated the same day with `deploy/update.sh`, a code-only update of about 70 KB that rebuilds on the server and rolls back by itself if the health check fails); files: `infra/prototype.yaml`, `deploy/package.sh`, `Dockerfile`, `apps/api/serve.py`, `apps/api/src/aceit/admin`)**: because this is a prototype for showing and has to run on AWS, the full design (ALB, Fargate, Aurora, NAT, WAF, about 55 to 60 USD a month or more) is replaced for now by the cheapest sensible AWS shape: one ARM EC2 server (t4g.small, 20 GB encrypted disk) that runs the app and PostgreSQL in two containers, with CloudFront in front for a free HTTPS address (Cognito requires https). The server takes its code from a private S3 bucket, builds the image, creates the schema, loads the 1,170 questions as drafts (an optional flag then makes 2018+ questions live through the marked development shortcut), and starts the app with the Cognito settings and the scheduled jobs. Security: no SSH port (administer with Session Manager), port 80 open only to CloudFront's address range, IMDSv2 only, encrypted disk, private bucket, no secrets in the template (the database password is generated on the server). Known prototype limits: no database backups and a single server (stopping it loses nothing, deleting the stack loses the data), any CloudFront distribution could reach port 80 (no shared-secret header yet), plain HTTP between CloudFront and the server, and no alarms. Estimated cost in ap-south-1: about 14 USD for the server, 4 for the public IPv4 address, 2 for the disk, CloudFront and S3 near zero at this size, about 20 USD a month. `infra/cognito.yaml` gained an optional `ProdUrl` so the deployed address can be added to the sign-in callbacks. Teardown: empty the bucket, then delete the stack. The earlier full design stays the target for a real launch.

**Retry, improve and past papers (built; analytics `classify`, `why_summary`, `difficulty_label`; store `mistakes`, `papers`, `pyq_versions`, `previous_attempt`; 8 tests)**: answers the three questions every result should answer. *Where did I lose marks*: unchanged (marks, topics, subjects, time). *Why*: every lost question gets one plain-rule reason, shown as a chip in the review and summed in a "Why you lost marks" card with advice: answered too fast (wrong in under a quarter of the expected time), careless slip (wrong although the topic's other questions went well), took very long (over twice the expected time, likely a concept gap), concept gap, skipped, ran out of time (nothing touched from that question on). These are guesses from timing and topic accuracy, not a diagnosis. *What next*: the practise-next topics are now buttons that build a 10-question test on that topic. **Mistakes notebook**: wrong answers are collected automatically (`GET /v1/me/mistakes`); "Retry my mistakes" (`POST /v1/tests` kind `retry`, up to 20) builds a test from them, and a question leaves the notebook by itself once answered correctly in a later test. **Past papers**: `GET /v1/papers` lists sittings whose 65 questions are all servable and `kind: pyq` builds that paper exactly as set (same order, 3 hours, ranked when its key is final). **Compare attempts**: the analysis shows percent, wrong and skipped now versus the previous attempt of the same kind. **Difficulty labels** (easy, medium, hard) appear in the review only once at least 20 students have attempted a question. Not built from the wish list: silly-mistake detection beyond timing, and sectional tests.

**Written explanations and the Gemini model (built; `apps/api/src/aceit/llm.py`, `aceit/explain/`; 9 tests)**: the AI features use **Google Gemini only** (no Anthropic key is used anywhere); the key comes from `GEMINI_API_KEY` in the environment and is never written to a file, the database or a log, and it travels in a request header, never in a URL. `GEMINI_MODEL` overrides the default `gemini-3.8-flash` (the old default `gemini-2.5-flash` was refused as no longer available to new keys; `GET /v1beta/models` lists what a key can use). Calls are spaced (`ACEIT_LLM_MIN_INTERVAL_S`, default 4 s) and a 429 is waited out and retried, because free tiers allow only a few requests a minute. **Explanations**: `python -m aceit.explain --limit N` writes a short explanation for live questions that have none. The model is told the official answer and must end with `FINAL ANSWER: {...}`; the text is stored in `question_version.solution_md` (`solution_src = 'ai'`) only if that answer scores as correct against the official key and the length is sensible, otherwise it is thrown away and counted by reason, because a model that cannot reach the official answer has probably misread the question. Students see an explanation only after submitting (the review endpoint), labelled "Written by AI and checked against the official answer" with a report button; questions without one say so. The scheduled job `explain` runs every 6 hours in batches of 50 and has its own switch `ACEIT_EXPLAIN=1`, separate from the publish gate (`ACEIT_JOB_SOLVER=gemini`), which needs about 5 calls per question and would use up a free quota. Limits: explanations are plain text (no formatted maths), image-only questions are sent to the model as images, and the quality of the writing has not yet been reviewed by a person.

**Smaller student features (built and deployed to the AWS prototype 2026-10-28; 7 tests)**: (1) **Sprint and subject tests**: the home page's first tab starts a 10-question mixed sprint (about 25 minutes), or a 10, 20 or 30 question test inside one subject; they use the normal topic-test builder (a 20-question single-subject test is served from the nightly shelf). (2) **Bookmarks and private notes**: a bookmark button and a note box (up to 2,000 characters, saved on leaving the box) on every question in the review; stored per student per question in the new table `question_note` (migration `db/migrations/2026-10-28-question-note.sql`, also in `schema.sql`; apply it to existing databases, done on the AWS server); only for questions in the student's own finished tests; another student cannot read or write them; `GET /v1/me/bookmarks`, `PUT /v1/questions/{id}/note`, and "Practise my bookmarks" builds a test from them (`kind: retry, source: bookmarks`). (3) **Pace indicator** in the exam bar: marks of the questions already moved past against the real exam's rate of 108 seconds per mark, shown as "On pace", "N min ahead" or "N min behind" (within about 3 marks counts as on pace); computed in the browser only. (5) **Display settings**: a theme button (auto follows the device, or light, or dark) and a text-size button (normal, large, extra large) in every page header and in the exam bar, stored in this browser; dark mode uses a full palette with the lime, rose, forest and timer blocks unchanged and question page images kept white; **phone layout** for the exam: compact bar, larger answer buttons, action buttons fixed to the bottom of the screen for thumb reach, an 8-column palette, no horizontal scroll at 375 px. The display buttons are hidden in the exam on phones to save space. Not built, by request: the browse page for past questions. Checked by hand in a real browser (sprint start, pace, dark exam, large-text review, bookmark and note saved to the server, phone width); the dark theme has not been checked on every page.

**Scanned papers (built 2026-10-28: `tools/ocr_pdf.py`, `tools/ingest_one.py`, OCR support in `tools/ingest_papers.py`; 3 new sittings, 195 questions; deployed)**: scanned PDFs are made searchable with local OCR (tesseract, no AI quota) and fed to the same ingester; the OCR text is only used to LOCATE questions, students always see the original page image, and every paper must still pass the strict checks against its official key (65 questions, types, marks) or it is refused. New numbering styles: `restart` (2019), `qn` (2017's exam-portal layout "Question Number : N  Correct : 1  Wrong : -0.33", where N is the key's number and the line gives the marks) and `qno` (2020's "Q.No. 6"). OCR repairs: markers misread as "Ql", "QI" or without the dot are normalised; a line at the marker margin that looks like a marker (such as "Qa4", "Oe", "Qs") and fills the next number is accepted; a run of numbers guessed from the sequence is accepted only if it exactly fills the gap between the explicit numbers around it (otherwise a lost marker would shift every later number and attach the wrong answer key, so the paper is refused instead). **Added: 2019 CS, 2017 CS1, 2017 CS2** (65 questions each, 100 marks each; 2019 has 41 MCQ and 24 NAT), with bootstrap topic tags in `data/tags/gate_cs_2019_2021.txt` (to be spot-checked by a person). 2019 is live through the development shortcut like 2018+; the 2017 sets stay drafts, like the other pre-2018 years. The question bank now holds 1,365 questions in 21 sittings (650 live). **Not added, and why**: 2020 (the OCR loses four question markers completely, so the paper is refused; a higher scan resolution made it worse); 2021 (its answer key is a scan that OCRs to noise such as "McQ", "Cc" and "CORD", and a misread key letter would silently mark students wrong, so it is not imported); 2015 (its key uses a layout the key importer does not support yet; its paper has three sessions in one file). Getting these needs a better reader for the lost markers and keys, which is a job for a vision model once Gemini quota is available.

**Formatted maths (built; `apps/web/js/math.js`, `apps/web/vendor/katex`, 3 tests; deployed)**: explanations are typeset with KaTeX 0.16.22, vendored (self-hosted, woff2 fonts only, about 0.9 MB, loaded only when a text contains maths). `$...$` is inline maths and `$$...$$` display maths; everything else is inserted as plain text, so no HTML can be injected; money such as "$5 and $6" is not mistaken for maths (no space inside the dollars, and a digit after the closing dollar disqualifies it) and `\$` is a literal dollar. The explanation writer's prompt asks for LaTeX in single dollars. Question stems are not run through it (text-mode stems come from the paper's text layer and are not LaTeX; maths-heavy questions are shown as page images).

**Gemini quota (finding 2026-10-28)**: the key works (it lists models and answered once), but `gemini-3.8-flash` is the only model it can call, it was often "overloaded" (503), and it now answers **429 "You exceeded your current quota, please check your plan and billing details"**. The pilot explanation run (4 questions) therefore stored nothing, correctly. Until quota is available (a daily reset, or billing enabled in Google AI Studio) neither the explanations nor the publish gate's AI solve can run on the real bank, so questions still go live through the development shortcut rather than the gate.

**Not built yet**: the AI solve step of the publish gate has not been run (blocked by Gemini quota, see above; the dev server still publishes everything as a clearly marked development shortcut), a framework version of the web app (optional), Redis-first autosave, difficulty bands for the shelf (§21.1), rate limiting (planned at the AWS WAF), scheduled/stored analysis snapshots (analysis is computed on request today), the AWS prototype stack has not been created yet (templates validated), and the full production infrastructure (§6).

**Policy (adopted)**: the development pool mixes 2013–2026 questions, but 2013–2018 papers have no MSQ and few NAT questions and used older formats. Test generation should probably draw full mocks from 2018 onwards only, and use the older years for PYQ mode and topic tests.

## Privacy tools (export and erase)

`GET /v1/me/export` returns everything held about the signed-in student as a JSON download (profile, attempts with every answer, notes, bookmarks). `DELETE /v1/me` erases the `app_user` row; tests, attempts, answers and notes follow by `ON DELETE CASCADE`, and question reports stay but lose the reporter (`ON DELETE SET NULL`). The home page has a "Your data" card with both buttons; delete asks for confirmation first.
Limit: this erases aceIt's copy only. The Cognito account (email and password) remains, so signing in again starts an empty profile. Deleting it needs a Cognito `AdminDeleteUser` call and an IAM permission for the app, not built yet.

## Sign-in page theme

The hosted Cognito page is themed with the app's lime and black (`infra/cognito-ui/ui.css` and `logo.png`). Cognito only accepts its own `*-customizable` class names, one selector per rule, and a logo of at most 100 KB. It is set on the app client, not in the stack, so re-apply it after recreating the pool:

    aws cognito-idp set-ui-customization --region ap-south-1 --user-pool-id <PoolId> --client-id <ClientId> --css file://infra/cognito-ui/ui.css --image-file fileb://infra/cognito-ui/logo.png

Changes take a few minutes to show because Cognito caches the page. To revert, call `delete-ui-customization`-style reset with no CSS or image.

## Username, trimmed home page, movable pad (2026-10-29)

- **Username**: `app_user.username` (3 to 20 letters, digits or underscores, unique ignoring case; migration `db/migrations/2026-10-29-username.sql`, also in `schema.sql`). After the first sign-in the web app asks for one before showing anything else; the header and greeting show it and never the email. `GET /v1/me` returns it, `PUT /v1/me/username` sets it (409 when taken, 422 when malformed). It is part of the data export and is erased with the account.
- **Removed**: the text-size button and its zoom rules, and the Past papers tab (the API still supports `kind: pyq`). A full mock is always assembled at random. Explanatory sentences were taken off the home page, the exam pad and the Your data card.
- **Dark mode**: pills, notices, labels and inputs on the lime and rose cards are now fixed dark-on-light, so they stay readable on the dark theme.
- **Rough-work pad**: drag it anywhere by its title bar; the drawing area is a fixed light paper so black ink is visible in both themes.
- **Defensive**: the result page tolerates a missing list in the analysis instead of crashing with "reading 'map'".

## Other model providers for the AI solve (2026-10-29)

`aceit/llm.py` now also drives any OpenAI-style chat provider (Groq, OpenRouter, Cerebras...). Set `LLM_BASE_URL`, `LLM_API_KEY` and optionally `LLM_MODEL`; it takes precedence over Gemini. Page images are sent as data URLs, so the model must accept images. Anthropic addresses are refused. The gate rule is unchanged (5 runs, at least 4 agreeing and matching the official key), so a weaker model holds more questions back; it never publishes a wrong one. Reason: with this Gemini key only `gemini-3.8-flash` is usable (the other models answer 404 "no longer available to new users") and it answered 503 "high demand" on every try on 2026-10-28 and 2026-10-29.
