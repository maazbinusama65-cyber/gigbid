import { MongoClient } from 'mongodb';

const col = new MongoClient(process.env.MONGO_URL!).db('event_ingestion_api').collection('events');
export const routeEvent = async () => { await col.createIndex({ ts: 1 }, { expireAfterSeconds: 7776000 }); };
