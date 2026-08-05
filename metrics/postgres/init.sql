CREATE TABLE IF NOT EXISTS requests (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    provider TEXT NOT NULL,
    trigger TEXT,
    messages JSONB,
    response TEXT,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER,
    success BOOLEAN NOT NULL DEFAULT true,
    error TEXT
);

CREATE INDEX IF NOT EXISTS requests_ts_idx ON requests (ts DESC);
CREATE INDEX IF NOT EXISTS requests_provider_idx ON requests (provider);
