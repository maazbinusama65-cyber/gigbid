# secure-document-intake

> secure file intake - repository for the legal engagement.

## Features

- Uses **S3 presigned uploads** (see `src/`)
- A JavaScript server process handling concurrent requests
- File processing pushed onto a durable queue
- A reproducible image with a one-command local start

## Quick start

```bash
npm install
npm run dev
```

## Layout

- `src/s3_uploads_secure.ts`
- `src/nodejs_secure.ts`
- `src/bullmq_secure.ts`

## Status

Delivered and handed over; this repository is the frozen client copy.
