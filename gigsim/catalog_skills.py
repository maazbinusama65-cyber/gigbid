"""Skill lexicon: canonical name, 'implied' phrasings (no tool name) and code snippets.

Implied phrases are noun phrases usable both as "I built <phrase>" and "We need <phrase>".
Code templates use __PKG__ / __FN__ / __CLS__ placeholders (never str.format: braces are code).
"""
from __future__ import annotations

from dataclasses import dataclass

CATEGORIES = {
    "ai_ml": "AI & Machine Learning",
    "web": "Web Development",
    "analytics": "Data Analytics",
    "data_eng": "Data Engineering",
    "devops": "DevOps & Cloud",
    "mobile": "Mobile Development",
    "design": "Design & Creative",
    "writing": "Writing & Translation",
    "marketing": "Sales & Marketing",
}


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    category: str
    implied: tuple[str, ...]
    lang: str | None = None
    code: str | None = None


SKILLS: dict[str, Skill] = {}


def _s(id, name, cat, implied, lang=None, code=None):
    SKILLS[id] = Skill(id, name, cat, tuple(implied), lang, code)


# ---- AI / ML ------------------------------------------------------------------------------
_s("python", "Python", "ai_ml", ["scripts and services in a typed, tested codebase", "a set of small automation tools"])
_s("huggingface", "Hugging Face Transformers", "ai_ml",
   ["a pretrained language model fine-tuned from a public model hub", "transformer checkpoints loaded through a model hub"],
   "py", "from transformers import AutoTokenizer, AutoModelForSequenceClassification\n\ntok = AutoTokenizer.from_pretrained('distilbert-base-uncased')\nmodel = AutoModelForSequenceClassification.from_pretrained('distilbert-base-uncased', num_labels=6)\n\ndef __FN__(texts):\n    batch = tok(texts, truncation=True, padding=True, return_tensors='pt')\n    return model(**batch).logits.softmax(-1)")
_s("nlp", "NLP", "ai_ml", ["text understanding for messy free-form customer messages", "language processing over thousands of short documents"],
   "py", "import re\n\nSTOP = {'the', 'a', 'an', 'and', 'to'}\n\ndef __FN__(text):\n    toks = [t for t in re.findall(r'[a-z0-9]+', text.lower()) if t not in STOP]\n    return {'tokens': toks, 'n': len(toks)}")
_s("fastapi", "FastAPI", "ai_ml", ["a typed async HTTP service with auto-generated docs", "a small Python web API with request validation"],
   "py", "from fastapi import FastAPI\nfrom pydantic import BaseModel\n\napp = FastAPI()\n\nclass Req(BaseModel):\n    text: str\n\n@app.post('/__PKG__/predict')\nasync def __FN__(req: Req):\n    return {'label': 'ok', 'chars': len(req.text)}")
_s("docker", "Docker", "devops", ["containerised builds that run the same on every machine", "a reproducible image with a one-command local start"],
   "dockerfile", "FROM python:3.11-slim\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install --no-cache-dir -r requirements.txt\nCOPY src ./src\nCMD [\"python\", \"-m\", \"src.main\"]")
_s("mlflow", "MLflow", "ai_ml", ["experiment tracking with comparable runs and a model registry", "every training run logged with its parameters and metrics"],
   "py", "import mlflow\n\ndef __FN__(params, metrics):\n    with mlflow.start_run(run_name='__PKG__'):\n        mlflow.log_params(params)\n        mlflow.log_metrics(metrics)")
_s("rag", "RAG", "ai_ml", ["answers grounded in retrieved passages with source citations", "a question-answering layer that looks things up before it writes"],
   "py", "def __FN__(question, retriever, llm):\n    ctx = retriever.search(question, k=5)\n    prompt = 'Answer using only these sources:\\n' + '\\n'.join(c['text'] for c in ctx)\n    return llm(prompt + '\\nQ: ' + question), [c['id'] for c in ctx]")
_s("embeddings", "embeddings", "ai_ml", ["meaning-based similarity instead of keyword matching", "dense vector representations of text for nearest-neighbour lookup"],
   "py", "import numpy as np\n\ndef __FN__(a, b):\n    a, b = np.asarray(a), np.asarray(b)\n    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))")
_s("vector_db", "Pinecone", "ai_ml", ["a managed nearest-neighbour index holding millions of vectors", "a hosted similarity-search store with metadata filters"],
   "py", "from pinecone import Pinecone\n\npc = Pinecone(api_key='...')\nindex = pc.Index('__PKG__')\n\ndef __FN__(vec, industry):\n    return index.query(vector=vec, top_k=8, filter={'industry': industry})")
_s("langchain", "LangChain", "ai_ml", ["chained prompts, tools and memory wired into one assistant", "an orchestration layer for multi-step language-model calls"],
   "py", "from langchain_core.prompts import ChatPromptTemplate\n\nprompt = ChatPromptTemplate.from_messages([('system', 'Be concise.'), ('human', '{q}')])\n\ndef __FN__(llm, q):\n    return (prompt | llm).invoke({'q': q})")
