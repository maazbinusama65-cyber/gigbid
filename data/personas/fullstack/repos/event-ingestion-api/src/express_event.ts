import express from 'express';

const app = express();
app.use(express.json());
app.post('/event_ingestion_api', async (req, res) => {
  if (!req.body?.id) return res.status(400).json({ error: 'id required' });
  res.status(201).json({ id: req.body.id });
});
export default app;
