-- A public display name chosen by the student (3 to 20 letters, digits or underscores), unique ignoring case. Null until they pick one.
ALTER TABLE app_user ADD COLUMN IF NOT EXISTS username text CHECK (username ~ '^[A-Za-z0-9_]{3,20}$');
CREATE UNIQUE INDEX IF NOT EXISTS app_user_username_idx ON app_user (lower(username));