_s("openai_api", "OpenAI API", "ai_ml", ["hosted large-language-model calls with retries and cost caps", "a commercial LLM endpoint behind our own thin wrapper"],
   "py", "from openai import OpenAI\n\nclient = OpenAI()\n\ndef __FN__(prompt):\n    r = client.chat.completions.create(model='gpt-4o-mini', messages=[{'role': 'user', 'content': prompt}], temperature=0.2)\n    return r.choices[0].message.content")
_s("sklearn", "scikit-learn", "ai_ml", ["classical models with cross-validated pipelines", "a tabular baseline with preprocessing and grid search"],
   "py", "from sklearn.pipeline import make_pipeline\nfrom sklearn.preprocessing import StandardScaler\nfrom sklearn.linear_model import LogisticRegression\n\ndef __FN__():\n    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=500, class_weight='balanced'))")
_s("xgboost", "XGBoost", "ai_ml", ["gradient-boosted trees tuned for imbalanced outcomes", "a boosted-tree scorer that beat the logistic baseline"],
   "py", "import xgboost as xgb\n\ndef __FN__(X, y, pos_weight):\n    return xgb.XGBClassifier(n_estimators=400, max_depth=5, learning_rate=0.05, scale_pos_weight=pos_weight).fit(X, y)")
_s("pandas", "pandas", "analytics", ["tabular wrangling in dataframes with merges and group-bys", "scripted reshaping of large spreadsheets into tidy tables"],
   "py", "import pandas as pd\n\ndef __FN__(df: pd.DataFrame) -> pd.DataFrame:\n    return (df.dropna(subset=['id']).assign(month=lambda d: pd.to_datetime(d['date']).dt.to_period('M')).groupby('month', as_index=False).agg(total=('amount', 'sum')))")
_s("ab_testing", "A/B testing", "analytics", ["controlled experiments with a pre-registered success metric", "split tests read out with confidence intervals"],
   "py", "from math import sqrt\n\ndef __FN__(c_a, n_a, c_b, n_b):\n    p_a, p_b = c_a / n_a, c_b / n_b\n    se = sqrt(p_a * (1 - p_a) / n_a + p_b * (1 - p_b) / n_b)\n    return (p_b - p_a) / se")
_s("timeseries", "time-series forecasting", "ai_ml", ["seasonal weekly predictions with holiday effects", "forward-looking numbers built from past daily history"],
   "py", "from prophet import Prophet\n\ndef __FN__(df, horizon=28):\n    m = Prophet(weekly_seasonality=True, yearly_seasonality=True)\n    m.fit(df.rename(columns={'date': 'ds', 'units': 'y'}))\n    return m.predict(m.make_future_dataframe(periods=horizon))")
_s("postgres", "PostgreSQL", "data_eng", ["a relational store with proper indexes and migrations", "SQL tables with constraints, not loose files"],
   "sql", "CREATE TABLE __PKG__ (\n    id BIGSERIAL PRIMARY KEY,\n    account_id BIGINT NOT NULL,\n    payload JSONB NOT NULL,\n    created_at TIMESTAMPTZ NOT NULL DEFAULT now()\n);\nCREATE INDEX __PKG___account_idx ON __PKG__ (account_id, created_at DESC);")
_s("airflow", "Airflow", "data_eng", ["scheduled multi-step workflows with retries and backfills", "a nightly DAG that reruns safely when a step fails"],
   "py", "from airflow import DAG\nfrom airflow.operators.python import PythonOperator\nfrom datetime import datetime\n\nwith DAG('__PKG__', start_date=datetime(2024, 1, 1), schedule='@daily', catchup=False) as dag:\n    PythonOperator(task_id='__FN__', python_callable=lambda: None)")
_s("computer_vision", "computer vision", "ai_ml", ["camera images turned into structured readings", "pictures of paper or parts analysed automatically"],
   "py", "import cv2\n\ndef __FN__(path):\n    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)\n    img = cv2.GaussianBlur(img, (3, 3), 0)\n    _, th = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)\n    return th")
_s("pytorch", "PyTorch", "ai_ml", ["a hand-written training loop on GPU with mixed precision", "a neural network trained end to end with custom data loaders"],
   "py", "import torch\nfrom torch import nn\n\ndef __FN__(model, loader, opt):\n    model.train()\n    for x, y in loader:\n        opt.zero_grad()\n        loss = nn.functional.cross_entropy(model(x), y)\n        loss.backward()\n        opt.step()")
_s("celery", "Celery", "ai_ml", ["background workers consuming a Redis-backed task queue", "long jobs pushed off the request path into a retrying worker pool"],
   "py", "from celery import Celery\n\napp = Celery('__PKG__', broker='redis://localhost:6379/0')\n\n@app.task(bind=True, max_retries=3, default_retry_delay=30)\ndef __FN__(self, payload):\n    try:\n        return {'ok': True, 'n': len(payload)}\n    except Exception as exc:\n        raise self.retry(exc=exc)")
