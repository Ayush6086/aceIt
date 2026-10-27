-- Invariant tests for db/schema.sql. Run against any database that has schema.sql + seed_paper_sessions.sql loaded
-- (real keys, topics and questions may be loaded too: the tests use their own fixture sitting, year 2099):
--   psql -v ON_ERROR_STOP=1 -d aceit_test -f db/tests/invariants.sql
-- Everything runs in one transaction and is rolled back, so it leaves no data behind.
BEGIN;

CREATE FUNCTION pg_temp.must_fail(label text, stmt text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    BEGIN
        EXECUTE stmt;
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'PASS  %  (rejected: %)', label, left(SQLERRM, 60);
        RETURN;
    END;
    RAISE EXCEPTION 'FAIL  %: accepted but must be rejected', label;
END $$;

CREATE FUNCTION pg_temp.expect(label text, cond boolean) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    IF cond IS TRUE THEN RAISE NOTICE 'PASS  %', label;
    ELSE RAISE EXCEPTION 'FAIL  %', label; END IF;
END $$;

-- fixture sitting that no real data uses
INSERT INTO paper_session (paper_id, year, session_code, key_provenance, key_finality)
SELECT id, 2099, 'T1', 'official', 'final' FROM paper WHERE code = 'CS';

-- 1. sittings with no key can never go live
SELECT pg_temp.must_fail('2010 (no key) cannot be made live',
  $$UPDATE paper_session SET availability='live' WHERE year=2010$$);

-- 2. rank eligibility needs an official AND final key
SELECT pg_temp.must_fail('2025 (key not confirmed final) cannot be rank_eligible',
  $$UPDATE paper_session SET rank_eligible=true WHERE year=2025 AND session_code='CS1'$$);
UPDATE paper_session SET rank_eligible=true, availability='live', num_questions=2
 WHERE year=2099 AND session_code='T1';
SELECT pg_temp.expect('a fixture sitting with an official final key can be live and rank_eligible',
  (SELECT rank_eligible AND availability='live' FROM paper_session WHERE year=2099 AND session_code='T1'));

-- fixtures: one key file, two official questions in the fixture sitting
INSERT INTO source_file (id, kind, storage_key, sha256)
VALUES ('00000000-0000-0000-0000-0000000000f1','answer_key','keys/fixture_key.pdf','sha-f1');

INSERT INTO question (id, session_id, number, section, q_type, marks, origin, status, rank_eligible)
SELECT x.id::uuid, ps.id, x.n, 'GA', 'MCQ', 1, 'official_pyq', 'live', true
FROM paper_session ps,
     (VALUES ('00000000-0000-0000-0000-0000000000a1', 1), ('00000000-0000-0000-0000-0000000000a2', 2)) x(id, n)
WHERE ps.year=2099 AND ps.session_code='T1';

INSERT INTO question_version (id, question_id, version, stem_md, options) VALUES
 ('00000000-0000-0000-0000-0000000000b1','00000000-0000-0000-0000-0000000000a1',1,'Q1 stem','[{"label":"A","text":"x"},{"label":"B","text":"y"}]'),
 ('00000000-0000-0000-0000-0000000000b2','00000000-0000-0000-0000-0000000000a2',1,'Q2 stem','[{"label":"A","text":"x"},{"label":"B","text":"y"}]');
UPDATE question SET current_version_id='00000000-0000-0000-0000-0000000000b1' WHERE id='00000000-0000-0000-0000-0000000000a1';
UPDATE question SET current_version_id='00000000-0000-0000-0000-0000000000b2' WHERE id='00000000-0000-0000-0000-0000000000a2';

-- 3. an unkeyed question is invisible to students
SELECT pg_temp.expect('question without a key is not servable', (SELECT count(*) = 0 FROM v_servable_question));

-- 4. key rules
SELECT pg_temp.must_fail('OFFICIAL key without a source file is rejected',
  $$INSERT INTO question_key (question_version_id,key_type,answer,status,finality)
    VALUES ('00000000-0000-0000-0000-0000000000b1','mcq','{"choice":"B"}','OFFICIAL','final')$$);
SELECT pg_temp.must_fail('MCQ key without a choice is rejected',
  $$INSERT INTO question_key (question_version_id,key_type,answer,status,finality,source_file_id)
    VALUES ('00000000-0000-0000-0000-0000000000b1','mcq','{"x":1}','OFFICIAL','final','00000000-0000-0000-0000-0000000000f1')$$);
SELECT pg_temp.must_fail('NAT key without a min/max range is rejected',
  $$INSERT INTO question_key (question_version_id,key_type,answer,status,finality,source_file_id)
    VALUES ('00000000-0000-0000-0000-0000000000b1','nat','{"min":1}','OFFICIAL','final','00000000-0000-0000-0000-0000000000f1')$$);

INSERT INTO question_key (question_version_id,key_type,answer,status,finality,source_file_id) VALUES
 ('00000000-0000-0000-0000-0000000000b1','mcq','{"choice":"B"}','OFFICIAL','final','00000000-0000-0000-0000-0000000000f1'),
 ('00000000-0000-0000-0000-0000000000b2','mcq','{"choice":"A"}','OFFICIAL','final','00000000-0000-0000-0000-0000000000f1');

SELECT pg_temp.must_fail('a second current key on the same version is rejected',
  $$INSERT INTO question_key (question_version_id,key_type,answer,status,finality,source_file_id)
    VALUES ('00000000-0000-0000-0000-0000000000b1','mcq','{"choice":"C"}','OFFICIAL','final','00000000-0000-0000-0000-0000000000f1')$$);

-- 5. visibility gate
SELECT pg_temp.expect('keyed official questions in a live sitting are servable', (SELECT count(*) = 2 FROM v_servable_question));
SELECT pg_temp.expect('official+final questions are rank-eligible', (SELECT count(*) = 2 FROM v_rank_question));

UPDATE question_key SET status='REVIEWER_VERIFIED', finality='unconfirmed'
 WHERE question_version_id='00000000-0000-0000-0000-0000000000b2';
SELECT pg_temp.expect('a non-official key is servable but NOT rank-eligible',
  (SELECT count(*) = 2 FROM v_servable_question) AND (SELECT count(*) = 1 FROM v_rank_question));

UPDATE question SET status='quarantined' WHERE id='00000000-0000-0000-0000-0000000000a2';
SELECT pg_temp.expect('quarantined question disappears from the gate', (SELECT count(*) = 1 FROM v_servable_question));

UPDATE paper_session SET availability='draft' WHERE year=2099 AND session_code='T1';
SELECT pg_temp.expect('questions of a non-live sitting are hidden', (SELECT count(*) = 0 FROM v_servable_question));
UPDATE paper_session SET availability='live' WHERE year=2099 AND session_code='T1';

-- 6. versions are immutable, edits create a new version
SELECT pg_temp.must_fail('editing a version''s stem is rejected',
  $$UPDATE question_version SET stem_md='changed' WHERE id='00000000-0000-0000-0000-0000000000b1'$$);

-- 7. private questions need an owner; only official PYQs can be rank-eligible
SELECT pg_temp.must_fail('private question without an owner is rejected',
  $$INSERT INTO question (q_type,marks,origin,scope) VALUES ('MCQ',1,'user_upload','private')$$);
SELECT pg_temp.must_fail('an AI-generated question cannot be rank_eligible',
  $$INSERT INTO question (q_type,marks,origin,rank_eligible) VALUES ('MCQ',1,'ai_generated',true)$$);
SELECT pg_temp.must_fail('an official question needs a sitting and a number',
  $$INSERT INTO question (q_type,marks,origin) VALUES ('MCQ',1,'official_pyq')$$);
SELECT pg_temp.must_fail('the same question number cannot appear twice in a sitting',
  $$INSERT INTO question (session_id,number,q_type,marks,origin)
    SELECT id,1,'MCQ',1,'official_pyq' FROM paper_session WHERE year=2099 AND session_code='T1'$$);

-- 8. readiness: cannot publish until every expected question is parsed and keyed
SELECT pg_temp.expect('fixture sitting readiness: 2 expected, 2 parsed, 2 keyed, publishable',
  (SELECT expected=2 AND parsed=2 AND keyed=2 AND publishable FROM v_session_readiness WHERE year=2099 AND session_code='T1'));
SELECT pg_temp.expect('a sitting with unknown question count is never publishable',
  (SELECT NOT publishable FROM v_session_readiness WHERE year=2019 AND session_code='CS'));

-- 8b. staged official keys (official_key_entry)
SELECT pg_temp.must_fail('a staged NAT key without a range is rejected',
  $$INSERT INTO official_key_entry (session_id,number,q_type,section,marks,key_type,answer,raw_key,source_file_id)
    SELECT id,1,'NAT','CS',1,'nat','{"min":1}','1',(SELECT id FROM source_file LIMIT 1) FROM paper_session WHERE year=2099 AND session_code='T1'$$);
SELECT pg_temp.must_fail('a key whose type does not match the question type is rejected',
  $$INSERT INTO official_key_entry (session_id,number,q_type,section,marks,key_type,answer,raw_key,source_file_id)
    SELECT id,1,'MCQ','GA',1,'nat','{"min":1,"max":2}','1 to 2',(SELECT id FROM source_file LIMIT 1) FROM paper_session WHERE year=2099 AND session_code='T1'$$);
SELECT pg_temp.must_fail('any_of with a single answer is rejected',
  $$INSERT INTO official_key_entry (session_id,number,q_type,section,marks,key_type,answer,raw_key,source_file_id)
    SELECT id,1,'MSQ','CS',1,'msq','{"any_of":[{"choices":["A"]}]}','A',(SELECT id FROM source_file LIMIT 1) FROM paper_session WHERE year=2099 AND session_code='T1'$$);
INSERT INTO official_key_entry (session_id,number,q_type,section,marks,key_type,answer,raw_key,source_file_id)
SELECT id,1,'MSQ','CS',1,'msq','{"any_of":[{"choices":["A","C"]},{"choices":["C"]}]}','A,C or C',(SELECT id FROM source_file LIMIT 1)
FROM paper_session WHERE year=2099 AND session_code='T1';
SELECT pg_temp.expect('a key with two accepted answers is stored', (SELECT count(*)=1 FROM official_key_entry WHERE raw_key='A,C or C'));
SELECT pg_temp.must_fail('the same question number cannot be staged twice for a sitting',
  $$INSERT INTO official_key_entry (session_id,number,q_type,section,marks,key_type,answer,raw_key,source_file_id)
    SELECT id,1,'MSQ','CS',1,'msq','{"choices":["B"]}','B',(SELECT id FROM source_file LIMIT 1) FROM paper_session WHERE year=2099 AND session_code='T1'$$);

-- 9. held-back years stay out of the gate
SELECT pg_temp.expect('2007-2012 sittings are all held_back',
  (SELECT bool_and(availability='held_back') FROM paper_session WHERE year BETWEEN 2007 AND 2012));

SELECT 'ALL INVARIANT TESTS PASSED' AS result;
ROLLBACK;
