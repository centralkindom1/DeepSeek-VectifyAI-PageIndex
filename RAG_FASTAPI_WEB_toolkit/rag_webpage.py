# File: rag_webpage.py
import sys
import os
import json
import logging
import glob
from typing import Optional, List, Any, Dict
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

# ==============================================================================
# 1. 环境与路径配置 (Robust Path Configuration)
# ==============================================================================
# 假设代码位于 C:\FastAPIApp\app\routes，而 rag_engine 在 C:\RagSource
# 您可以根据实际部署位置修改 RAG_SOURCE_BASE
RAG_SOURCE_BASE = r"C:\RagSource"

# 尝试将 RAG 源目录加入系统路径
if RAG_SOURCE_BASE not in sys.path:
    sys.path.append(RAG_SOURCE_BASE)

# 定义结果目录 (通常存放 .db 和 .json)
RESULTS_DIR = os.path.join(RAG_SOURCE_BASE, "results")

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 动态导入引擎
try:
    from rag_engine import RAGQueryEngine
    logger.info("✅ 成功导入 rag_engine 模块")
except ImportError:
    logger.error(f"❌ 未找到 rag_engine 模块，请检查路径: {RAG_SOURCE_BASE}")
    RAGQueryEngine = None

router = APIRouter()

# ==============================================================================
# 2. 全局状态管理 (Global State)
# ==============================================================================
current_engine: Optional[Any] = None 

# 记录当前配置，用于前端回显
current_status = {
    "db_loaded": False,
    "db_name": "未加载",
    "json_name": "未加载",
    "local_model": "None"
}

# ==============================================================================
# 3. 数据模型定义 (Pydantic Models) - 对应 13 个接口需求
# ==============================================================================

# 接口 1: 初始化
class ConfigRequest(BaseModel):
    db_name: str
    json_name: str

# 接口 2: 本地模型切换
class LocalModelRequest(BaseModel):
    model_name: str  # "None", "BGE", "MiniLM"

# 接口 3: 航司字典管理
class DictRequest(BaseModel):
    operation: str   # "list", "add", "delete"
    value: Optional[str] = None

# 接口 4-9: 检索请求参数
class QueryRequest(BaseModel):
    query: str
    mode: str = "smart"                # 4. 检索参数 (smart, precise, fuzzy)
    doc_type: str = "不指定类型"         # 5. 文档类型
    model: str = "DeepSeek-R1"         # 模型名称
    limit_vector: int = 10             # 8. 返回切片数 (向量)
    limit_json: int = 10               # 8. 返回切片数 (JSON)
    enable_local: bool = False         # 6. 启用本地过滤
    enable_routing: bool = False       # 7. 启用路由建议

# ==============================================================================
# 4. 辅助函数：智能文件路径解析 (Critical Fix)
# ==============================================================================
def resolve_file_path(filename: str) -> Optional[str]:
    """
    在多个可能的目录中查找文件，解决路径加载失败问题。
    搜索顺序: RESULTS_DIR -> RAG_SOURCE_BASE -> 当前工作目录
    """
    search_paths = [
        RESULTS_DIR,
        RAG_SOURCE_BASE,
        os.getcwd(),
        os.path.join(os.getcwd(), "results")
    ]
    
    for base_path in search_paths:
        if not os.path.exists(base_path):
            continue
        full_path = os.path.join(base_path, filename)
        if os.path.isfile(full_path):
            return full_path
            
    return None

def get_engine():
    """获取全局引擎实例，未初始化则抛出异常"""
    if current_engine is None:
        raise HTTPException(status_code=400, detail="RAG引擎未初始化，请先调用 /update_config 挂载知识库。")
    return current_engine

# ==============================================================================
# 5. API 接口实现 (API Implementation)
# ==============================================================================

# --- 文件列表接口 (辅助功能) ---
@router.get("/list_files")
async def list_files():
    """扫描所有可能路径下的 .db 和 .json 文件"""
    dbs = set()
    jsons = set()
    
    # 扫描目录列表
    scan_dirs = [RESULTS_DIR, RAG_SOURCE_BASE, os.getcwd()]
    
    for d in scan_dirs:
        if os.path.exists(d):
            # 获取 .db 文件
            for f in glob.glob(os.path.join(d, "*.db")):
                dbs.add(os.path.basename(f))
            # 获取 .json 文件
            for f in glob.glob(os.path.join(d, "*.json")):
                jsons.add(os.path.basename(f))
    
    return {
        "status": "success",
        "dbs": sorted(list(dbs)),
        "jsons": sorted(list(jsons)),
        "current_status": current_status
    }