_s("redis", "Redis", "data_eng", ["an in-memory cache with expiry in front of the database", "a fast key-value layer for sessions and rate limits"],
   "py", "import redis\n\nr = redis.Redis()\n\ndef __FN__(key, compute, ttl=300):\n    hit = r.get(key)\n    if hit is not None:\n        return hit\n    val = compute()\n    r.setex(key, ttl, val)\n    return val")
_s("recsys", "recommender systems", "ai_ml", ["'people who liked this also liked' suggestions", "a personalised ranking of items per shopper"],
   "py", "import numpy as np\n\ndef __FN__(user_vec, item_mat, k=10):\n    scores = item_mat @ user_vec\n    return np.argsort(-scores)[:k].tolist()")
_s("whisper", "Whisper", "ai_ml", ["automatic speech-to-text on recorded phone calls", "audio recordings transcribed with timestamps"],
   "py", "import whisper\n\nmodel = whisper.load_model('small')\n\ndef __FN__(path):\n    out = model.transcribe(path, word_timestamps=False)\n    return out['text'], out['segments']")
_s("onnx", "ONNX Runtime", "ai_ml", ["an exported model served on CPU in milliseconds", "a framework-neutral model file loaded by a lean runtime"],
   "py", "import onnxruntime as ort\n\nsess = ort.InferenceSession('model.onnx', providers=['CPUExecutionProvider'])\n\ndef __FN__(x):\n    return sess.run(None, {sess.get_inputs()[0].name: x})[0]")
_s("aws_sagemaker", "SageMaker", "devops", ["managed cloud training jobs and hosted endpoints", "a cloud-managed model endpoint behind autoscaling"],
   "py", "import sagemaker\n\ndef __FN__(role, image, s3_out):\n    est = sagemaker.estimator.Estimator(image, role, instance_count=1, instance_type='ml.m5.xlarge', output_path=s3_out)\n    est.fit({'train': 's3://__PKG__/train'})\n    return est")
_s("finetuning", "LoRA fine-tuning", "ai_ml", ["a small adapter trained on domain text instead of a full retrain", "parameter-efficient adaptation of a base model"],
   "py", "from peft import LoraConfig, get_peft_model\n\ndef __FN__(base):\n    cfg = LoraConfig(r=16, lora_alpha=32, target_modules=['q_proj', 'v_proj'], lora_dropout=0.05)\n    return get_peft_model(base, cfg)")
_s("model_eval", "model evaluation", "ai_ml", ["held-out metrics, error slices and calibration checks", "a scorecard that shows where the model fails, not just one number"],
   "py", "from sklearn.metrics import classification_report\n\ndef __FN__(y_true, y_pred, slices):\n    out = {'all': classification_report(y_true, y_pred, output_dict=True)}\n    for name, idx in slices.items():\n        out[name] = classification_report([y_true[i] for i in idx], [y_pred[i] for i in idx], output_dict=True)\n    return out")
_s("prompt_eng", "prompt engineering", "ai_ml", ["carefully versioned instructions and few-shot examples for a language model", "instructions tuned until the output format stopped breaking"],
   "py", "SYSTEM = 'You are a concise assistant. Reply as JSON with keys: summary, next_step.'\n\ndef __FN__(llm, text, examples):\n    shots = '\\n'.join(f'IN: {i}\\nOUT: {o}' for i, o in examples)\n    return llm(SYSTEM + '\\n' + shots + '\\nIN: ' + text + '\\nOUT:')")
_s("sql", "SQL", "analytics", ["hand-written analytical queries with window functions", "reporting queries over millions of rows"],
   "sql", "WITH monthly AS (\n    SELECT date_trunc('month', created_at) AS m, customer_id, SUM(amount) AS spend\n    FROM orders GROUP BY 1, 2\n)\nSELECT m, COUNT(*) AS buyers, AVG(spend) AS avg_spend,\n       SUM(spend) OVER (ORDER BY m) AS running_total\nFROM monthly GROUP BY m ORDER BY m;")
# distractor-only skills (never requested by jobs: weight 0)
_s("regex_bots", "rule-based chatbot", "ai_ml", ["canned replies chosen by keyword rules"], "py", "import re\n\nRULES = [(re.compile(r'refund|money back', re.I), 'refund_policy'), (re.compile(r'hours|open', re.I), 'opening_hours')]\n\ndef __FN__(text):\n    return next((a for r, a in RULES if r.search(text)), 'fallback')")
_s("openpyxl_reports", "openpyxl reports", "analytics", ["a script that fills an Excel template"], "py", "from openpyxl import load_workbook\n\ndef __FN__(path, rows):\n    wb = load_workbook(path)\n    ws = wb.active\n    for r in rows:\n        ws.append(r)\n    wb.save(path)")
_s("static_site", "static HTML site", "web", ["a hand-coded five-page brochure site"], None, None)

