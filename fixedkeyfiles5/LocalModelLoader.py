import os
import sys

# 尝试导入 sentence_transformers
try:
    from sentence_transformers import SentenceTransformer, util
    HAS_LOCAL_MODEL_LIB = True
except ImportError:
    HAS_LOCAL_MODEL_LIB = False
    print("Warning: sentence_transformers not found. Local filter will be disabled.")

class LocalSemanticFilter:
    """
    单例类：负责加载本地 Embedding 小模型并计算语义相似度。
    主要用于 Rerank 前的粗排过滤 (Low Cost Filter)。
    """
    def __init__(self):
        self.model = None
        self.is_loaded = False
        
        # 本地缓存路径 (保持原配置)
        # 注意：使用 r"" 原始字符串防止转义问题
        self.local_path = r"C:\Users\Administrator.SK-20220809VSDF\.cache\torch\sentence_transformers\sentence-transformers_all-MiniLM-L6-v2"
        
        if not HAS_LOCAL_MODEL_LIB:
            print("❌ 错误: 缺少 sentence_transformers 库")
            return
            
        try:
            print(f">>> 正在从本地路径加载模型: {self.local_path} ...")
            
            # 检查路径是否存在
            if os.path.exists(self.local_path):
                # 直接加载本地目录，device='cpu' 保证在无 GPU 环境下可用
                self.model = SentenceTransformer(self.local_path, device='cpu')
                self.is_loaded = True
                print(">>> ✅ 本地模型加载成功！(使用 all-MiniLM-L6-v2)")
            else:
                print(f"❌ 路径不存在: {self.local_path}")
                # 如果本地路径不存在，可尝试自动下载（可选逻辑，根据需求开启）
                # self.model = SentenceTransformer("all-MiniLM-L6-v2", device='cpu')
                # self.is_loaded = True
                
        except Exception as e:
            print(f"❌ 加载失败: {str(e)}")
            self.is_loaded = False

    def compute_similarity(self, query, texts):
        """
        计算 Query 与 文本列表 的余弦相似度
        :param query: str
        :param texts: list[str]
        :return: list[float]
        """
        if not self.is_loaded or not self.model or not texts:
            # 如果模型没加载成功，或者没有文本，返回全0分
            return [0.0] * len(texts)
        
        try:
            # 编码 Query
            query_embedding = self.model.encode(query, convert_to_tensor=True)
            # 编码 文本列表
            text_embeddings = self.model.encode(texts, convert_to_tensor=True)
            
            # 计算余弦相似度
            cos_scores = util.cos_sim(query_embedding, text_embeddings)[0]
            
            # 转为 list
            return cos_scores.cpu().tolist()
        except Exception as e:
            print(f"Similarity Compute Error: {e}")
            return [0.0] * len(texts)