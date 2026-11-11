CREATE TABLE clinic_appointment_booking (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX clinic_appointment_booking_account_idx ON clinic_appointment_booking (account_id, created_at DESC);
