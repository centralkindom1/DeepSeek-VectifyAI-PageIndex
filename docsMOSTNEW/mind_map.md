# RAG Code Buddy 思维导图

## 核心概念

```
RAG Code Buddy DEV0
├── 项目概述
│   ├── 智能文档理解系统
│   ├── 航空公司波音飞机手册
│   └── 检索增强生成(RAG)
├── 三大处理管道
│   ├── TAB A: PDF解析与PageIndex构建
│   │   ├── PDF文档输入
│   │   ├── 结构化内容提取
│   │   ├── 章节识别
│   │   └── JSON输出
│   ├── TAB B: LLM驱动向量化
│   │   ├── PageIndex JSON输入
│   │   ├── 语义分析
│   │   ├── 元数据提取
│   │   └── RAG-ready JSON输出
│   └── TAB C: 规则基础转换
│       ├── PageIndex JSON输入
│       ├── 规则转换算法
│       ├── 高速处理
│       └── RAG-ready JSON输出
├── 核心技术栈
│   ├── Python 3.9+
│   ├── PyQt5 (GUI)
│   ├── Qwen API
│   ├── BGE嵌入模型
│   ├── SQLite数据库
│   └── LangChain框架
├── 功能模块
│   ├── 前端GUI (front_pgui.py)
│   │   ├── 三标签页界面
│   │   ├── 进度监控
│   │   ├── 日志输出
│   │   └── 可视化窗口
│   ├── 后端处理 (backend_pgui.py)
│   │   ├── 递归树遍历
│   │   ├── LLM调用
│   │   ├── 语义导语生成
│   │   └── JSON格式化
│   ├── 规则转换器 (json_phase2_converter.py)
│   │   ├── 树状转扁平
│   │   ├── 语义导语生成
│   │   ├── 元数据提取
│   │   └── 格式标准化
│   └── BGE客户端 (bge_gui.py)
│       ├── 向量化处理
│       ├── 重排序功能
│       ├── 数据库管理
│       └── 批处理支持
├── 数据流程
│   ├── 输入层
│   │   ├── PDF文档
│   │   └── JSON文件
│   ├── 处理层
│   │   ├── PageIndex构建
│   │   ├── 语义增强
│   │   ├── 规则转换
│   │   └── 向量化
│   ├── 存储层
│   │   ├── SQLite数据库
│   │   ├── JSON文件
│   │   └── 索引文件
│   └── 输出层
│       ├── 检索结果
│       ├── 答案生成
│       └── 可视化展示
├── 智能检索引擎
│   ├── 向量检索
│   │   ├── BGE嵌入模型
│   │   ├── 余弦相似度
│   │   └── 相似度排序
│   ├── 传统检索
│   │   ├── 关键词匹配
│   │   ├── 内容搜索
│   │   └── 章节定位
│   ├── 重排序
│   │   ├── BGE重排序模型
│   │   ├── 相关性优化
│   │   └── 结果精炼
│   └── 融合算法
│       ├── RRF互反排名融合
│       ├── 多通道结果合并
│       └── 权重平衡
├── 用户体验
│   ├── 界面设计
│   │   ├── 直观易用
│   │   ├── 进度可视化
│   │   ├── 实时反馈
│   │   └── 错误提示
│   ├── 性能表现
│   │   ├── 快速响应
│   │   ├── 高吞吐量
│   │   ├── 稳定可靠
│   │   └── 资源优化
│   └── 可访问性
│       ├── 多平台支持
│       ├── 无障碍设计
│       ├── 国际化
│       └── 个性化配置
├── 安全与合规
│   ├── 数据安全
│   │   ├── 本地处理
│   │   ├── 加密传输
│   │   ├── 访问控制
│   │   └── 审计日志
│   ├── API安全
│   │   ├── 密钥管理
│   │   ├── 认证授权
│   │   ├── 速率限制
│   │   └── 监控告警
│   └── 隐私保护
│       ├── 数据最小化
│       ├── 用户同意
│       ├── 数据保留
│       └── 匿名化处理
└── 扩展与维护
    ├── 架构设计
    │   ├── 模块化
    │   ├── 插件化
    │   ├── 微服务
    │   └── API优先
    ├── 性能优化
    │   ├── 缓存策略
    │   ├── 并发处理
    │   ├── 批处理
    │   └── 资源管理
    ├── 监控运维
    │   ├── 性能监控
    │   ├── 错误追踪
    │   ├── 日志分析
    │   └── 自动化测试
    └── 版本管理
        ├── 持续集成
        ├── 发布管理
        ├── 回滚机制
        └── 版本兼容
```

## 系统架构思维导图

