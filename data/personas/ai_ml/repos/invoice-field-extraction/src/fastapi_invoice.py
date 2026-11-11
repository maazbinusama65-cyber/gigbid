from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Req(BaseModel):
    text: str

@app.post('/invoice_field_extraction/predict')
async def sync_invoice(req: Req):
    return {'label': 'ok', 'chars': len(req.text)}