# ---- Full-stack ---------------------------------------------------------------------------
_s("typescript", "TypeScript", "web", ["strictly typed JavaScript across client and server", "shared type definitions between front end and back end"],
   "ts", "export interface __CLS__ {\n  id: string;\n  status: 'active' | 'paused' | 'cancelled';\n  updatedAt: string;\n}\n\nexport function __FN__(x: __CLS__): boolean {\n  return x.status === 'active';\n}")
_s("react", "React", "web", ["a component-based single-page interface with hooks", "an interactive front end split into reusable components"],
   "ts", "import { useState } from 'react';\n\nexport function __CLS__({ items }: { items: string[] }) {\n  const [q, setQ] = useState('');\n  const shown = items.filter((i) => i.toLowerCase().includes(q.toLowerCase()));\n  return (<div><input value={q} onChange={(e) => setQ(e.target.value)} /><ul>{shown.map((i) => <li key={i}>{i}</li>)}</ul></div>);\n}")
_s("nextjs", "Next.js", "web", ["server-rendered React pages with route-level data fetching", "a site with file-based routing and incremental regeneration"],
   "ts", "export const revalidate = 60;\n\nexport default async function Page() {\n  const res = await fetch(process.env.API_URL + '/__PKG__', { next: { revalidate } });\n  const data = await res.json();\n  return <pre>{JSON.stringify(data, null, 2)}</pre>;\n}")
_s("nodejs", "Node.js", "web", ["a JavaScript server process handling concurrent requests", "backend services written in server-side JavaScript"],
   "ts", "import http from 'node:http';\n\nconst server = http.createServer((req, res) => {\n  res.setHeader('content-type', 'application/json');\n  res.end(JSON.stringify({ ok: true, path: req.url }));\n});\nserver.listen(3000);")
_s("express", "Express", "web", ["a minimal routing layer with middleware for auth and logging", "an HTTP API assembled from small route handlers"],
   "ts", "import express from 'express';\n\nconst app = express();\napp.use(express.json());\napp.post('/__PKG__', async (req, res) => {\n  if (!req.body?.id) return res.status(400).json({ error: 'id required' });\n  res.status(201).json({ id: req.body.id });\n});\nexport default app;")
_s("stripe", "Stripe", "web", ["card payments, subscriptions and webhooks handled safely", "a hosted payments provider with signed event callbacks"],
   "ts", "import Stripe from 'stripe';\n\nconst stripe = new Stripe(process.env.STRIPE_KEY!);\n\nexport async function __FN__(customer: string, price: string) {\n  return stripe.subscriptions.create({ customer, items: [{ price }], payment_behavior: 'default_incomplete' });\n}")
_s("prisma", "Prisma", "web", ["a type-safe database layer generated from a schema file", "migrations and queries driven from one declarative schema"],
   "ts", "import { PrismaClient } from '@prisma/client';\n\nconst db = new PrismaClient();\n\nexport const __FN__ = (accountId: string) =>\n  db.invoice.findMany({ where: { accountId }, orderBy: { createdAt: 'desc' }, take: 50 });")
_s("tailwind", "Tailwind CSS", "web", ["utility-first styling with a shared design-token config", "a consistent look without hand-written stylesheets"],
   "ts", "export const Button = ({ children }: { children: React.ReactNode }) => (\n  <button className=\"rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 focus:ring-2\">{children}</button>\n);")
_s("websockets", "WebSockets", "web", ["a persistent two-way connection pushing updates to the browser", "live messages delivered without polling"],
   "ts", "import { WebSocketServer } from 'ws';\n\nconst wss = new WebSocketServer({ port: 8080 });\nwss.on('connection', (ws) => {\n  ws.on('message', (m) => wss.clients.forEach((c) => c.send(m.toString())));\n});")
_s("rest_api", "REST API design", "web", ["versioned JSON endpoints with consistent errors and pagination", "a documented HTTP interface other teams could build against"],
   "ts", "export function paginate<T>(rows: T[], cursor = 0, limit = 50) {\n  const page = rows.slice(cursor, cursor + limit);\n  return { data: page, next: cursor + limit < rows.length ? cursor + limit : null };\n}")
_s("jwt_auth", "JWT authentication", "web", ["stateless signed tokens with refresh rotation", "login sessions carried in short-lived signed tokens"],
   "ts", "import jwt from 'jsonwebtoken';\n\nexport const issue = (sub: string) => jwt.sign({ sub }, process.env.JWT_SECRET!, { expiresIn: '15m' });\nexport const verify = (t: string) => jwt.verify(t, process.env.JWT_SECRET!);")