```
RAG系统架构
├── 展示层
│   ├── GUI界面
│   │   ├── TAB A: PDF解析
│   │   ├── TAB B: 向量化
│   │   └── TAB C: 规则转换
│   ├── 进度监控
│   ├── 日志输出
│   └── 可视化组件
├── 业务逻辑层
│   ├── 文档解析模块
│   │   ├── PDF解析器
│   │   ├── 结构提取器
│   │   └── JSON生成器
│   ├── 处理模块
│   │   ├── LLM处理器
│   │   ├── 规则转换器
│   │   └── 向量化器
│   ├── 检索引擎
│   │   ├── 向量检索器
│   │   ├── 传统检索器
│   │   ├── 重排序器
│   │   └── 融合算法
│   └── 答案生成器
│       ├── 内容聚合器
│       ├── 上下文构建器
│       └── 回答合成器
├── 数据访问层
│   ├── 文件系统
│   │   ├── 输入文件读取
│   │   ├── 输出文件写入
│   │   └── 临时文件管理
│   ├── 数据库
│   │   ├── SQLite存储
│   │   ├── 向量表
│   │   └── 文档表
│   └── 缓存
│       ├── 结果缓存
│       ├── 向量缓存
│       └── 查询缓存
└── 外部服务层
    ├── AI模型API
    │   ├── Qwen API
    │   ├── BGE Embedding API
    │   └── BGE Rerank API
    ├── 第三方服务
    │   ├── 认证服务
    │   ├── 监控服务
    │   └── 通知服务
    └── 系统资源
        ├── CPU/GPU
        ├── 内存
        └── 网络
```

## 功能流程思维导图

```
用户操作流程
├── 准备阶段
│   ├── 环境配置
│   │   ├── 安装依赖
│   │   ├── API密钥配置
│   │   └── 系统初始化
│   ├── 文件准备
│   │   ├── 选择PDF文档
│   │   ├── 验证文件格式
│   │   └── 检查文件大小
│   └── 参数设置
│       ├── 选择处理模型
│       ├── 设置处理策略
│       └── 配置输出路径
├── 处理阶段
│   ├── TAB A: PDF解析
│   │   ├── 文档加载
│   │   ├── 结构分析
│   │   ├── 内容提取
│   │   └── JSON生成
│   ├── TAB B: LLM向量化
│   │   ├── JSON读取
│   │   ├── 语义分析
│   │   ├── 元数据增强
│   │   └── 向量准备
│   └── TAB C: 规则转换
│       ├── JSON读取
│       ├── 规则应用
│       ├── 结构转换
│       └── 格式标准化
├── 后处理阶段
│   ├── 向量化处理
│   │   ├── 文本嵌入
│   │   ├── 向量存储
│   │   └── 索引构建
│   ├── 数据库操作
│   │   ├── 创建表结构
│   │   ├── 插入向量数据
│   │   └── 优化索引
│   └── 结果验证
│       ├── 数据完整性检查
│       ├── 格式验证
│       └── 性能评估
└── 查询阶段
    ├── 问题输入
    │   ├── 用户查询
    │   ├── 语义解析
    │   └── 查询优化
    ├── 检索执行
    │   ├── 向量生成
    │   ├── 相似度计算
    │   ├── 结果排序
    │   └── 重排序
    ├── 结果处理
    │   ├── 多通道融合
    │   ├── 内容去重
    │   └── 相关性排序
    └── 答案生成
        ├── 内容聚合
        ├── 上下文构建
        └── 最终回答
```

## 技术组件思维导图

```
核心技术组件
├── 前端组件 (PyQt5)
│   ├── MainWindow
│   │   ├── TabWidget
│   │   │   ├── PageIndexTab
│   │   │   ├── VectorTab
│   │   │   └── ConverterTab
│   │   ├── MenuBar
│   │   ├── ToolBar
│   │   └── StatusBar
│   ├── WorkerThreads
│   │   ├── PageIndexWorker
│   │   ├── VectorWorker
│   │   └── ConverterWorker
│   └── UIComponents
│       ├── FileSelector
│       ├── ProgressBar
│       ├── LogViewer
│       └── ConfigPanel
├── 后端组件 (Python)
│   ├── PageIndexModule
│   │   ├── PDFParser
│   │   ├── StructureExtractor
│   │   └── JSONGenerator
│   ├── VectorModule
│   │   ├── TextEmbedder
│   │   ├── SemanticAnalyzer
│   │   └── MetadataExtractor
│   ├── ConverterModule
│   │   ├── TreeWalker
│   │   ├── RuleEngine
│   │   └── FormatConverter
│   └── RAGModule
│       ├── VectorDB
│       ├── Retriever
│       ├── Reranker
│       └── AnswerGenerator
├── AI模型组件
│   ├── QwenIntegration
│   │   ├── ChatCompletion
│   │   ├── SemanticAnalysis
│   │   └── ContentGeneration
│   ├── BGEIntegration
│   │   ├── EmbeddingModel
│   │   ├── SimilarityCalc
│   │   └── RerankModel
│   └── ModelAbstraction
│       ├── ModelInterface
│       ├── ResponseParser
│       └── ErrorHandler
└── 数据存储组件
    ├── SQLiteIntegration
    │   ├── ConnectionManager
    │   ├── TableCreator
    │   └── QueryExecutor
    ├── JSONHandlers
    │   ├── FileReader
    │   ├── FileWriter
    │   └── Validator
    └── CacheLayer
        ├── ResultCache
        ├── VectorCache
        └── QueryCache
```

---

**思维导图版本**: 1.0  
**创建日期**: 2026-01-18  
**作者**: RAG Code Buddy Architecture Team