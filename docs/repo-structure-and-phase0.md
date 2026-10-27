# aceIt: Repo Structure and Phase 0 Plan (draft v0.1)

Companion to [system-design.md](system-design.md). **Update:** the platform runs with no human in the loop (design §21), so the admin review UI and test builder are out of v1, P0-20 becomes a script, and the two spikes (P0-17, P0-18) are gating. Decisions below follow it: FastAPI, Next.js, AWS ap-south-1, modular monolith.

## 1. Repo structure

**One monorepo** (`aceit`). One repo means one PR can change the API, the web client and the infra together, and one CI pipeline covers it. We do not split into multiple repos or services until a measured need appears.

```
aceit/
├── apps/
│   ├── web/                      Next.js (TypeScript, Tailwind, Radix). Student app + /admin (role-gated)
│   │   ├── src/app/              routes: dashboard, tests, exam/[attemptId], results, review, admin/*
│   │   ├── src/components/       card, pill, stat-tile, progress-bar, palette-button, ...
│   │   ├── src/exam/             exam console: isolated route bundle, no chart/dashboard imports
│   │   ├── src/styles/tokens.css design tokens from system-design §19.1
│   │   └── .storybook/
│   └── api/                      FastAPI service + workers (ONE Python package, two entrypoints)
│       ├── src/aceit/
│       │   ├── main.py           API entrypoint
│       │   ├── worker.py         SQS worker entrypoint (ingest | solve | score | analytics | email)
│       │   ├── platform/         config, logging, auth (Cognito JWT), db session, redis, quotas, errors
│       │   ├── identity/         users, roles
│       │   ├── catalog/          exam, paper, topic taxonomy, aliases, blueprints
│       │   ├── content/          questions, versions, keys, key history, tags
│       │   ├── ingestion/        page prep, dual readers (vision LLM + Textract), structuring, key import
│       │   ├── review/           reviewer queues, blind-first verification, key-override approval
│       │   ├── testing/          assembler, topic resolver, generation jobs, test instances
│       │   ├── session/          attempts, autosave, timer, resume, submit, force-submit
│       │   ├── scoring/          marks, negative marking, normalisation estimate, re-scoring
│       │   ├── analytics/        topic/time/strategy analysis, mastery, predictions, rank
│       │   ├── uploads/          student PDF uploads, format detection, private scope
│       │   └── admin/            PDF upload, blueprint editor, test builder
│       ├── migrations/           Alembic
│       ├── tests/                unit/ (pure logic), integration/ (db+redis), contract/ (API)
│       └── pyproject.toml
├── packages/
│   └── api-client/               TypeScript client generated from the API's OpenAPI schema
├── infra/                        AWS CDK (Python): network, data, auth, compute, pipeline, monitoring
│   ├── stacks/
│   └── app.py
├── data/
│   ├── taxonomy/gate_cs.json     topic taxonomy (built from the GATE CS syllabus, checked by tools/load_taxonomy.py)
│   ├── blueprints/               exam format JSON per paper and year
│   └── golden/                   hand-verified extraction samples (small, text only)
├── docs/                         system-design.md, this file, decisions/ (ADRs), runbooks/
├── scripts/                      dev helpers, sourcing-sheet tools
├── tools/ingest-spike/           throwaway experiments for the vision-LLM extraction spike (not shipped)
├── .github/workflows/            ci.yml, deploy-dev.yml, deploy-staging.yml, deploy-prod.yml
├── docker-compose.yml            local Postgres, Redis, LocalStack (S3, SQS)
├── Makefile                      make setup | dev | test | lint | migrate | seed
├── CODEOWNERS
└── README.md
```

**Not in git**: the PYQ PDFs and keys (large binaries, and the rights question in §7.2 of the design doc). They live in a private S3 bucket (`aceit-<env>-source`) and are listed in `docs/pyq-sourcing-sheet.csv`. Only small text fixtures go in `data/golden/`.

### Rules that keep the monolith modular
1. **One-way imports**: `api routes → module services → module repositories`. A module never imports another module's repository or tables. It calls the other module's service functions. (Enforced in CI with `import-linter`.)
2. **Pure logic stays pure**: `scoring/`, `testing/assembler`, `session/timer` have no I/O in their core functions, so they are unit-testable without a database. These are the highest-risk logic (marks, deadlines).
3. **Private-scope filter in one place**: every query returning questions goes through `content` repository helpers that apply `scope = 'public' OR owner_id = :me` (design §20.4). A test tries to read another user's private question.
4. **One worker image**: the API and the workers are the same container image with different commands, so there is one build and one set of dependencies.
5. **Web exam bundle is isolated**: `src/exam/` may not import charts or dashboard code (lint rule), to keep the console small and fast.

