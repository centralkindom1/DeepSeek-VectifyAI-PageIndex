# File: C:\FastAPIApp\main.py
import os
import sys
import shutil
import requests
import time
import httpx
import json
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from a2wsgi import ASGIMiddleware

# Legacy imports
import dashscope
from dashscope import Generation

# ==============================================================================
# SECTION: RAG 路径挂载 (C:\RagSource)
# ==============================================================================
RAG_SOURCE_PATH = r"C:\RagSource"
if RAG_SOURCE_PATH not in sys.path:
    sys.path.append(RAG_SOURCE_PATH)

# --- LLM 模块导入 ---
try:
    from app.llm import llmarena 
    from app.llm import llmarena2
    from app.llm import deepseek_r1
    from app.llm import deepseek_v3
    from app.llm import qwen2_5_vl_72b
except ImportError:
    print("Warning: Some LLM modules could not be imported.")

# --- 功能模块导入 ---
try:
    from app.routes import translator, notebook, weather, ip_logger
    # 导入 RAG 模块
    from app.routes import rag_webpage 
except ImportError as e:
    print(f"Error importing routes: {e}")

# --- Main FastAPI App Initialization ---
APP_DIR = os.path.dirname(os.path.abspath(__file__))

# 1. 静态文件目录
STATIC_DIR = os.path.join(APP_DIR, "static")
if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR)

# 2. RAG UI 目录
RAG_UI_DIR = os.path.join(APP_DIR, "rag")
if not os.path.exists(RAG_UI_DIR):
    os.makedirs(RAG_UI_DIR)

# 初始化应用
app = FastAPI(title="Combined App: All Services (Legacy & New)")

# 挂载目录
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/rag_ui", StaticFiles(directory=RAG_UI_DIR), name="rag_ui")

# 挂载 Flight App
try:
    from flight_app import flight_app as flight_subapp
    app.mount("/flight", flight_subapp)
except ImportError:
    pass

# ==============================================================================
# SECTION: 注册路由
# ==============================================================================
app.include_router(translator.router, prefix="/api/translator", tags=["Translator"])
app.include_router(notebook.router, prefix="/api/notebook", tags=["Notebook"])
app.include_router(weather.router, prefix="/api/weather", tags=["Weather"])
app.include_router(ip_logger.router, prefix="/api/ip", tags=["IP Logger"])
app.include_router(rag_webpage.router, prefix="/api/rag", tags=["RAG Service"])

# LLM Routers
try:
    app.include_router(deepseek_r1.router, tags=["DeepSeek R1"])
    app.include_router(deepseek_v3.router, tags=["DeepSeek V3"])
    app.include_router(qwen2_5_vl_72b.router, tags=["Qwen VL"])
    app.include_router(llmarena.router, tags=["LLM Arena"])
    app.include_router(llmarena2.router, tags=["LLM Arena 2"])
except NameError:
    pass

# ==============================================================================
# SECTION: HTML 页面路由
# ==============================================================================
@app.get("/rag_webpage", response_class=HTMLResponse)
async def get_rag_page():
    # 确保文件存在，否则返回错误提示
    path = os.path.join(RAG_UI_DIR, 'rag_webpage.html')
    if os.path.exists(path):
        return FileResponse(path)
    return HTMLResponse("<h1>Error: rag_webpage.html not found in rag folder.</h1>")

@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
async def get_main_page():
    return FileResponse('index.html')

# (其他 HTML 路由保持原样，为节省篇幅省略重复部分...)

# ==============================================================================
# SECTION: ASGI to WSGI WRAPPER FOR IIS
# ==============================================================================
wsgi_app = ASGIMiddleware(app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8090)