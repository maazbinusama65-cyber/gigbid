import { Queue, Worker } from 'bullmq';

const connection = { host: '127.0.0.1', port: 6379 };
export const q = new Queue('secure_document_intake', { connection });
new Worker('secure_document_intake', async (job) => ({ done: job.id }), { connection, concurrency: 4 });