### Tooling choices (kept boring)
| Area | Choice |
|---|---|
| Python | 3.12, `uv` for deps and venv, `ruff` (lint+format), `pyright` (types), `pytest` |
| API | FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, `redis-py`, `boto3` |
| Web | pnpm, TypeScript strict, ESLint, Playwright (E2E), Storybook, Vitest |
| Infra | AWS CDK in Python (same language as the backend, no extra DSL) |
| Local | Docker Compose with LocalStack for S3/SQS |
| Git flow | Trunk-based, short-lived branches, PR required, CI green, 1 review, conventional commits |
| Quality gates in CI | ruff, pyright, pytest, import-linter, eslint, tsc, vitest, `cdk synth`, secret scan, dependency audit |

## 2. Phase 0 plan: foundations (2 weeks, 10 working days)

### Assumptions
- Team: 1 backend/infra engineer, 1 full-stack engineer, you as product owner, 1 reviewer (part-time). Adjust the calendar if the team is smaller.
- Goal of Phase 0: **a walking skeleton deployed to AWS through CI**, plus the data foundations Phase 1 needs. No student features yet.

### Day-1 decisions (blocking)
| # | Decision | Recommendation |
|---|---|---|
| D1 | AWS account layout | Separate AWS accounts for `dev`, `staging`, `prod` under one AWS Organization. Cheap, and prevents test data touching prod |
| D2 | Domain name and email sender | Choose and register now, so Cognito, SES and TLS can be set up |
| D3 | GitHub org and repo name | `aceit` monorepo |
| D4 | Bedrock model and region | Confirm the chosen Claude model is available to our account in ap-south-1. If not, plan the cross-region call (question text only) |
| D5 | Budget guardrails | AWS Budgets alarm per account; a hard monthly cap on Bedrock |

### Tasks

| ID | Task | Est. | Done when |
|---|---|---|---|
| **Track A: repo and tooling** | | | |
| P0-01 | Create the monorepo with the structure above, README, CODEOWNERS, Makefile | 0.5d | `make setup && make test` works on a clean clone |
| P0-02 | CI: lint, types, unit tests, import-linter, secret scan, `cdk synth` | 1d | PR is blocked on red CI |
| P0-03 | Local env: Docker Compose (Postgres, Redis, LocalStack), `make dev` | 1d | API and web run locally against it. **Check free disk space first: Docker images need several GB** |
| **Track B: data foundations** | | | |
| P0-04 | Schema v0 + Alembic migrations: users, exam, paper, topic, source_pdf, question, question_version, question_key_history, test_template, test_instance, attempt, attempt_response, audit_log (design §11) | 2d | Migrations apply and roll back cleanly in CI |
| P0-05 | GATE CS topic taxonomy from the official syllabus (`CS_GATE2027_Syllabus.pdf`, already on your Mac), with aliases, as `data/taxonomy/gate_cs.json` + `tools/load_taxonomy.py` (**done**, see design doc §7.3) | 1.5d | Taxonomy loads; every topic has a parent subject; reviewed by the reviewer |
| P0-06 | Exam blueprint v0 for GATE CS (65 questions, 100 marks, GA 15 / subject 85, types, marking) as data, plus per-year variants noted for older papers | 1d | Blueprint JSON validates against a schema; scoring unit tests read it |
| P0-07 | Scoring core v0 (MCQ, MSQ, NAT, negative marking) as pure functions with tests | 1.5d | Table-driven tests pass for each question type and marks value |
| **Track C: cloud foundations (CDK)** | | | |
| P0-08 | Network stack: VPC, private/public subnets in 2 AZs, VPC endpoints (S3, SQS, Bedrock, Secrets) | 1d | `cdk deploy` to dev succeeds |
| P0-09 | Data stack: Aurora PostgreSQL (small), RDS Proxy, ElastiCache Redis (Multi-AZ), S3 buckets (source, assets) with KMS and versioning | 1.5d | API can connect from inside the VPC |
| P0-10 | Auth stack: Cognito user pool (email OTP, Google sign-in), roles (`student`, `reviewer`, `admin`) as groups | 1d | A test user signs in and gets a JWT |
| P0-11 | Compute stack: ECR, ECS Fargate API service behind ALB + WAF, SQS queues with DLQs, worker service | 1.5d | `/health` is reachable over HTTPS |
| P0-12 | Observability baseline: structured JSON logs, CloudWatch dashboards and alarms (5xx, queue age, DB CPU), Sentry, budget alarms | 1d | A deliberately failing request raises an alarm |
| P0-13 | CD pipeline: build image, run migrations, deploy to dev on merge; staging on tag; prod behind manual approval; automatic rollback on alarm | 1.5d | Merge to main deploys dev with no manual step |
| **Track D: walking skeleton (vertical slice)** | | | |
| P0-14 | API platform: config, Cognito JWT verification, role checks, error format, OpenAPI export, generated `api-client` | 1.5d | Protected endpoint rejects bad/expired tokens in tests |
| P0-15 | Web skeleton: Next.js app, design tokens (design §19.1), five base components in Storybook (card, pill, progress bar, stat tile, palette button), sign-in flow | 2d | Storybook published; contrast check passes AA |
| P0-16 | **Slice**: signed-in admin uploads a PDF (presigned S3 URL) → API records `source_pdf` → SQS message → worker logs it and updates the status → UI shows the status | 1.5d | Works end-to-end in dev, on real AWS |
| **Track E: de-risking spikes** | | | |
| P0-17 | **Extraction spike**: run the vision LLM on 3 pages (one clean 2024 page, one 2019 scan, one 2011 scan with a diagram) and compare with Textract; measure character accuracy on a hand-checked sample | 2d | A short report with accuracy and cost per page, and a go/no-go for the dual-reader design |
| P0-18 | **AI-key spike**: run the 5-solve consensus on about 30 questions from 2022–2024 and compare with the official keys | 1d | Agreement rate by topic recorded, as the first data point for §7.4 |
| **Track F: non-code (runs in parallel)** | | | |
| P0-19 | Pick the golden set: about 100 questions across 3 years (to be hand-verified by the reviewer in Phase 1) | 0.5d | List committed to `data/golden/` |
| P0-20 | Check each official key's heading or source (final vs provisional) and fill the `key_status` column of the sourcing sheet | 1.5d (reviewer) | No year left as `UNCONFIRMED` without a reason |
| P0-21 | Legal review request: PYQ reuse rights, user-upload terms and takedown process | start day 1 | Written guidance, or a named owner and date |
| P0-22 | Write ADRs: modular monolith, FastAPI, Redis-first exam state, official-key-as-truth, AI-key policy | 1d | Merged under `docs/decisions/` |

