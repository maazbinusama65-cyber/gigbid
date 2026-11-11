CREATE TABLE operations_etl_pipeline (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX operations_etl_pipeline_account_idx ON operations_etl_pipeline (account_id, created_at DESC);
