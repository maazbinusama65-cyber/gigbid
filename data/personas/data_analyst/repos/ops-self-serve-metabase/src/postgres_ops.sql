CREATE TABLE ops_self_serve_metabase (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ops_self_serve_metabase_account_idx ON ops_self_serve_metabase (account_id, created_at DESC);
