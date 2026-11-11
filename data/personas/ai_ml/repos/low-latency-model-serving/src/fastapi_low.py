from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Req(BaseModel):
    text: str

@app.post('/low_latency_model_serving/predict')
async def score_low(req: Req):
    return {'label': 'ok', 'chars': len(req.text)}
