from fastapi import FastAPI
from app.routes import router

app = FastAPI(title="Rapinet Pay", version="1.0")
app.include_router(router)
