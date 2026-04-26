CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text,
    phone text UNIQUE,
    email text,
    state text,
    created_at timestamp DEFAULT now()
);

ALTER TABLE users ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS allow_insert_users ON users;
CREATE POLICY allow_insert_users
ON users
FOR INSERT
WITH CHECK (true);

DROP POLICY IF EXISTS allow_select_users ON users;
CREATE POLICY allow_select_users
ON users
FOR SELECT
USING (true);

DROP POLICY IF EXISTS allow_update_users ON users;
CREATE POLICY allow_update_users
ON users
FOR UPDATE
USING (true);

CREATE TABLE IF NOT EXISTS user_messages (
    id bigserial PRIMARY KEY,
    phone text NOT NULL,
    role text NOT NULL,
    content text NOT NULL,
    created_at timestamp DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_messages_phone
ON user_messages(phone);