_s("django", "Django", "web", ["a batteries-included Python web framework with an admin site", "model-driven server-rendered pages and an ORM"],
   "py", "from django.db import models\n\nclass __CLS__(models.Model):\n    name = models.CharField(max_length=120)\n    starts_at = models.DateTimeField(db_index=True)\n    is_cancelled = models.BooleanField(default=False)\n\n    class Meta:\n        ordering = ['starts_at']")
_s("bullmq", "BullMQ", "web", ["a Redis-backed job queue for Node with retries and delayed jobs", "file processing pushed onto a durable queue"],
   "ts", "import { Queue, Worker } from 'bullmq';\n\nconst connection = { host: '127.0.0.1', port: 6379 };\nexport const q = new Queue('__PKG__', { connection });\nnew Worker('__PKG__', async (job) => ({ done: job.id }), { connection, concurrency: 4 });")
_s("s3_uploads", "S3 presigned uploads", "devops", ["browser-to-bucket file uploads that never pass through our server", "time-limited signed links for large file intake"],
   "ts", "import { S3Client, PutObjectCommand } from '@aws-sdk/client-s3';\nimport { getSignedUrl } from '@aws-sdk/s3-request-presigner';\n\nexport const __FN__ = (key: string) =>\n  getSignedUrl(new S3Client({}), new PutObjectCommand({ Bucket: process.env.BUCKET!, Key: key }), { expiresIn: 300 });")
_s("oauth", "OAuth 2.0 / SSO", "web", ["staff sign in with their existing company Google or Microsoft account", "delegated login via an identity provider"],
   "ts", "export const authorizeUrl = (clientId: string, redirect: string, state: string) =>\n  'https://accounts.example.com/oauth/authorize?' + new URLSearchParams({ response_type: 'code', client_id: clientId, redirect_uri: redirect, scope: 'openid email', state });")
_s("graphql", "GraphQL", "web", ["a single query endpoint where clients pick the fields they need", "a typed schema stitched over several backends"],
   "ts", "export const typeDefs = `\n  type Item { id: ID! title: String! price: Float! }\n  type Query { items(limit: Int = 20): [Item!]! }\n`;\nexport const resolvers = { Query: { items: (_: unknown, a: { limit: number }, ctx: any) => ctx.db.items(a.limit) } };")
_s("github_actions", "GitHub Actions", "devops", ["push-triggered build, test and deploy workflows", "automated checks on every pull request"],
   "yaml", "name: ci\non: [push, pull_request]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-node@v4\n        with: { node-version: 20 }\n      - run: npm ci && npm test")
_s("aws", "AWS", "devops", ["cloud hosting with managed queues, storage and load balancing", "infrastructure on a major public cloud with least-privilege roles"],
   "yaml", "Resources:\n  Bucket:\n    Type: AWS::S3::Bucket\n    Properties:\n      BucketName: __PKG__-uploads\n      PublicAccessBlockConfiguration: { BlockPublicAcls: true, RestrictPublicBuckets: true }")
_s("playwright", "Playwright", "web", ["scripted real-browser checks of the main user journeys", "end-to-end regression runs across three browsers"],
   "ts", "import { test, expect } from '@playwright/test';\n\ntest('__FN__', async ({ page }) => {\n  await page.goto('/');\n  await page.getByRole('link', { name: 'Sign in' }).click();\n  await expect(page).toHaveURL(/login/);\n});")
_s("elasticsearch", "Elasticsearch", "data_eng", ["typo-tolerant full-text search with facet counts", "an inverted-index search service beside the main database"],
   "ts", "export const query = (q: string, brand?: string) => ({\n  query: { bool: { must: [{ multi_match: { query: q, fields: ['title^3', 'body'], fuzziness: 'AUTO' } }], filter: brand ? [{ term: { brand } }] : [] } },\n  aggs: { brands: { terms: { field: 'brand' } } },\n});")
_s("supabase", "Supabase", "web", ["a hosted Postgres with row-level security and instant APIs", "a backend-as-a-service for auth, storage and database"],
   "ts", "import { createClient } from '@supabase/supabase-js';\n\nconst sb = createClient(process.env.SUPABASE_URL!, process.env.SUPABASE_ANON_KEY!);\n\nexport const __FN__ = () => sb.from('articles').select('id,title').eq('published', true).order('published_at', { ascending: false });")
_s("mongodb", "MongoDB", "data_eng", ["a document store for loosely structured event records", "schemaless collections with TTL indexes"],
   "ts", "import { MongoClient } from 'mongodb';\n\nconst col = new MongoClient(process.env.MONGO_URL!).db('__PKG__').collection('events');\nexport const __FN__ = async () => { await col.createIndex({ ts: 1 }, { expireAfterSeconds: 7776000 }); };")
_s("jest", "Jest", "web", ["fast unit tests with mocks and snapshot checks", "a test runner wired into the commit hook"],
   "ts", "import { paginate } from './paginate';\n\ntest('__FN__ returns null cursor on last page', () => {\n  expect(paginate([1, 2, 3], 0, 5).next).toBeNull();\n});")