Total engineering effort is about 26 person-days across two engineers, which fits in two weeks with margin for the spikes. Tracks A to C are mostly sequential for the infra engineer. Tracks B and D are mostly for the full-stack engineer. Track E is shared. Track F is yours and the reviewer's.

### Suggested calendar
| Days | Backend / infra engineer | Full-stack engineer | You / reviewer |
|---|---|---|---|
| 1 | D1-D5 decisions, P0-01 | P0-01, P0-03 | D1-D5, start P0-21 |
| 2-3 | P0-02, P0-08 | P0-04 | P0-19 |
| 4-5 | P0-09, P0-10 | P0-04, P0-05 | P0-05 review, P0-20 |
| 6-7 | P0-11, P0-13 | P0-06, P0-07 | P0-20 |
| 8 | P0-12, P0-14 | P0-14, P0-15 | P0-22 review |
| 9 | P0-16 | P0-15, P0-16 | P0-17/18 results |
| 10 | P0-17, P0-18 | P0-17, P0-18 | Phase 0 review |

### Exit criteria (Phase 0 done = all true)
1. A merge to `main` deploys to **dev** with no manual step, and **staging** on a tag, through CI/CD.
2. A signed-in admin can upload a PDF and see its status change through the SQS worker (the walking skeleton, P0-16).
3. The schema v0, taxonomy and blueprint are loaded, and the scoring core has passing tests.
4. Bedrock access in the chosen region is confirmed, and the extraction and AI-key spike reports exist with a go/no-go decision.
5. Budget alarms and baseline alarms are active in all three accounts.
6. The sourcing sheet has a verified `key_status` for every year with a key, and the golden set is chosen.
7. The legal question has an owner and a date.

### Risks for Phase 0
| Risk | Mitigation |
|---|---|
| The extraction spike shows the vision LLM is poor on the old scans | Learn it in week 2, not in Phase 1. Fallback: more reviewer time, or hold back the scanned years (they are already last in the order) |
| Bedrock model not available in ap-south-1 | Decide cross-region early (D4). Only question text leaves Mumbai |
| AWS account setup and quota requests are slow | Start on day 1, and request Bedrock access and any quota increases immediately |
| Local machine disk or RAM too low for Docker | Check free disk now. Use a remote dev environment if needed |
| Scope creep into student features | Phase 0 has no student features. Anything not in the exit criteria goes to Phase 1 |

### Open items for you
1. Team size: confirm the two-engineer assumption.
2. The AWS accounts layout (D1) and the domain name (D2).
3. Who owns the legal review (P0-21)?
