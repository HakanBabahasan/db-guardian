-- DB Guardian — Demo Production Verisi
-- Bu dosya container ilk başlatıldığında otomatik çalışır.

-- ── Tablolar ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    username    VARCHAR(100) NOT NULL UNIQUE,
    email       VARCHAR(255) NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS payments (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    amount      NUMERIC(12, 2) NOT NULL,
    status      VARCHAR(30) NOT NULL DEFAULT 'pending',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS orders (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    total       NUMERIC(12, 2) NOT NULL,
    status      VARCHAR(30) NOT NULL DEFAULT 'new',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ── Demo verileri ────────────────────────────────────────────────────────────

INSERT INTO users (username, email) VALUES
  ('alice',   'alice@example.com'),
  ('bob',     'bob@example.com'),
  ('charlie', 'charlie@example.com'),
  ('diana',   'diana@example.com'),
  ('eve',     'eve@example.com');

INSERT INTO payments (user_id, amount, status) VALUES
  (1, 100.00, 'completed'),
  (1, 250.50, 'completed'),
  (2, 75.00,  'pending'),
  (3, 500.00, 'completed'),
  (4, 33.99,  'failed'),
  (5, 1200.00,'completed');

INSERT INTO orders (user_id, total, status) VALUES
  (1, 350.50, 'completed'),
  (2, 75.00,  'processing'),
  (3, 500.00, 'completed'),
  (4, 33.99,  'cancelled'),
  (5, 1200.00,'completed');
