from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Req(BaseModel):
    text: str

@app.post('/payment_fraud_scoring/predict')
async def check_payment(req: Req):
    return {'label': 'ok', 'chars': len(req.text)}
