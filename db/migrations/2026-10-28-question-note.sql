-- Bookmarks and private notes: one row per student per question (not per version, so they survive a question being re-versioned).
CREATE TABLE IF NOT EXISTS question_note (
    user_id      uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    question_id  uuid NOT NULL REFERENCES question(id) ON DELETE CASCADE,
    bookmarked   boolean NOT NULL DEFAULT false,
    note         text NOT NULL DEFAULT '' CHECK (char_length(note) <= 2000),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, question_id)
);
CREATE INDEX IF NOT EXISTS question_note_bookmarks_idx ON question_note (user_id) WHERE bookmarked;
