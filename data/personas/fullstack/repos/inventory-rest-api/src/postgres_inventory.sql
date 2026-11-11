CREATE TABLE inventory_rest_api (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX inventory_rest_api_account_idx ON inventory_rest_api (account_id, created_at DESC);
