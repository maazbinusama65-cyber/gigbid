from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Req(BaseModel):
    text: str

@app.post('/support_ticket_triage/predict')
async def route_support(req: Req):
    return {'label': 'ok', 'chars': len(req.text)}
