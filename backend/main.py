from fastapi import FastAPI
import os

app = FastAPI()

@app.get("/")
def root():
    return {
        "service": "nischint-backend",
        "status": "running",
        "run_mode": os.getenv("RUN_MODE", "api")
    }

@app.get("/health")
def health():
    return {"status": "healthy"}