_s("wordpress_theme", "WordPress theme", "web", ["a brochure site on a hosted blogging CMS"], None, None)
_s("jquery_plugin", "jQuery plugin", "web", ["a legacy page slider script"], "ts", "$.fn.__FN__ = function () { return this.each(function () { $(this).fadeToggle(); }); };")
_s("static_html", "static HTML", "web", ["a hand-coded landing page"], None, None)

# ---- Data analyst ------------------------------------------------------------------------
_s("tableau", "Tableau", "analytics", ["interactive drill-down dashboards for area managers", "a published workbook with filters and calculated fields"],
   "sql", "-- custom SQL behind the workbook\nSELECT region, store_id, DATE_TRUNC('week', sold_at) AS week, SUM(net_amount) AS revenue\nFROM sales WHERE sold_at >= CURRENT_DATE - INTERVAL '26 weeks'\nGROUP BY 1, 2, 3;")
_s("kpi_dashboards", "KPI dashboards", "analytics", ["a one-page scorecard that leadership reads on Monday", "targets versus actuals with traffic-light status"],
   "sql", "SELECT metric, actual, target, CASE WHEN actual >= target THEN 'green' WHEN actual >= 0.9 * target THEN 'amber' ELSE 'red' END AS status\nFROM weekly_kpis WHERE week = (SELECT MAX(week) FROM weekly_kpis);")
_s("cohort_analysis", "cohort analysis", "analytics", ["month-by-month survival curves for customers by signup month", "retention triangles showing who stays"],
   "sql", "SELECT date_trunc('month', first_order) AS cohort,\n       date_part('month', age(o.created_at, first_order)) AS month_n,\n       COUNT(DISTINCT o.customer_id) AS active\nFROM orders o JOIN firsts f USING (customer_id)\nGROUP BY 1, 2 ORDER BY 1, 2;")
_s("statistics", "statistics", "analytics", ["significance tests, confidence intervals and effect sizes", "careful inference instead of eyeballing charts"],
   "py", "from scipy import stats\n\ndef __FN__(a, b):\n    t, p = stats.ttest_ind(a, b, equal_var=False)\n    return {'t': float(t), 'p': float(p)}")
_s("bigquery", "BigQuery", "data_eng", ["a serverless warehouse queried over billions of event rows", "partitioned cloud tables keeping scan costs low"],
   "sql", "SELECT event_name, COUNT(DISTINCT user_pseudo_id) AS users\nFROM `proj.analytics.events_*`\nWHERE _TABLE_SUFFIX BETWEEN '20240101' AND '20240131'\nGROUP BY event_name ORDER BY users DESC;")
_s("looker_studio", "Looker Studio", "analytics", ["free shareable web dashboards connected to live sheets and warehouse tables", "a link-shared report that refreshes itself"], None, None)
_s("dbt", "dbt", "data_eng", ["version-controlled SQL models with tests and documentation", "tidy reporting tables built by layered, tested transformations"],
   "sql", "{{ config(materialized='incremental', unique_key='order_id') }}\nSELECT order_id, customer_id, ordered_at, net_amount\nFROM {{ ref('stg_orders') }}\n{% if is_incremental() %}WHERE ordered_at > (SELECT MAX(ordered_at) FROM {{ this }}){% endif %}")
_s("snowflake", "Snowflake", "data_eng", ["a cloud warehouse with separate compute for reporting and loads", "elastic warehouse sizes switched per workload"], "sql", "CREATE WAREHOUSE IF NOT EXISTS reporting_wh WAREHOUSE_SIZE = 'XSMALL' AUTO_SUSPEND = 60;\nCOPY INTO raw.orders FROM @stage/orders/ FILE_FORMAT = (TYPE = CSV SKIP_HEADER = 1);")
_s("warehouse_modeling", "dimensional modeling", "data_eng", ["fact and dimension tables arranged for easy slicing", "a star schema the business could understand"],
   "sql", "CREATE TABLE fact_sales (\n    date_key INT, store_key INT, product_key INT, units INT, net_amount NUMERIC(12,2)\n);\nCREATE TABLE dim_store (store_key INT PRIMARY KEY, store_name TEXT, region TEXT);")
_s("customer_segmentation", "customer segmentation", "analytics", ["buyers grouped by behaviour for targeted campaigns", "clusters of customers described in plain business terms"],
   "py", "from sklearn.cluster import KMeans\nfrom sklearn.preprocessing import StandardScaler\n\ndef __FN__(rfm, k=5):\n    X = StandardScaler().fit_transform(rfm[['recency', 'frequency', 'monetary']])\n    return KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(X)")
