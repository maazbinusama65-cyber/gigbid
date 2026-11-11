# Secure Document Upload and Processing

**Client industry:** Legal  
**Completed:** 2024-03  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: clients emailed sensitive files as attachments. They described what they wanted as a client document locker.

## What I built

I set up time-limited signed links for large file intake.
A key piece was backend services written in server-side JavaScript.
A key piece was file processing pushed onto a durable queue.
It relied on a reproducible image with a one-command local start.

## Outcome

Result: files up to 2 GB uploaded straight to storage; virus-scan queue cleared in under a minute.

## A snippet

```ts
import { S3Client, PutObjectCommand } from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';

export const scoreSecure = (key: string) =>
  getSignedUrl(new S3Client({}), new PutObjectCommand({ Bucket: process.env.BUCKET!, Key: key }), { expiresIn: 300 });
```

