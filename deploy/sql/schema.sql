-- aceIt question bank: schema v0 (PostgreSQL 15+, tested on 18)
-- Draft reference DDL. It becomes the first Alembic migration (apps/api/migrations).
-- Design: docs/system-design.md  (§7 keys, §11 data model, §20 trust ladder, §21 autonomy)
--
-- Principles
--   * Questions are versioned. Tests and attempts point at question_version, never at question,
--     so an edit can never rewrite history.
--   * Answer keys are rows, not a column: every key change is a new row, one is_current.
--   * What a student can see is decided in ONE place: the views at the bottom.
--   * Invariants live in the database (CHECK / unique indexes), not only in app code.

BEGIN;

-- ---------------------------------------------------------------- catalogue
CREATE TABLE exam (
    id    smallserial PRIMARY KEY,
    code  text NOT NULL UNIQUE,                     -- 'GATE'
    name  text NOT NULL
);

CREATE TABLE paper (
    id       smallserial PRIMARY KEY,
    exam_id  smallint NOT NULL REFERENCES exam(id),
    code     text NOT NULL,                         -- 'CS'
    name     text NOT NULL,                         -- 'Computer Science and Information Technology'
    UNIQUE (exam_id, code)
);

-- One row per real exam sitting of a paper: GATE CS 2024 has two (CS1, CS2).
CREATE TABLE paper_session (
    id               serial PRIMARY KEY,
    paper_id         smallint NOT NULL REFERENCES paper(id),
    year             smallint NOT NULL CHECK (year BETWEEN 2000 AND 2100),
    session_code     text NOT NULL,                 -- 'CS', 'CS1', 'CS2', ...
    organiser        text,                          -- 'IIT Madras'
    duration_min     smallint,
    total_marks      smallint,
    num_questions    smallint,                      -- expected count: the readiness check compares against it
    format           jsonb NOT NULL DEFAULT '{}',   -- marking scheme, sections, question types for THAT year
    key_provenance   text NOT NULL DEFAULT 'none'
                     CHECK (key_provenance IN ('official', 'reconstructed', 'none')),
    key_finality     text NOT NULL DEFAULT 'unconfirmed'
                     CHECK (key_finality IN ('final', 'provisional', 'unconfirmed')),
    availability     text NOT NULL DEFAULT 'draft'
                     CHECK (availability IN ('draft', 'live', 'held_back')),
    rank_eligible    boolean NOT NULL DEFAULT false,
    note             text,
    UNIQUE (paper_id, year, session_code),
    -- rank is only ever computed on official, final keys (design §7.1, §20.3)
    CHECK (NOT rank_eligible OR (key_provenance = 'official' AND key_finality = 'final')),
    -- a session with no key can never be live
    CHECK (availability <> 'live' OR key_provenance <> 'none')
);

CREATE TABLE topic (
    id           serial PRIMARY KEY,
    paper_id     smallint NOT NULL REFERENCES paper(id),
    parent_id    integer REFERENCES topic(id),
    slug         text NOT NULL,
    name         text NOT NULL,
    level        smallint NOT NULL DEFAULT 1,       -- 1 subject, 2 topic, 3 subtopic
    sort         integer NOT NULL DEFAULT 0,
    syllabus     text,                              -- e.g. 'GATE 2027'
    source       text NOT NULL DEFAULT 'syllabus',  -- 'general-gate' = not in the syllabus PDF, to be verified
    derived      boolean NOT NULL DEFAULT false,    -- a grouping label that is not in the syllabus wording
    UNIQUE (paper_id, slug)
);

CREATE TABLE topic_alias (
    id        serial PRIMARY KEY,
    topic_id  integer NOT NULL REFERENCES topic(id) ON DELETE CASCADE,
    alias     text NOT NULL,                        -- free-text matching for "test by topic name" (§20.1)
    source    text NOT NULL DEFAULT 'seed'
);
CREATE UNIQUE INDEX topic_alias_lower_uq ON topic_alias (lower(alias));

