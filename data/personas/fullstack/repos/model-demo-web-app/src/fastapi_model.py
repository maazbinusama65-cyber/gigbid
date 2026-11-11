from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Req(BaseModel):
    text: str

@app.post('/model_demo_web_app/predict')
async def load_model(req: Req):
    return {'label': 'ok', 'chars': len(req.text)}