_s("powerbi", "Power BI", "analytics", ["a governed report pack with scheduled refresh and row-level access", "a measure-driven report with budget versus actual views"], None, None)
_s("excel", "Excel", "analytics", ["advanced spreadsheet models with lookups and pivot tables", "workbooks that finance could audit"], None, None)
_s("google_sheets", "Google Sheets", "analytics", ["team spreadsheets that update themselves from live sources", "shared sheets with import formulas and protected ranges"], None, None)
_s("apps_script", "Apps Script", "analytics", ["scripted automation inside a cloud spreadsheet, including scheduled emails", "triggers that mail a weekly summary from a sheet"],
   "js", "function __FN__() {\n  const sh = SpreadsheetApp.getActive().getSheetByName('Summary');\n  const body = sh.getRange('A1:C10').getValues().map(r => r.join(' | ')).join('\\n');\n  MailApp.sendEmail('team@example.com', 'Weekly summary', body);\n}")
_s("web_scraping", "web scraping", "data_eng", ["polite scheduled collection of public pages into a table", "daily price snapshots pulled from competitor catalogues"],
   "py", "import requests\nfrom bs4 import BeautifulSoup\n\ndef __FN__(url):\n    soup = BeautifulSoup(requests.get(url, timeout=20, headers={'User-Agent': 'research-bot'}).text, 'html.parser')\n    return [(p.select_one('.name').text.strip(), p.select_one('.price').text.strip()) for p in soup.select('.product')]")
_s("survey_analysis", "survey analysis", "analytics", ["thematic coding of open-text answers and satisfaction scoring", "questionnaire results weighted and cross-tabulated"],
   "py", "def __FN__(scores):\n    p = sum(1 for s in scores if s >= 9)\n    d = sum(1 for s in scores if s <= 6)\n    return round(100 * (p - d) / len(scores), 1)")
_s("r_lang", "R", "analytics", ["scripted statistical analysis with tidy data verbs", "reproducible notebooks in the statistician's language"],
   "r", "library(dplyr)\n\n__FN__ <- function(df) {\n  df %>% group_by(segment) %>% summarise(n = n(), mean_score = mean(score, na.rm = TRUE))\n}")
_s("ggplot2", "ggplot2", "analytics", ["publication-quality statistical charts from code", "layered chart grammar for report figures"],
   "r", "library(ggplot2)\n\n__FN__ <- function(df) {\n  ggplot(df, aes(x = month, y = score, colour = segment)) + geom_line() + theme_minimal()\n}")
_s("forecasting", "forecasting", "analytics", ["next-quarter numbers with seasonality and prediction ranges", "projections that finance used in budget talks"],
   "py", "from statsmodels.tsa.holtwinters import ExponentialSmoothing\n\ndef __FN__(series, horizon=13):\n    fit = ExponentialSmoothing(series, trend='add', seasonal='add', seasonal_periods=52).fit()\n    return fit.forecast(horizon)")
_s("etl", "ETL", "data_eng", ["nightly extract, clean and load jobs between systems", "spreadsheets and exports synced into a database on a schedule"],
   "py", "import csv, sqlite3\n\ndef __FN__(path, db):\n    con = sqlite3.connect(db)\n    with open(path, newline='') as f:\n        rows = [(r['id'], r['amount'].replace(',', '')) for r in csv.DictReader(f)]\n    con.executemany('INSERT OR REPLACE INTO staging VALUES (?, ?)', rows)\n    con.commit()")
_s("regression", "regression analysis", "analytics", ["driver analysis showing which factors move an outcome", "a model explaining why, not only predicting what"],
   "py", "import statsmodels.formula.api as smf\n\ndef __FN__(df):\n    return smf.logit('left ~ tenure + salary_band + manager_changes', data=df).fit(disp=False).summary()")
_s("data_cleaning", "data cleaning", "analytics", ["deduplicated, standardised records from messy exports", "inconsistent names, dates and codes normalised"],
   "py", "import re\n\ndef __FN__(name):\n    n = re.sub(r'\\s+', ' ', name).strip().lower()\n    return re.sub(r'\\b(inc|llc|ltd)\\b\\.?', '', n).strip()")
_s("metabase", "Metabase", "analytics", ["a question-builder that non-technical staff use themselves", "an internal self-service BI portal over the database"], None, None)
_s("streamlit", "Streamlit", "analytics", ["a quick interactive web tool in plain Python for scenario what-ifs", "sliders and charts wrapped around an analysis script"],
   "py", "import streamlit as st\n\nprice = st.slider('Price change %', -20, 20, 0)\nbase = st.number_input('Baseline units', 1000)\nst.metric('Projected units', int(base * (1 - 0.012 * price)))")
_s("vba_macros", "VBA macros", "analytics", ["spreadsheet buttons that run recorded macros"], None, None)
_s("infographics", "infographics", "design", ["a hand-drawn poster of statistics"], None, None)
_s("wordcloud", "word clouds", "analytics", ["a decorative word picture from survey text"], "py", "from wordcloud import WordCloud\n\ndef __FN__(text):\n    return WordCloud(width=800, height=400).generate(text)")

