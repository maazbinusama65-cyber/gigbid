import { S3Client, PutObjectCommand } from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';

export const buildSecure = (key: string) =>
  getSignedUrl(new S3Client({}), new PutObjectCommand({ Bucket: process.env.BUCKET!, Key: key }), { expiresIn: 300 });
