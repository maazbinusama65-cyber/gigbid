CREATE TABLE competitor_price_scraper (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX competitor_price_scraper_account_idx ON competitor_price_scraper (account_id, created_at DESC);
