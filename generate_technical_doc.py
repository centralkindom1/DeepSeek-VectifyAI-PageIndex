import os
import datetime
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH

def create_tech_doc():
    doc = Document()

    # Title
    title = doc.add_heading('DeepSeek-VectifyAI-PageIndex 技术文档', 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_paragraph(f'生成日期: {datetime.date.today()}')
    doc.add_paragraph('版本: 1.1')

    # 1. 项目概览与代码结构
    doc.add_heading('1. 项目概览与代码结构', level=1)
    doc.add_paragraph(
        'DeepSeek-VectifyAI-PageIndex 是一个基于推理的、无向量数据库、无切片的 RAG 系统。'
        '它通过将长 PDF 文档转换为语义分级的树状索引结构，模拟人类专家阅读长文档的方式进行检索。'
    )

    doc.add_heading('代码结构说明:', level=2)
    struct_text = (
        '• pageindex/: 核心逻辑包\n'
        '  - page_index.py: 树形结构解析与处理主程序\n'
        '  - page_index_md.py: Markdown 文件索引支持\n'
        '  - utils.py: 工具函数库（API 调用、JSON 处理、PDF 解析、分词计数等）\n'
        '• pgui.py: 基于 PyQt5 的图形化用户界面，支持 PageIndex 生成与 RAG 向量化\n'
        '• run_pageindex.py: 命令行运行脚本\n'
        '• run_pageindex_simple.py: 简化版脚本，跳过 TOC 检测直接处理\n'
        '• RAG_FASTAPI_WEB_toolkit/: RAG 后端与 Web 工具集\n'
        '• docs/: PRD、用户需求、部署指南等文档\n'
        '• results/: 生成的索引 JSON 文件存储目录\n'
        '• logs/: 系统日志目录'
    )
    doc.add_paragraph(struct_text)

    # 2. RAG 切片核心逻辑
    doc.add_heading('2. RAG 切片核心逻辑', level=1)
    doc.add_paragraph(
        '该项目的核心逻辑是“树状索引（Tree Index）”。与传统 RAG 将文档强制切成固定长度的“块（Chunks）”不同，'
        'PageIndex 根据文档的语义结构（如目录、标题层级）进行动态切片。'
    )
    doc.add_paragraph(
        '1. 目录提取（TOC Extraction）：首先尝试识别文档的目录页，提取原始层级关系。\n'
        '2. 递归细化（Recursive Refinement）：对于没有目录或目录过大的节点，通过 LLM 递归地将其划分为更小的子节点，'
        '直至每个节点的大小（Token 数或页数）满足预设限制。\n'
        '3. 语义对齐：使用 LLM 验证标题在页面中的实际出现位置，确保物理索引准确。'
    )

    # 3. 功能地图
    doc.add_heading('3. 功能地图', level=1)
    doc.add_paragraph(
        '• 文档解析：支持 PDF 文本提取，物理索引标记。\n'
        '• 结构化索引生成：生成带有层级关系、摘要和物理页码的 JSON 索引。\n'
        '• 向量化准备：为 RAG 系统生成增强的语义摘要（Tab B 功能）。\n'
        '• 智能召回：基于树状结构的推理召回，支持精准、模糊、智能三种模式。\n'
        '• 可视化界面：实时显示 AI 处理过程和结果输出。'
    )

    # 4. 关键算法
    doc.add_heading('4. 关键算法', level=1)
    doc.add_paragraph(
        '• TOC 检测算法：利用 LLM 识别文档前几页是否包含目录（toc_detector_single_page）。\n'
        '• 递归树构建：当单个节点超过 max_token_num_each_node 时，递归调用 LLM 生成子树（process_large_node_recursively）。\n'
        '• 物理索引偏移计算：通过比对 TOC 提到的页码与 LLM 实际找到的物理页码，计算全局页码偏移（calculate_page_offset）。\n'
        '• 语义验证：双向验证标题是否在页面开头出现（check_title_appearance_in_start）。'
    )

    # 5. 数据结构
    doc.add_heading('5. 数据结构', level=1)
    doc.add_paragraph('核心索引 JSON 格式示例如下：')
    doc.add_paragraph(
        '{\n'
        '  "title": "章节标题",\n'
        '  "node_id": "0001",\n'
        '  "start_index": 1,\n'
        '  "end_index": 5,\n'
        '  "summary": "本章节简要总结...",\n'
        '  "nodes": [ /* 子节点列表 */ ]\n'
        '}'
    )

    # 6. 函数调用图
    doc.add_heading('6. 函数调用图', level=1)
    doc.add_paragraph(
        'main (run_pageindex.py)\n'
        ' └── page_index_main (pageindex/page_index.py)\n'
        '      └── tree_parser\n'
        '           ├── check_toc (识别目录)\n'
        '           ├── meta_processor (处理顶级结构)\n'
        '           │    ├── process_toc_with_page_numbers\n'
        '           │    └── verify_toc (验证准确性)\n'
        '           └── process_large_node_recursively (递归细化超大节点)\n'
        '      ├── write_node_id\n'
        '      ├── add_node_text\n'
        '      └── generate_summaries_for_structure (生成摘要)'
    )

    # 7. 安全性分析、可扩展性与性能
    doc.add_heading('7. 安全性分析、可扩展性与性能', level=1)
    doc.add_heading('安全性分析:', level=2)
    doc.add_paragraph(
        '• API 密钥保护：支持通过 .env 文件和环境变量管理密钥，代码中避免硬编码。\n'
        '• 数据隔离：本地处理 PDF 和中间数据，仅摘要和结构信息发送至 LLM API。\n'
        '• 代理清理：自动清除环境变量中的代理设置，防止内网请求泄露。'
    )
    doc.add_heading('可扩展性:', level=2)
    doc.add_paragraph(
        '• 模块化设计：PageIndex 逻辑与 GUI/RAG 引擎解耦，易于集成到现有系统。\n'
        '• 模型适配：支持 DeepSeek, Qwen, GPT 等多种兼容 OpenAI 接口的模型。'
    )
    doc.add_heading('性能:', level=2)
    doc.add_paragraph(
        '• 并行处理：在摘要生成和验证环节使用 asyncio 并发，显著提升处理速度。\n'
        '• 内存优化：通过 Slim Version 机制，在前端显示前移除大段正文，防止 GUI 卡死。'
    )

    # 8. 总结和建议
    doc.add_heading('8. 总结和建议', level=1)
    doc.add_paragraph(
        '本项目成功实现了无需向量库的高精度 RAG 系统，特别适用于处理层级结构明显的长文档（如审计报告、技术手册）。'
        '建议后续引入更强大的多模态 OCR（如 PageIndex OCR）以处理包含复杂表格和图片的扫描件。'
    )

    # 9. 产品 MD 文档 (PRD)
    doc.add_heading('9. 产品 PRD 文档', level=1)
    doc.add_paragraph('详细内容请参考项目 docs/PRD.md。核心目标是提供比传统 RAG 更精准、更可解释的文档分析能力。')

    # 10. User Story
    doc.add_heading('10. User Stories', level=1)
    doc.add_paragraph('• 作为审计员，我希望系统能精准定位到财务报表的特定附注页，而不是仅仅返回相似的文本段落。\n'
                     '• 作为技术支持，我希望通过自然语言提问，系统能根据手册目录层级快速导航到对应的操作步骤。')

    # 11. SRS 文档
    doc.add_heading('11. SRS 文档（软件需求规范）', level=1)
    doc.add_paragraph(
        '• 输入：PDF、Markdown 文件。\n'
        '• 输出：结构化 JSON、向量数据库文件 (SQLite/FAISS)。\n'
        '• 性能要求：P95 检索延迟 < 500ms，支持百万页级别索引。'
    )

    # 12. 开发文档与本地小模型应用部署
    doc.add_heading('12. 开发与本地部署指南', level=1)
    doc.add_paragraph(
        '1. 克隆仓库并安装 requirements.txt 依赖。\n'
        '2. 配置 .env 文件中的 API_KEY。\n'
        '3. 本地模型：可结合 Ollama 或 vLLM 部署 DeepSeek/Qwen 系列模型，并将 API_BASE 指向本地端点。'
    )

    # 13. 脑图与图表 (Mermaid/Markmap)
    doc.add_heading('13. 系统图谱 (Mermaid Map)', level=1)
    doc.add_paragraph('```mermaid\n'
                     'graph TD\n'
                     '  A[PDF Document] --> B(PageIndex Engine)\n'
                     '  B --> C{TOC Detected?}\n'
                     '  C -- Yes --> D[Extract Hierarchy]\n'
                     '  C -- No --> E[Recursive Semantic Slicing]\n'
                     '  D --> F[Tree Index JSON]\n'
                     '  E --> F\n'
                     '  F --> G[RAG Knowledge Recall]\n'
                     '```')

    # 14. Requirements.txt
    doc.add_heading('14. Requirements.txt', level=1)
    doc.add_paragraph('PyQt5, openai, tiktoken, requests, urllib3, jieba, numpy, python-dotenv, PyYAML, PyPDF2, python-docx, langchain, chromadb, faiss-cpu')

    # 15. 软件使用手册
    doc.add_heading('15. 软件使用手册', level=1)
    doc.add_paragraph(
        '1. 运行 python front_pgui.py 启动主界面。\n'
        '2. 在 Page Index 标签页选择 PDF，点击 Start Indexing。\n'
        '3. 结果生成后，在 Tab B 进行向量化增强。\n'
        '4. 使用 RAG_Frontend.py 进行对话式检索。'
    )

    # Save
    save_path = 'DeepSeek-VectifyAI-PageIndex_Technical_Documentation.docx'
    doc.save(save_path)
    print(f'Document saved to {save_path}')

if __name__ == '__main__':
    create_tech_doc()
