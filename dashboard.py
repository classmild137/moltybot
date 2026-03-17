from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from core.monitor import Monitor
import uvicorn
import os

app = FastAPI()
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})

@app.get("/api/stats")
async def get_stats():
    return JSONResponse(Monitor.get_all())

def run_dashboard(host="0.0.0.0", port=5000):
    uvicorn.run(app, host=host, port=port, log_level="warning")

if __name__ == "__main__":
    run_dashboard()
