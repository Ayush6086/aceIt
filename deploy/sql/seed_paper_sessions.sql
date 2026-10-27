-- Seed: exam, paper and every GATE CS sitting we hold (from docs/pyq-sourcing-sheet.csv)
-- 2007-2012 are held_back: no official key, not published until verified (design §21.6 decision A).
-- num_questions is left NULL on purpose: v_session_readiness.publishable stays false until it is set from the paper.
BEGIN;
INSERT INTO exam (code, name) VALUES ('GATE', 'Graduate Aptitude Test in Engineering');
INSERT INTO paper (exam_id, code, name) SELECT id, 'CS', 'Computer Science and Information Technology' FROM exam WHERE code='GATE';
INSERT INTO paper_session (paper_id, year, session_code, key_provenance, key_finality, availability, note)
SELECT p.id, v.year, v.session_code, v.prov, v.fin, v.avail, v.note FROM paper p, (VALUES
  (2026::smallint,'CS1','official','unconfirmed','draft',''),
  (2026::smallint,'CS2','official','unconfirmed','draft',''),
  (2025::smallint,'CS1','official','unconfirmed','draft',''),
  (2025::smallint,'CS2','official','unconfirmed','draft',''),
  (2024::smallint,'CS1','official','final','draft',''),
  (2024::smallint,'CS2','official','final','draft',''),
  (2023::smallint,'CS','official','unconfirmed','draft',''),
  (2022::smallint,'CS','official','unconfirmed','draft',''),
  (2021::smallint,'CS1','official','unconfirmed','draft',''),
  (2021::smallint,'CS2','official','unconfirmed','draft',''),
  (2020::smallint,'CS','official','unconfirmed','draft',''),
  (2019::smallint,'CS','official','unconfirmed','draft',''),
  (2018::smallint,'CS','official','unconfirmed','draft',''),
  (2017::smallint,'CS1','official','unconfirmed','draft',''),
  (2017::smallint,'CS2','official','unconfirmed','draft',''),
  (2016::smallint,'CS1','official','final','draft',''),
  (2016::smallint,'CS2','official','final','draft',''),
  (2015::smallint,'CS1','official','unconfirmed','draft',''),
  (2015::smallint,'CS2','official','unconfirmed','draft',''),
  (2015::smallint,'CS3','official','unconfirmed','draft',''),
  (2014::smallint,'CS1','official','unconfirmed','draft',''),
  (2014::smallint,'CS2','official','unconfirmed','draft',''),
  (2014::smallint,'CS3','official','unconfirmed','draft',''),
  (2013::smallint,'CS-A','official','unconfirmed','draft','ORS paper code A'),
  (2013::smallint,'CS-B','official','unconfirmed','draft','ORS paper code B'),
  (2013::smallint,'CS-C','official','unconfirmed','draft','ORS paper code C'),
  (2013::smallint,'CS-D','official','unconfirmed','draft','ORS paper code D'),
  (2012::smallint,'CS','none','unconfirmed','held_back','no official key found; held back until verified'),
  (2011::smallint,'CS','none','unconfirmed','held_back','no official key found; held back until verified'),
  (2010::smallint,'CS','none','unconfirmed','held_back','no official key found; held back until verified'),
  (2009::smallint,'CS','none','unconfirmed','held_back','no official key found; held back until verified'),
  (2008::smallint,'CS','none','unconfirmed','held_back','no official key found; held back until verified'),
  (2007::smallint,'CS','none','unconfirmed','held_back','no official key found; held back until verified')
) AS v(year, session_code, prov, fin, avail, note) WHERE p.code='CS';
COMMIT;
