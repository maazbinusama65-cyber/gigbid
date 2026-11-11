CREATE TABLE marketplace_payouts (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX marketplace_payouts_account_idx ON marketplace_payouts (account_id, created_at DESC);
