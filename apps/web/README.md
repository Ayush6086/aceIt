# aceIt web app

Dependency-free: plain HTML, CSS and ES modules, no build step, served by the API itself (`ACEIT_WEB_DIR`).

    cd apps/web && node --test tests/                    # 8 tests of the exam console logic (timer, palette, autosave batching)

    # see it with real questions (needs the PDFs; builds a local database the first time)
    tools/build_dev_sql.sh ~/Downloads/GATE
    cd apps/api && .venv/bin/python dev_server.py        # http://localhost:8000, sign in with any name (DEVELOPMENT ONLY)

Screens: sign-in, home (create a test by topic or a full mock, recent tests), the exam console, and the result with a review.
Design tokens and rules are in docs/system-design.md §19. Question text is always inserted as text, never as HTML.
A framework (Next.js, per the design doc) can replace this later; the API contract does not change.
