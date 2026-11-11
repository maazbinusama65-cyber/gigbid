CREATE TABLE service_marketplace_backend (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX service_marketplace_backend_account_idx ON service_marketplace_backend (account_id, created_at DESC);
