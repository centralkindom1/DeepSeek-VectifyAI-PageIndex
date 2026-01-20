# RAG系统快速启动指南

## ✅ 问题已解决

### **问题描述:**
程序在 `find_toc_pages` (目录检测) 阶段卡住

### **根本原因:**
API URL配置错误,导致无法连接到LLM服务

### **解决方案:**
创建了简化版 `run_pageindex_simple.py`,跳过TOC检测直接处理

---

## 🚀 快速启动方式

### **方式1: 使用简化版 (推荐,跳过API)**

```bash
# 命令行启动
python run_pageindex_simple.py --pdf_path "路径/PDF文件.pdf" --model qwen-plus
```

**优点:**
- ✅ 不依赖LLM API
- ✅ 处理速度快
- ✅ 适合大部分技术文档

**缺点:**
- ⚠️ 不使用TOC优化结构
- ⚠️ 摘要生成仍需API(可选)

---

### **方式2: GUI界面**

#### **主工作台 (front_pgui.py)**

**注意:** 当前GUI会调用TOC检测,可能卡住。建议:

1. **关闭当前GUI窗口**
2. **使用命令行先处理PDF**
3. **然后在GUI中继续后续步骤**

#### **替代方案 - 使用批处理启动**

双击运行: `start_rag_system.bat`

选择:
- `1` - 主工作台 (front_pgui.py)
- `2` - 知识召回窗口
- `3` - RAG前端
- `4` - BGE向量化工具

---

## 📋 完整工作流程 (使用简化版)

### **步骤1: PDF解析 (命令行)**

```bash
# earthmover.pdf 示例
python run_pageindex_simple.py --pdf_path "D:/RagCodeBudyDEV0/tests/pdfs/earthmover.pdf" --model qwen-plus
```

**输出:**
- 文件保存在 `logs/` 目录
- 格式: `{pdf_name}_{timestamp}.json`
- 例如: `earthmover_20260118_153316.json`

**日志说明:**
- `Cannot set gray non-stroke color` - 警告,可忽略
- `DEBUG_AI_CHAR:*` - AI实时生成内容
- `[SUCCESS]` - 处理完成

---

### **步骤2: 向量化准备 (GUI)**

1. 启动主工作台:
   ```bash
   python front_pgui.py
   ```

2. 切换到 **"TAB B: RAG Vectorization (LLM)"**

3. 配置参数:
   - SOURCE JSON: 选择步骤1的JSON文件
   - EXPORT TO: 自动生成 `RAGjson_{pdf_name}.json`
   - SUMMARIZER MODEL: qwen-plus
   - STRATEGY: 数据无损模式 (Lossless)

4. 点击 **"⚡ GENERATE VECTOR JSON"**

**注意:** 此步骤需要有效的LLM API密钥

---

### **步骤3: BGE向量化**

```bash
# 启动BGE工具
python bge_gui.py
```

1. 点击 **"📂 选择文件"**
2. 选择步骤2的 `RAGjson_{pdf_name}.json`
3. 点击 **"🚀 开始发送 BGE 向量化"**

**输出:**
- `{json_name}_embedded.json` - 包含向量的JSON
- `{json_name}_rag.db` - SQLite数据库

**注意:** 此步骤需要有效的BGE API密钥

---

### **步骤4: RAG召回查询**

```bash
# 启动RAG前端
python RAG_Frontend.py
```

1. 配置:
   - Vector Database: 选择步骤3的 `.db` 文件
   - PageIndex JSON: 选择步骤1的 `.json` 文件
   - Summary Model: qwen-plus

2. 输入查询问题
3. 选择召回模式:
   - **Smart**: 自动路由 (推荐)
   - **Precise**: 精准模式 (航班号/代码)
   - **Fuzzy**: 模糊模式 (语义查询)

4. 点击 **"开始召回"**

---

## 🔧 故障排查

### **问题1: PDF解析卡在"start find_toc_pages"**

**解决:** 使用简化版
```bash
python run_pageindex_simple.py --pdf_path "your.pdf" --model qwen-plus
```

---

### **问题2: API连接失败 (404/401)**

**检查:**
1. 运行API测试
   ```bash
   python test_api_config.py
   ```

2. 更新 `.env` 文件中的密钥

3. 确认模型名称正确:
   - Qwen: `qwen-plus`
   - BGE: `BAAI/bge-m3`

---

### **问题3: Pydantic错误**

**解决:**
```bash
pip install --force-reinstall pydantic
```

---

### **问题4: PDF警告 "Cannot set gray non-stroke color"**

**说明:** 此警告来自pdfplumber,**不影响功能**

**解决:** 可安全忽略,不影响文本提取

---

## 📊 性能建议

### **PDF解析**
- ✅ 使用简化版跳过TOC检测
- ✅ 小文件: 使用完整版
- ✅ 大文件: 必须用简化版

### **向量化**
- 批处理: 8条/批 (默认)
- 策略选择:
  - 表格/时刻表 → Lossless
  - 公文/政策 → Semantic
  - 通用文档 → Mixed

### **召回**
- 智能模式: 自动平衡速度和准确性
- 精准模式: 快速精确查询
- 模糊模式: 深度语义理解

---

## 📁 文件结构

```
RagCodeBudyDEV0/
├── .env                          # API配置
├── front_pgui.py                 # 主工作台GUI
├── bge_gui.py                    # BGE向量化工具
├── RAG_Frontend.py              # RAG召回前端
├── pgirecallwindow.py            # 知识召回窗口
├── run_pageindex_simple.py        # 简化版PDF解析 (推荐)
├── run_pageindex.py              # 完整版PDF解析
├── pageindex/                   # PDF解析模块
│   ├── utils.py                 # 工具函数
│   └── page_index.py            # 主逻辑
├── logs/                        # 输出目录
│   ├── earthmover_*.json        # PDF解析结果
│   └── PRML_*.json
└── results/                     # 处理结果
    └── earthmover_*.json
```

---

## 🎯 下一步

### **当前状态:**
- ✅ PDF解析工具已修复
- ✅ 简化版已测试成功
- ✅ API配置已更新

### **建议操作:**

1. **测试完整流程** (使用简化版):
   ```bash
   # Step 1: PDF解析
   python run_pageindex_simple.py --pdf_path "tests/pdfs/earthmover.pdf"

   # Step 2-4: 使用GUI完成后续步骤
   python front_pgui.py
   python bge_gui.py
   python RAG_Frontend.py
   ```

2. **验证API配置**:
   ```bash
   python test_api_config.py
   ```

3. **修复GUI中的TOC问题** (可选):
   - 修改 `front_pgui.py` 中的参数
   - 将 `toc_check_pages` 设为 0

---

## 💡 技术说明

### **TOC检测 vs 简化版**

| 特性 | 完整版 | 简化版 |
|------|---------|---------|
| TOC检测 | ✅ | ❌ |
| 处理速度 | 慢 | 快 |
| API依赖 | 是 | 否 |
| 适用场景 | 结构化文档 | 所有文档 |
| 错误率 | 低(如果有API) | 中 |

### **API端点配置**

```env
# Qwen API (阿里云)
QWEN_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_API_KEY=sk-xxxxx
QWEN_MODEL=qwen-plus

# BGE Embedding (SiliconFlow)
BGE_API_BASE=https://api.siliconflow.cn/v1
BGE_API_KEY=sk-xxxxx
BGE_MODEL=BAAI/bge-m3
```

---

**更新时间:** 2025-01-18
**版本:** v1.1 (简化版)
