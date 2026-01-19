# RAG Code Buddy DEV0 API 文档

## 概述

本文档描述了RAG Code Buddy DEV0系统中涉及的所有API接口，包括第三方模型API和内部接口。

## 第三方API

### 1. Qwen API

#### 用途
- 语义分析
- 内容总结
- 回答生成

#### 配置
```env
QWEN_API_KEY=your_api_key
QWEN_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus
```

#### 调用示例
```python
headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

data = {
    "model": "qwen-plus",
    "messages": [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Your query here"}
    ],
    "max_tokens": 1000,
    "temperature": 0.1
}
```

### 2. BGE Embedding API

#### 用途
- 文本向量化
- 语义嵌入

#### 配置
```env
BGE_API_KEY=your_api_key
BGE_API_BASE=https://api.siliconflow.cn/v1
BGE_MODEL=BAAI/bge-m3
```

#### 接口详情
- **Endpoint**: `/v1/embeddings`
- **Method**: POST
- **Headers**:
  - `Content-Type: application/json`
  - `Authorization: Bearer {API_KEY}`

#### 请求格式
```json
{
  "model": "BAAI/bge-m3",
  "input": ["text to embed"],
  "encoding_format": "float"
}
```

#### 响应格式
```json
{
  "data": [
    {
      "embedding": [0.1, 0.2, 0.3, ...],
      "index": 0
    }
  ]
}
```

### 3. BGE Rerank API

#### 用途
- 检索结果重排序
- 相关性优化

#### 配置
```env
BGE_RERANK_API_KEY=your_api_key
BGE_RERANK_API_BASE=https://api.siliconflow.cn/v1
BGE_RERANK_MODEL=BAAI/bge-reranker-v2-m3
```

#### 接口详情
- **Endpoint**: `/v1/rerank`
- **Method**: POST
- **Headers**:
  - `Content-Type: application/json`
  - `Authorization: Bearer {API_KEY}`

#### 请求格式
```json
{
  "model": "BAAI/bge-reranker-v2-m3",
  "query": "search query",
  "documents": ["doc1", "doc2", "doc3"],
  "top_n": 3
}
```

#### 响应格式
```json
{
  "results": [
    {
      "index": 0,
      "relevance_score": 0.95
    },
    {
      "index": 2,
      "relevance_score": 0.87
    }
  ]
}
```

## 内部API接口

### 1. 命令行接口

#### PageIndex 生成
```bash
python run_pageindex_simple.py --pdf_path "path/to/pdf" --model "qwen-plus"
```

#### 向量化处理 (TAB B)
```bash
python backend_pgui.py --input "input.json" --output "output.json" --model "qwen-plus" --strategy 0
```

#### 规则转换 (TAB C)
```bash
python json_phase2_converter.py "input.json" "output.json"
```

#### BGE向量化
```bash
python bge_gui.py
```

### 2. 进度报告接口

#### 格式
```json
{
  "phase": "Converting",
  "current": 5,
  "total": 10
}
```

#### 使用场景
- 后台处理进度
- GUI更新
- 用户反馈

### 3. 日志格式接口

#### 标准格式
```
[LEVEL] Message content
```

#### 级别定义
- `[INFO]`: 一般信息
- `[SUCCESS]`: 成功完成
- `[ERROR]`: 错误发生
- `[WARN]`: 警告信息

## 数据接口

### 1. 输入格式 (PageIndex JSON)

```json
{
  "doc_name": "document_name.pdf",
  "doc_description": "Description of the document",
  "structure": [
    {
      "title": "Section Title",
      "start_index": 1,
      "end_index": 1,
      "nodes": [],
      "node_id": "0000",
      "text": "Section content...",
      "summary": "Section summary..."
    }
  ]
}
```

### 2. 输出格式 (RAG-ready JSON)

```json
{
  "embedding_text": "Semantic introduction with original content",
  "section_hint": "Type of content",
  "metadata": {
    "doc_title": "Document title",
    "section_id": "Unique identifier",
    "section_path": ["path", "to", "section"],
    "depth": 1,
    "original_length": 100,
    "strategy": 0
  },
  "original_snippet": "Original content snippet"
}
```

### 3. 数据库结构 (SQLite)

#### vectors 表
```sql
CREATE TABLE vectors (
    id TEXT PRIMARY KEY,
    embedding TEXT,
    dim INTEGER,
    doc_title TEXT,
    section_id TEXT
);
```

#### documents 表
```sql
CREATE TABLE documents (
    id TEXT PRIMARY KEY,
    embedding_text TEXT,
    section_hint TEXT,
    original_snippet TEXT,
    section_path TEXT,
    depth INTEGER,
    original_length INTEGER
);
```

## 错误处理

### 通用错误码
- `401`: API密钥无效
- `429`: 请求频率限制
- `500`: 服务器内部错误
- `503`: 服务不可用

### 重试策略
- 指数退避算法
- 最大重试次数: 3
- 初始延迟: 1秒

## 安全考虑

### API密钥管理
- 环境变量存储
- 不在代码中硬编码
- 定期轮换

### 数据隐私
- 本地处理选项
- 数据脱敏
- 审计日志

## 性能指标

### API调用限制
- Qwen: 根据API提供商限制
- BGE: 无明确限制
- BGE Rerank: 根据API提供商限制

### 响应时间
- Qwen: <5秒 (平均)
- BGE Embedding: <2秒 (平均)
- BGE Rerank: <1秒 (平均)

## 故障排除

### 常见问题
1. **API密钥无效**: 检查`.env`文件配置
2. **网络连接错误**: 检查网络连接
3. **响应格式错误**: 检查请求格式

### 调试方法
- 启用详细日志
- 检查API端点可达性
- 验证请求格式

---

**文档版本**: 1.0  
**更新日期**: 2026-01-18  
**API版本**: v1