-- ---------------------------------------------------------------- source files
CREATE TABLE source_file (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind          text NOT NULL CHECK (kind IN ('question_paper', 'answer_key', 'syllabus', 'user_upload')),
    storage_key   text NOT NULL,                    -- S3 key (or local path during Phase 0)
    sha256        text NOT NULL UNIQUE,             -- same bytes are stored once
    bytes         bigint,
    pages         integer,
    text_layer    text CHECK (text_layer IN ('text', 'scan', 'mixed')),
    origin_url    text,                             -- where we got it, for provenance
    retrieved_at  timestamptz,
    note          text
);

CREATE TABLE paper_session_file (
    session_id  integer NOT NULL REFERENCES paper_session(id) ON DELETE CASCADE,
    file_id     uuid    NOT NULL REFERENCES source_file(id),
    role        text    NOT NULL CHECK (role IN ('question_paper', 'answer_key')),
    PRIMARY KEY (session_id, file_id, role)
);

-- ---------------------------------------------------------------- questions
CREATE TABLE app_user (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cognito_sub  text NOT NULL UNIQUE,
    email        text,
    role         text NOT NULL DEFAULT 'student' CHECK (role IN ('student', 'reviewer', 'admin')),
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE question (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id          integer REFERENCES paper_session(id),   -- null for generated / uploaded questions
    number              smallint,                                -- question number inside the sitting
    section             text CHECK (section IN ('GA', 'CS')),    -- GA vs subject, per paper
    q_type              text NOT NULL CHECK (q_type IN ('MCQ', 'MSQ', 'NAT')),
    marks               smallint NOT NULL CHECK (marks IN (1, 2)),
    origin              text NOT NULL CHECK (origin IN ('official_pyq', 'ai_generated', 'user_upload')),
    scope               text NOT NULL DEFAULT 'public' CHECK (scope IN ('public', 'private')),
    owner_id            uuid REFERENCES app_user(id) ON DELETE CASCADE,
    status              text NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft', 'held', 'live', 'quarantined', 'retired')),
    rank_eligible       boolean NOT NULL DEFAULT false,
    shuffle_safe        boolean NOT NULL DEFAULT false,          -- options may be reordered (§21.1)
    current_version_id  uuid,                                    -- FK added below (circular)
    created_at          timestamptz NOT NULL DEFAULT now(),
    CHECK (origin <> 'official_pyq' OR (session_id IS NOT NULL AND number IS NOT NULL)),
    CHECK ((scope = 'private') = (owner_id IS NOT NULL)),
    CHECK (NOT rank_eligible OR origin = 'official_pyq')
);
CREATE UNIQUE INDEX question_official_slot_uq
    ON question (session_id, number) WHERE origin = 'official_pyq';
CREATE INDEX question_status_idx ON question (status, scope);

CREATE TABLE question_version (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    question_id   uuid NOT NULL REFERENCES question(id) ON DELETE CASCADE,
    version       integer NOT NULL,
    stem_md       text NOT NULL,                    -- Markdown + LaTeX ($...$) for KaTeX
    options       jsonb,                            -- [{"label":"A","text":"..."}, ...]; null for NAT
    figures       jsonb NOT NULL DEFAULT '[]',      -- [{"file_id":..,"page":..,"bbox":[..]}]
    solution_md   text,
    solution_src  text CHECK (solution_src IN ('ai', 'reviewer')),
    extraction    jsonb NOT NULL DEFAULT '{}',      -- readers, agreement score, page, bbox (§7, §21.3)
    created_by    text NOT NULL DEFAULT 'pipeline',
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (question_id, version),
    CHECK (options IS NULL OR jsonb_typeof(options) = 'array')
);

ALTER TABLE question
    ADD CONSTRAINT question_current_version_fk
    FOREIGN KEY (current_version_id) REFERENCES question_version(id) DEFERRABLE INITIALLY DEFERRED;

-- A version's content is immutable once written. Edits create a new version.
CREATE FUNCTION question_version_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.stem_md IS DISTINCT FROM OLD.stem_md
       OR NEW.options IS DISTINCT FROM OLD.options
       OR NEW.figures IS DISTINCT FROM OLD.figures
       OR NEW.question_id IS DISTINCT FROM OLD.question_id THEN
        RAISE EXCEPTION 'question_version % is immutable: create a new version', OLD.id;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER question_version_immutable_trg
    BEFORE UPDATE ON question_version
    FOR EACH ROW EXECUTE FUNCTION question_version_immutable();

-- ---------------------------------------------------------------- answer keys
-- Every key change is a new row. Exactly one row per version is_current. That history IS the audit trail.
CREATE TABLE question_key (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    question_version_id uuid NOT NULL REFERENCES question_version(id) ON DELETE CASCADE,
    key_type            text NOT NULL CHECK (key_type IN ('mcq', 'msq', 'nat', 'mta', 'dropped')),
    answer              jsonb,                      -- mcq {"choice":"B"} | msq {"choices":["A","C"]} | nat {"min":2,"max":2.5}
    status              text NOT NULL CHECK (status IN (
                            'OFFICIAL', 'OFFICIAL_MTA', 'OFFICIAL_DROPPED', 'PROVISIONAL',
                            'REVIEWER_VERIFIED', 'AI_CONSENSUS', 'AI_UNVERIFIED', 'USER_PROVIDED', 'UNCERTAIN')),
    finality            text NOT NULL DEFAULT 'unconfirmed'
                        CHECK (finality IN ('final', 'provisional', 'unconfirmed')),
    source_file_id      uuid REFERENCES source_file(id),
    source_ref          text,                       -- page / row in the key file
    is_current          boolean NOT NULL DEFAULT true,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CHECK (key_type IN ('mta', 'dropped') OR answer IS NOT NULL),
    CHECK (key_type <> 'mcq' OR (answer ? 'choice') OR (answer ? 'any_of')),
    CHECK (key_type <> 'msq' OR (answer ? 'choices') OR (answer ? 'any_of')),
    CHECK (key_type <> 'nat' OR (answer ? 'min' AND answer ? 'max') OR (answer ? 'any_of')),
    -- several accepted answers are written {"any_of": [ {..}, {..} ]} (official keys sometimes accept two)
    CHECK (answer IS NULL OR NOT (answer ? 'any_of')
           OR (jsonb_typeof(answer -> 'any_of') = 'array' AND jsonb_array_length(answer -> 'any_of') >= 2)),
    -- an OFFICIAL status must come with a file it was read from
    CHECK (status NOT LIKE 'OFFICIAL%' OR source_file_id IS NOT NULL)
);
CREATE UNIQUE INDEX question_key_one_current_uq ON question_key (question_version_id) WHERE is_current;

-- Evidence for the automatic publish gate (§21.3): independent AI solves vs the key
CREATE TABLE ai_check (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    question_version_id  uuid NOT NULL REFERENCES question_version(id) ON DELETE CASCADE,
    model                text NOT NULL,
    solves               smallint NOT NULL,
    agree                smallint NOT NULL,          -- how many of the solves gave the same answer
    answer               jsonb,
    matches_key          boolean,                    -- agreed answer equals the current key
    detail               jsonb NOT NULL DEFAULT '{}',
    created_at           timestamptz NOT NULL DEFAULT now(),
    CHECK (agree BETWEEN 0 AND solves)
);

-- ---------------------------------------------------------------- official key staging
-- Official keys are imported from the key PDFs BEFORE the questions exist. They are stored per
-- (sitting, question number), exactly as read, and later attached to question_version rows as
-- question_key rows when the questions are ingested. raw_key keeps the original text for audit.
CREATE TABLE official_key_entry (
    id              bigserial PRIMARY KEY,
    session_id      integer  NOT NULL REFERENCES paper_session(id) ON DELETE CASCADE,
    exam_session    smallint NOT NULL DEFAULT 1,     -- the "Session" column in the file (merged keys repeat numbers per session)
    number          smallint NOT NULL,               -- slot 1..65 inside the sitting (GA first, then the rest, unless the key lists GA last)
    printed_number  smallint,                        -- the number printed in the key/paper (2018-2020 restart at 1 for the CS section)
    q_type          text     NOT NULL CHECK (q_type IN ('MCQ', 'MSQ', 'NAT')),
    section         text     NOT NULL,               -- as written: GA, CS, CS-1, ...
    marks           smallint NOT NULL CHECK (marks IN (1, 2)),
    key_type        text     NOT NULL CHECK (key_type IN ('mcq', 'msq', 'nat', 'mta', 'dropped')),
    answer          jsonb,
    raw_key         text     NOT NULL,
    source_file_id  uuid     NOT NULL REFERENCES source_file(id),
    imported_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (session_id, exam_session, number),
    CHECK (key_type IN ('mta', 'dropped') OR answer IS NOT NULL),
    CHECK (key_type <> 'mcq' OR (answer ? 'choice') OR (answer ? 'any_of')),
    CHECK (key_type <> 'msq' OR (answer ? 'choices') OR (answer ? 'any_of')),
    CHECK (key_type <> 'nat' OR (answer ? 'min' AND answer ? 'max') OR (answer ? 'any_of')),
    CHECK (answer IS NULL OR NOT (answer ? 'any_of')
           OR (jsonb_typeof(answer -> 'any_of') = 'array' AND jsonb_array_length(answer -> 'any_of') >= 2)),
    CHECK ((key_type = 'mcq' AND q_type = 'MCQ') OR (key_type = 'msq' AND q_type = 'MSQ')
        OR (key_type = 'nat' AND q_type = 'NAT') OR key_type IN ('mta', 'dropped'))
);

-- ---------------------------------------------------------------- tags, flags, stats
CREATE TABLE question_topic (
    question_id  uuid    NOT NULL REFERENCES question(id) ON DELETE CASCADE,
    topic_id     integer NOT NULL REFERENCES topic(id),
    is_primary   boolean NOT NULL DEFAULT false,
    confidence   real,
    source       text NOT NULL DEFAULT 'pipeline',
    PRIMARY KEY (question_id, topic_id)
);
CREATE UNIQUE INDEX question_one_primary_topic_uq ON question_topic (question_id) WHERE is_primary;
CREATE INDEX question_topic_topic_idx ON question_topic (topic_id);

-- Inputs to the automatic quarantine rules (§21.3)
CREATE TABLE question_flag (
    id           bigserial PRIMARY KEY,
    question_id  uuid NOT NULL REFERENCES question(id) ON DELETE CASCADE,
    kind         text NOT NULL CHECK (kind IN (
                     'student_report', 'negative_discrimination', 'takedown',
                     'low_extraction_confidence', 'ai_disagrees_with_key')),
    reporter_id  uuid REFERENCES app_user(id) ON DELETE SET NULL,
    detail       text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    resolved_at  timestamptz
);
CREATE INDEX question_flag_open_idx ON question_flag (question_id, kind) WHERE resolved_at IS NULL;

CREATE TABLE question_stats (
    question_id     uuid PRIMARY KEY REFERENCES question(id) ON DELETE CASCADE,
    attempts        integer NOT NULL DEFAULT 0,
    correct_rate    real,
    avg_time_s      real,
    discrimination  real,
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- tests and attempts (minimal v0)
CREATE TABLE test_instance (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id              smallint NOT NULL REFERENCES paper(id),
    kind                  text NOT NULL CHECK (kind IN ('full', 'subject', 'topic', 'pyq', 'custom', 'topic_ai', 'upload')),
    seed                  bigint,                    -- random seed: any test can be reproduced (§21.1)
    blueprint_version     text,
    question_version_ids  uuid[] NOT NULL,
    duration_s            integer NOT NULL CHECK (duration_s > 0),
    rank_eligible         boolean NOT NULL DEFAULT false,
    owner_id              uuid REFERENCES app_user(id) ON DELETE CASCADE,   -- null = shared shelf test
    shelf_key             text,                      -- 'full:rank' | 'full:practice' | 'subject:<slug>' | 'pair:rank' | 'pair:practice' while a shared test is on the shelf (§21.1); null otherwise
    pair_id               uuid,                      -- the two sets of a CS1/CS2-style pair share a pair_id (§21.1)
    pair_set              smallint CHECK (pair_set IN (1, 2)),
    created_at            timestamptz NOT NULL DEFAULT now(),
    CHECK ((pair_id IS NULL) = (pair_set IS NULL))
);

CREATE UNIQUE INDEX test_instance_pair_uq ON test_instance (pair_id, pair_set) WHERE pair_id IS NOT NULL;
CREATE INDEX test_instance_shelf_idx ON test_instance (shelf_key) WHERE shelf_key IS NOT NULL;

CREATE TABLE attempt (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    test_instance_id uuid NOT NULL REFERENCES test_instance(id),
    user_id          uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    started_at       timestamptz NOT NULL DEFAULT now(),
    deadline_at      timestamptz NOT NULL,           -- the server owns time (§10)
    submitted_at     timestamptz,
    status           text NOT NULL DEFAULT 'in_progress'
                     CHECK (status IN ('in_progress', 'submitted', 'auto_submitted', 'excluded')),
    score            numeric(6, 2),
    section_scores   jsonb,
    result           jsonb,                          -- full scored result, written once at submit
    last_seq         integer NOT NULL DEFAULT -1,    -- highest autosave sequence applied (makes retries idempotent)
    integrity        jsonb NOT NULL DEFAULT '{}',
    CHECK (deadline_at > started_at)
);
CREATE INDEX attempt_user_idx ON attempt (user_id, started_at DESC);
CREATE INDEX attempt_open_idx ON attempt (deadline_at) WHERE status = 'in_progress';   -- the sweeper's index

CREATE TABLE attempt_response (
    attempt_id           uuid NOT NULL REFERENCES attempt(id) ON DELETE CASCADE,
    question_version_id  uuid NOT NULL REFERENCES question_version(id),
    response             jsonb,
    palette_status       text NOT NULL DEFAULT 'not_visited'
                         CHECK (palette_status IN ('not_visited', 'not_answered', 'answered', 'marked', 'answered_marked')),
    time_spent_s         integer NOT NULL DEFAULT 0,
    is_correct           boolean,
    marks_awarded        numeric(4, 2),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (attempt_id, question_version_id)
);

-- ---------------------------------------------------------------- the visibility gate (views)
-- Every student-facing query reads these views. Nothing else decides what a student can see.

-- Public, live questions with their current version and current key, from a session that is live
-- and whose key is allowed in a scored test.
CREATE VIEW v_servable_question AS
SELECT q.id            AS question_id,
       qv.id           AS version_id,
       q.session_id,
       q.number, q.section, q.q_type, q.marks, q.origin, q.shuffle_safe,
       k.id            AS key_id,
       k.status        AS key_status,
       k.finality      AS key_finality,
       (q.rank_eligible
        AND ps.rank_eligible
        AND k.status IN ('OFFICIAL', 'OFFICIAL_MTA')
        AND k.finality = 'final')                       AS rank_eligible
FROM question q
JOIN question_version qv ON qv.id = q.current_version_id
JOIN question_key k      ON k.question_version_id = qv.id AND k.is_current
LEFT JOIN paper_session ps ON ps.id = q.session_id
WHERE q.status = 'live'
  AND q.scope = 'public'
  AND k.status <> 'OFFICIAL_DROPPED'
  AND k.status NOT IN ('UNCERTAIN')
  AND (q.session_id IS NULL OR ps.availability = 'live');

-- Questions allowed in a rank-bearing test: Official + final only.
CREATE VIEW v_rank_question AS
SELECT * FROM v_servable_question WHERE rank_eligible;

-- Per sitting: how far ingestion has got. Publishing is blocked unless keyed = expected.
CREATE VIEW v_session_readiness AS
SELECT ps.id AS session_id, ps.year, ps.session_code, ps.availability, ps.key_finality,
       ps.num_questions                                        AS expected,
       count(q.id)                                             AS parsed,
       count(q.id) FILTER (WHERE k.id IS NOT NULL)             AS keyed,
       count(q.id) FILTER (WHERE q.status = 'live')            AS live,
       (ps.num_questions IS NOT NULL
        AND count(q.id) = ps.num_questions
        AND count(q.id) FILTER (WHERE k.id IS NOT NULL) = ps.num_questions) AS publishable
FROM paper_session ps
LEFT JOIN question q ON q.session_id = ps.id AND q.origin = 'official_pyq'
LEFT JOIN question_version qv ON qv.id = q.current_version_id
LEFT JOIN question_key k ON k.question_version_id = qv.id AND k.is_current
GROUP BY ps.id;

COMMIT;
