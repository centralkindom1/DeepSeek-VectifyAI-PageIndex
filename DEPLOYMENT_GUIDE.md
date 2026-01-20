# RAG系统本地部署指南

## 📋 部署清单

- [x] Python 3.9+ 已安装
- [x] 依赖包已安装
- [x] API配置文件已创建 (`.env`)
- [ ] API密钥验证
- [ ] PDF解析测试
- [ ] 完整工作流测试

## 🔧 步骤1: 安装Python依赖

所有核心依赖已安装完成:

```bash
pip install PyQt5 openai tiktoken requests urllib3 jieba numpy python-dotenv PyYAML PyPDF2
```

## 📝 步骤2: 配置API密钥

已创建 `.env` 配置文件,需要验证以下API密钥:

### API密钥列表

| API服务 | 配置项 | 当前密钥 | 状态 |
|---------|--------|---------|------|
| **Qwen LLM** | `QWEN_API_KEY` | sk-f3b2...d028 | ✅ |
| **BGE Embedding** | `BGE_API_KEY` | sk-8a84...dc555 | ⚠️ 需验证 |
| **BGE Reranker** | `BGE_RERANK_API_KEY` | sk-56d6...757f | ⚠️ 需验证 |

### API端点配置

```bash
# Qwen (阿里云DashScope)
QWEN_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus

# BGE Embedding (SiliconFlow)
BGE_API_BASE=https://api.siliconflow.cn/v1
BGE_MODEL=BAAI/bge-m3

# BGE Reranker (SiliconFlow)
BGE_RERANK_API_BASE=https://api.siliconflow.cn/v1
BGE_RERANK_MODEL=BAAI/bge-reranker-v2-m3
```

### 验证API密钥

运行测试脚本:

```bash
python test_api_config.py
```

**预期输出:**
```
✅ Qwen LLM : 通过
✅ BGE Embedding : 通过
✅ BGE Rerank : 通过
```

如果API密钥无效,需要更新 `.env` 文件中的密钥。

## 🚀 步骤3: 运行系统

### 启动主界面

```bash
python front_pgui.py
```

### 启动知识召回窗口

```bash
python pgirecallwindow.py
```

### 启动RAG前端

```bash
python RAG_Frontend.py
```

## 📚 步骤4: RAG工作流

### 完整工作流程

```
1. PDF解析 → front_pgui.py (Tab A: PageIndex)
   ├─ 选择PDF文件
   ├─ 选择AI模型 (Qwen/DeepSeek)
   ├─ 选择策略模式 (IATA Hybrid推荐)
   └─ 点击 "START INDEXING"
   ↓ 输出: {pdf_name}.json

2. 向量化准备 → front_pgui.py (Tab B: RAG Vectorization)
   ├─ 选择步骤1的JSON文件
   ├─ 选择向量化策略 (Lossless推荐)
   ├─ 选择LLM模型
   └─ 点击 "GENERATE VECTOR JSON"
   ↓ 输出: RAGjson_{pdf_name}.json

3. BGE向量化 → bge_gui.py
   ├─ 选择步骤2的Vector JSON
   ├─ 点击 "开始发送 BGE 向量化"
   └─ 等待批处理完成
   ↓ 输出: {json_name}_embedded.json + {json_name}_rag.db

4. RAG召回查询 → RAG_Frontend.py 或 pgirecallwindow.py
   ├─ 选择向量数据库 (.db文件)
   ├─ 选择PageIndex JSON文件
   ├─ 输入查询问题
   ├─ 选择召回模式 (Smart/Precise/Fuzzy)
   └─ 点击 "开始召回"
   ↓ 输出: 召回结果 + AI生成的答案
```

## ⚠️ 常见问题

### 问题1: PDF解析警告

```
Cannot set gray non-stroke color because /'P0' is an invalid float value
```

**说明:** 这是pdfplumber的警告,不影响文本提取功能,可以忽略。

### 问题2: API连接失败 (404/401)

**原因:**
- 404: 模型名称不正确
- 401: API密钥无效或过期

**解决方法:**
1. 检查 `.env` 文件中的API密钥
2. 确认模型名称是否正确
3. 运行 `python test_api_config.py` 验证

### 问题3: BGE API密钥无效

**原因:** SiliconFlow密钥可能已过期或未激活

**解决方法:**
1. 访问 https://siliconflow.cn 获取新密钥
2. 或使用其他兼容的Embedding服务 (如Jina AI, OpenAI等)

### 问题4: Pydantic错误

**原因:** pip包安装不完整

**解决方法:**
```bash
pip install --force-reinstall pydantic
```

## 📊 性能优化建议

### 1. PDF解析优化
- 使用IATA Hybrid模式 (并发+跳过短文本)
- 调整并发线程数 (推荐2-4线程)

### 2. 向量化优化
- 批处理大小: 保持8条/批
- 选择合适的向量化策略:
  - 表格/时刻表: Lossless模式
  - 公文/政策: Semantic模式
  - 通用文档: Mixed模式

### 3. 召回优化
- 智能模式 (Smart): 自动路由
- 精准模式 (Precise): 适合航班号/代码查询
- 模糊模式 (Fuzzy): 适合语义查询

## 🔍 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                  PDF 文档输入                          │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│         Step 1: PageIndex解析                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │ pdfplumber  │  │  文本提取   │  │  结构化     │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  │
│                        │                               │
│                        ▼                               │
│              Qwen API (摘要生成)                        │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│         Step 2: 向量化准备                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │ 语义导语生成 │  │  内容重组   │  │ 元数据提取  │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  │
│                        │                               │
│                        ▼                               │
│              Qwen API (内容分析)                        │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│         Step 3: BGE向量化                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │ 批处理请求   │  │BGE Embedding│  │ SQLite存储  │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  │
│                        │                               │
│                        ▼                               │
│            BGE API (向量生成)                          │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│         Step 4: RAG召回                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │ 查询重写     │  │双通道召回   │  │ RRF融合     │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  │
│                        │                               │
│     ┌──────────────────┴──────────────────┐             │
│     ▼                                  ▼             │
│  向量通道                          JSON关键词通道       │
│  (BGE Embedding + Reranker)        (Jieba分词)         │
│                        │                               │
│                        ▼                               │
│              Qwen API (答案生成)                        │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
              最终答案输出
```

## 📞 技术支持

如遇到问题,请检查:
1. Python版本: 需要3.9+
2. 依赖包: 运行 `pip list` 确认
3. API密钥: 运行 `python test_api_config.py`
4. 日志文件: 查看 `logs/` 目录

## ✅ 部署完成检查清单

- [ ] Python环境配置完成
- [ ] 所有依赖包安装成功
- [ ] `.env` 文件配置正确
- [ ] API测试全部通过
- [ ] 能够成功解析PDF文件
- [ ] 能够完成完整RAG工作流
- [ ] 能够查询并获得答案

---

**部署日期:** 2025-01-18
**版本:** v1.0
**系统:** Windows / Python 3.9+
