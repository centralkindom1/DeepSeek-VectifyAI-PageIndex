# RAG Code Buddy Mermaid 图表文档

## 系统架构图

```mermaid
graph TB
    subgraph "用户界面层"
        A[front_pgui.py]
        A1[TAB A: PDF解析]
        A2[TAB B: 向量化]
        A3[TAB C: 规则转换]
    end

    subgraph "处理层"
        B[backend_pgui.py]
        C[bge_gui.py]
        D[json_phase2_converter.py]
    end

    subgraph "核心模块"
        E[pageindex/模块]
        F[QwenAPIutilspy/]
        G[utils.py]
    end

    subgraph "数据存储"
        H[(SQLite数据库)]
        I[JSON文件]
    end

    A1 --> E
    A2 --> B
    A3 --> D
    E --> B
    D --> B
    B --> C
    C --> H
    E --> I
    B --> I
    D --> I

    A -.-> A1
    A -.-> A2
    A -.-> A3
```

## 数据流程图

```mermaid
sequenceDiagram
    participant User as 用户
    participant GUI as GUI界面
    participant Parser as PDF解析器
    participant Processor as 处理器
    participant Vectorizer as 向量化器
    participant DB as 数据库
    participant RAG as RAG引擎
    participant Answer as 答案生成器

    User->>GUI: 上传PDF文档
    GUI->>Parser: 解析PDF
    Parser-->>GUI: 返回PageIndex JSON
    alt LLM处理模式
        GUI->>Processor: 启动LLM处理
        Processor->>F: 调用Qwen API
        F-->>Processor: 返回语义增强结果
        Processor-->>GUI: 返回RAG-ready JSON
    else 规则转换模式
        GUI->>D: 启动规则转换
        D-->>GUI: 返回RAG-ready JSON
    end
    GUI->>Vectorizer: 启动向量化
    Vectorizer->>C: 调用BGE API
    C-->>Vectorizer: 返回向量数据
    Vectorizer->>DB: 存储向量数据
    User->>RAG: 输入查询问题
    RAG->>DB: 检索相关文档
    DB-->>RAG: 返回相关片段
    RAG->>Answer: 生成答案
    Answer-->>User: 返回最终答案
```

## 组件依赖图

```mermaid
graph LR
    subgraph "前端组件"
        A[front_pgui.py]
        A1[TabPageIndex]
        A2[TabVectorize]
        A3[TabConvert]
    end

    subgraph "后端组件"
        B[backend_pgui.py]
        C[bge_gui.py]
        D[json_phase2_converter.py]
    end

    subgraph "核心库"
        E[pageindex/]
        F[QwenAPIutilspy/]
        G[utils.py]
    end

    A --- A1
    A --- A2
    A --- A3
    A1 --- E
    A2 --- B
    A3 --- D
    B --- F
    C --- F
    D --- G
    B --- C
    E --- G
```

## 处理管道图

```mermaid
flowchart LR
    Start([PDF文档]) --> A[PageIndex解析]
    A --> B{选择处理管道}
    
    B -->|TAB B: LLM| C[LLM语义增强]
    B -->|TAB C: 规则| D[规则基础转换]
    
    C --> E[向量化处理]
    D --> E
    E --> F[(SQLite数据库)]
    F --> G[RAG检索]
    G --> H[答案生成]
    H --> End([最终答案])

    C -.-> I[API调用<br/>Qwen/BGE])
    D -.-> J[本地规则<br/>无API依赖]
    E -.-> K[BGE向量化<br/>API调用]
    
    style A fill:#e1f5fe
    style C fill:#f3e5f5
    style D fill:#e8f5e8
    style F fill:#fff3e0
    style H fill:#fce4ec
```

## 类结构图

```mermaid
classDiagram
    class MainWindow {
        +str current_tab
        +dict tabs
        +setup_ui()
        +switch_tab()
        +show_visual_window()
    }
    
    class WorkerThread {
        +str input_path
        +str output_path
        +run()
    }
    
    class PageIndexWorker {
        +str pdf_path
        +str model
        +int max_workers
        +run()
    }
    
    class VectorWorker {
        +str json_path
        +str db_path
        +str model
        +run()
    }
    
    class ConverterWorker {
        +str input_path
        +str output_path
        +run()
    }
    
    class BGERetriever {
        +str api_key
        +str base_url
        +vectorize()
        +rerank()
    }
    
    MainWindow ||--o{ WorkerThread : manages
    WorkerThread <|-- PageIndexWorker
    WorkerThread <|-- VectorWorker
    WorkerThread <|-- ConverterWorker
    MainWindow ..> BGERetriever : uses
```

## 状态转换图

```mermaid
stateDiagram-v2
    [*] --> Idle : 启动应用
    Idle --> Processing : 开始任务
    Processing --> Indexing : TAB A选中
    Processing --> Vectorizing : TAB B选中
    Processing --> Converting : TAB C选中
    
    Indexing --> Indexing : 解析中
    Indexing --> Indexed : 解析完成
    
    Vectorizing --> Vectorizing : 向量化中
    Vectorizing --> Vectorized : 向量化完成
    
    Converting --> Converting : 转换中
    Converting --> Converted : 转换完成
    
    Indexed --> Idle : 任务完成
    Vectorized --> Idle : 任务完成
    Converted --> Idle : 任务完成
    
    Processing --> Error : 发生错误
    Error --> Idle : 重置
```

## 时序图：RAG查询流程

```mermaid
sequenceDiagram
    participant User as 用户
    participant Frontend as 前端界面
    participant RAG as RAG引擎
    participant VectorDB as 向量数据库
    participant TraditionalDB as 传统数据库
    participant LLM as LLM服务
    participant Response as 响应组装

    User->>Frontend: 输入查询 "发动机维护步骤"
    Frontend->>RAG: 传递查询
    RAG->>RAG: 语义解析和关键词提取
    par 向量检索分支
        RAG->>VectorDB: 向量相似度搜索
        VectorDB-->>RAG: 返回相关文档片段
    and 传统检索分支
        RAG->>TraditionalDB: 关键词匹配搜索
        TraditionalDB-->>RAG: 返回匹配文档
    end
    RAG->>RAG: RRF融合算法
    RAG->>LLM: 生成查询向量
    LLM-->>RAG: 返回向量表示
    RAG->>VectorDB: 计算相似度
    VectorDB-->>RAG: 返回最相关片段
    RAG->>Response: 组装最终结果
    Response-->>Frontend: 返回答案和来源
    Frontend-->>User: 显示最终答案
```

## 部署架构图

```mermaid
graph TB
    subgraph "客户端"
        A[front_pgui.py]
        B[PyQt5界面]
    end

    subgraph "本地服务"
        C[backend_pgui.py]
        D[bge_gui.py]
        E[json_phase2_converter.py]
    end

    subgraph "数据存储"
        F[(SQLite数据库)]
        G[JSON文件存储]
    end

    subgraph "外部API服务"
        H[Qwen API]
        I[BGE API]
        J[BGE Rerank API]
    end

    A --- C
    A --- D
    A --- E
    C --- F
    D --- F
    C --- H
    D --- I
    D --- J
    E --- G
    C --- G
    D --- G

    style A fill:#cde4ff
    style F fill:#f0f8cc
    style H fill:#ffe0e0
    style I fill:#ffe0e0
    style J fill:#ffe0e0
```

---

**图表版本**: 1.0  
**创建日期**: 2026-01-18  
**作者**: RAG Code Buddy Documentation Team