# ---- Off-profile pool (jobs only; no persona has these) ---------------------------------------
_OFF = [
    ("swift", "Swift", "mobile", ["a native iPhone app with offline sync", "an App Store release built with Apple's own toolkit"]),
    ("kotlin", "Kotlin", "mobile", ["a native Android app with Jetpack Compose", "a Play Store app using Google's modern toolkit"]),
    ("flutter", "Flutter", "mobile", ["one cross-platform mobile codebase from a single Dart project", "a mobile app for both stores from shared code"]),
    ("react_native", "React Native", "mobile", ["a JavaScript-built mobile app with native modules", "a phone app sharing logic with our web code"]),
    ("unity", "Unity", "mobile", ["a small 3D mobile game with touch controls", "a game prototype built in a popular engine"]),
    ("figma", "Figma", "design", ["clickable interface mockups and a component library", "a design system delivered as shared design files"]),
    ("logo_design", "logo design", "design", ["a brand mark and colour palette", "a memorable identity with business cards"]),
    ("illustrator", "Adobe Illustrator", "design", ["vector illustrations and icon sets", "print-ready artwork"]),
    ("video_editing", "video editing", "design", ["cut and colour-graded promo videos", "short social clips from raw footage"]),
    ("seo_writing", "SEO writing", "writing", ["search-optimised blog articles of 1,500 words", "long-form posts targeting buyer keywords"]),
    ("copywriting", "copywriting", "writing", ["punchy landing page and email copy", "persuasive sales pages"]),
    ("translation", "translation", "writing", ["English to Spanish translation of product documents", "accurate localisation of an app's strings"]),
    ("ghostwriting", "ghostwriting", "writing", ["an executive's LinkedIn posts written in their voice", "a nonfiction ebook drafted from interviews"]),
    ("google_ads", "Google Ads", "marketing", ["paid search campaigns with weekly optimisation", "pay-per-click accounts managed to a target cost per lead"]),
    ("email_marketing", "email marketing", "marketing", ["newsletter flows and list segmentation", "automated drip sequences"]),
    ("social_media", "social media management", "marketing", ["daily posting and community replies on several channels", "a content calendar executed for a brand"]),
    ("lead_gen", "lead generation", "marketing", ["cold outreach lists and appointment setting", "qualified sales leads delivered monthly"]),
    ("kubernetes", "Kubernetes", "devops", ["a production cluster with autoscaling and rollouts", "container orchestration across several nodes"]),
    ("terraform", "Terraform", "devops", ["infrastructure described as reviewed code", "cloud environments created from templates"]),
    ("java_spring", "Java Spring Boot", "web", ["enterprise Java microservices", "a Spring service with JPA and security"]),
    ("dotnet", ".NET", "web", ["a C# back end on the Microsoft stack", "ASP.NET services with Entity Framework"]),
    ("php_laravel", "Laravel", "web", ["a PHP application on the Laravel framework", "an existing PHP code base to extend"]),
    ("ruby_rails", "Ruby on Rails", "web", ["a Rails monolith to maintain and upgrade", "a convention-over-configuration web app"]),
    ("golang_services", "Go", "web", ["high-throughput services written in Go", "concurrent network daemons in a compiled language"]),
    ("shopify_theme", "Shopify theme", "web", ["a custom Liquid storefront theme", "a store template tweaked for conversion"]),
    ("wordpress_plugin", "WordPress plugin", "web", ["a custom plugin for a popular CMS", "a WooCommerce extension"]),
    ("salesforce", "Salesforce", "web", ["CRM customisation with Apex and flows", "Salesforce admin automation"]),
    ("sap_abap", "SAP ABAP", "web", ["custom ERP reports in ABAP", "SAP module enhancements"]),
    ("bookkeeping", "bookkeeping", "marketing", ["monthly reconciliations and tax-ready books", "accounts payable and receivable upkeep"]),
    ("pentesting", "penetration testing", "devops", ["a security assessment and written findings", "ethical hacking of a web app"]),
    ("solidity", "Solidity", "web", ["smart contracts deployed to an EVM chain", "an NFT mint contract with an audit"]),
    ("embedded_c", "embedded C", "web", ["firmware for a microcontroller board", "low-level device drivers"]),
    ("voiceover", "voice-over", "design", ["a studio-quality narration of explainer scripts", "recorded voice talent for ads"]),
    ("cad_drafting", "CAD drafting", "design", ["technical drawings in AutoCAD", "3D parts modelled for printing"]),
]
for _i, _n, _c, _imp in _OFF:
    _s(_i, _n, _c, _imp)

OFF_PROFILE_POOL = [x[0] for x in _OFF]
DISTRACTOR_SKILLS = {"regex_bots", "openpyxl_reports", "static_site", "wordpress_theme",
                     "jquery_plugin", "static_html", "vba_macros", "infographics", "wordcloud"}
