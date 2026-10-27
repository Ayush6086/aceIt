"""Test database: a throwaway PostgreSQL with the real schema, the real topic list and a synthetic copy of the real
question pool (975 questions with the real subjects, marks, types and sittings). Skipped when PostgreSQL is missing."""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
PG_BIN = next((p for p in (os.environ.get("PG_BIN", ""), "/Library/PostgreSQL/18/bin", "/opt/homebrew/opt/postgresql@17/bin", "/usr/local/bin") if p and (Path(p) / "initdb").exists()), None)


def q(s) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def bank_sql(pool: list[dict]) -> str:
    out = ["BEGIN;", "INSERT INTO source_file (id, kind, storage_key, sha256) VALUES ('00000000-0000-0000-0000-00000000f001', 'answer_key', 'fixture', 'fixture');"]
    sittings = {}
    for r in pool:
        year, _, code = r["sitting"].partition("_")
        sittings[r["sitting"]] = (int(year), code)
    for label, (year, code) in sittings.items():
        out.append(f"UPDATE paper_session SET availability = 'live'" + (", rank_eligible = true" if label in {"2016_CS1", "2016_CS2", "2024_CS1", "2024_CS2"} else "")
                   + f" WHERE year = {year} AND session_code = {q(code)};")
    for r in pool:
        year, code = sittings[r["sitting"]]
        sess = f"(SELECT id FROM paper_session WHERE year = {year} AND session_code = {q(code)})"
        rank = "true" if r["rank_eligible"] else "false"
        out.append(f"INSERT INTO question (session_id, number, section, q_type, marks, origin, status, rank_eligible) VALUES ({sess}, {r['number']}, {q(r['section'])}, {q(r['type'])}, {r['marks']}, 'official_pyq', 'live', {rank});")
        qid = f"(SELECT id FROM question WHERE session_id = {sess} AND number = {r['number']})"
        opts = "NULL" if r["type"] == "NAT" else q(json.dumps([{"label": c, "text": c.lower()} for c in "ABCD"])) + "::jsonb"
        out.append(f"INSERT INTO question_version (question_id, version, stem_md, options, extraction) VALUES ({qid}, 1, {q('Question ' + r['id'])}, {opts}, '{{\"display\":\"text\"}}');")
        vid = f"(SELECT id FROM question_version WHERE question_id = {qid})"
        out.append(f"UPDATE question SET current_version_id = {vid} WHERE id = {qid};")
        if r["key_type"] == "mta":
            key_type, answer = "mta", "NULL"
        else:
            key_type = {"MCQ": "mcq", "MSQ": "msq", "NAT": "nat"}[r["type"]]
            answer = q(json.dumps({"mcq": {"choice": "A"}, "msq": {"choices": ["A", "B"]}, "nat": {"min": 1, "max": 1}}[key_type])) + "::jsonb"
        status = "OFFICIAL_MTA" if key_type == "mta" else "OFFICIAL"
        out.append(f"INSERT INTO question_key (question_version_id, key_type, answer, status, finality, source_file_id) SELECT {vid}, {q(key_type)}, {answer}, {q(status)}, ps.key_finality, '00000000-0000-0000-0000-00000000f001' FROM paper_session ps WHERE ps.id = {sess};")
        out.append(f"INSERT INTO question_topic (question_id, topic_id, is_primary) SELECT {qid}, t.id, true FROM topic t WHERE t.slug = {q(r['topic'])};")
    out.append("COMMIT;")
    return "\n".join(out)


@pytest.fixture(scope="session")
def pg():
    if not PG_BIN:
        pytest.skip("PostgreSQL binaries not found (set PG_BIN)")
    import load_taxonomy
    tmp = Path(tempfile.mkdtemp(prefix="aceit-pg-"))
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = {**os.environ, "PATH": f"{PG_BIN}:{os.environ['PATH']}"}
    run = lambda *a, **k: subprocess.run(a, check=True, capture_output=True, text=True, env=env, **k)
    run("initdb", "-D", str(tmp / "data"), "-U", "postgres", "--auth=trust", "-E", "UTF8")
    run("pg_ctl", "-D", str(tmp / "data"), "-o", f"-p {port} -k {tmp} -c listen_addresses=''", "-l", str(tmp / "log"), "-w", "start")
    psql = lambda *a: run("psql", "-h", str(tmp), "-p", str(port), "-U", "postgres", "-v", "ON_ERROR_STOP=1", "-q", *a)
    try:
        psql("-c", "CREATE DATABASE aceit")
        for f in (ROOT / "db" / "schema.sql", ROOT / "db" / "seed_paper_sessions.sql"):
            psql("-d", "aceit", "-f", str(f))
        (tmp / "tax.sql").write_text(load_taxonomy.emit(json.loads(load_taxonomy.DATA.read_text())))
        psql("-d", "aceit", "-f", str(tmp / "tax.sql"))
        pool = json.loads((ROOT / "data" / "pool" / "gate_cs_dev_pool.json").read_text())
        (tmp / "bank.sql").write_text(bank_sql(pool))
        psql("-d", "aceit", "-f", str(tmp / "bank.sql"))
        yield f"host={tmp} port={port} user=postgres dbname=aceit"
    finally:
        subprocess.run(["pg_ctl", "-D", str(tmp / "data"), "-m", "immediate", "stop"], env=env, capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)