# --- 接口 1: 引擎初始化模型加载 ---
@router.post("/update_config")
async def update_config(req: ConfigRequest):
    global current_engine, current_status
    
    if RAGQueryEngine is None:
        return JSONResponse(status_code=500, content={"status": "error", "message": "rag_engine 模块加载失败"})

    # 1. 解析真实路径
    db_path = resolve_file_path(req.db_name)
    json_path = resolve_file_path(req.json_name)
    
    if not db_path:
        return JSONResponse(status_code=404, content={"status": "error", "message": f"找不到数据库文件: {req.db_name}"})
    if not json_path:
        return JSONResponse(status_code=404, content={"status": "error", "message": f"找不到索引文件: {req.json_name}"})

    try:
        logger.info(f"正在初始化引擎... DB={db_path}, JSON={json_path}")
        # 2. 实例化引擎
        current_engine = RAGQueryEngine(db_path, json_path)
        
        # 3. 更新状态
        current_status["db_loaded"] = True
        current_status["db_name"] = req.db_name
        current_status["json_name"] = req.json_name
        
        return {"status": "success", "message": "引擎初始化成功", "config": current_status}
    except Exception as e:
        logger.error(f"引擎初始化失败: {str(e)}")
        return JSONResponse(status_code=500, content={"status": "error", "message": f"初始化异常: {str(e)}"})

# --- 接口 2: Local Model 加载 ---
@router.post("/switch_local_model")
async def switch_local_model(req: LocalModelRequest):
    engine = get_engine()
    try:
        # 调用 rag_engine 的方法
        result = engine.switch_local_model(req.model_name)
        if result.get("status") == "success":
            current_status["local_model"] = req.model_name
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}

# --- 接口 3: 航司字典管理 API ---
@router.post("/manage_dict")
async def manage_dict(req: DictRequest):
    engine = get_engine()
    try:
        # 调用 rag_engine 的方法
        result = engine.manage_airline_dict(req.operation, req.value)
        # 统一返回格式
        if isinstance(result, list):
            return {"status": "success", "data": result}
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}

# --- 接口 10: 停止放弃操作 ---
@router.post("/stop_search")
async def stop_search():
    if current_engine:
        current_engine.stop()
        logger.info("已发送停止信号")
        return {"status": "success", "message": "Search stopped."}
    return {"status": "warning", "message": "Engine not running."}

# --- 接口 4-9, 11-13: 核心流式检索 ---
@router.post("/stream_ask")
async def stream_ask(req: QueryRequest):
    """
    核心流式接口，涵盖功能点：
    4. 检索参数(mode)
    5. 文档类型
    6. 本地过滤
    7. 路由建议
    8. 切片数
    9. 开始检索(Trigger)
    11. AI回答(Stream)
    12. 实时日志(Stream)
    13. 召回源(Stream)
    """
    if not current_engine:
        # 如果引擎未加载，通过SSE发送错误并关闭流
        def err_gen():
            yield f"data: {json.dumps({'type': 'error', 'data': 'Engine not initialized. Please load DB first.'}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(err_gen(), media_type="text/event-stream")

    # 构造传递给 engine.search 的参数字典
    # 必须严格对应 rag_engine.py 中 search 方法的参数名
    search_params = {
        "query": req.query,
        "search_mode": req.mode,           # smart, precise, fuzzy
        "doc_type": req.doc_type,          # 书籍, 规章...
        "model_name": req.model,
        "limit_vector": req.limit_vector,
        "limit_json": req.limit_json,
        "enable_local_filter": req.enable_local,
        "enable_routing": req.enable_routing
    }

    async def event_generator():
        try:
            # 获取 rag_engine 的生成器
            generator = current_engine.search(**search_params)
            
            for event in generator:
                # event 格式: {"type": "...", "data": ...}
                # 转换为 SSE 格式: data: {...}\n\n
                json_str = json.dumps(event, ensure_ascii=False)
                yield f"data: {json_str}\n\n"
            
            # 结束标志
            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"Stream Error: {e}")
            err_payload = {"type": "error", "data": str(e)}
            yield f"data: {json.dumps(err_payload, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# 为了方便直接运行测试，如果直接运行此文件
if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI
    
    app = FastAPI(title="RAG WebPage Backend")
    app.include_router(router, prefix="/api/rag")
    
    print(f"🚀 RAG Backend running on http://127.0.0.1:8000")
    print(f"📂 Searching files in: {RESULTS_DIR} and {RAG_SOURCE_BASE}")
    
    uvicorn.run(app, host="127.0.0.1", port=8000)