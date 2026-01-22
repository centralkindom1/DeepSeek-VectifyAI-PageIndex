import os
import sys
import gc
import torch

# 尝试导入 sentence_transformers
try:
    from sentence_transformers import SentenceTransformer, util
    HAS_LIB = True
except ImportError:
    HAS_LIB = False
    print("Warning: sentence_transformers not found. BGE Loader will fail.")

class BGESemanticFilter:
    """
    【新积木】: BGE-Small-Zh-v1.5 专用加载器
    特性：
    1. 专为 D:\Models\bge-small-zh-v1.5 路径设计
    2. 强制使用 CPU 模式，防止 Win7 显卡兼容问题
    3. 提供与旧模型一致的 compute_similarity 接口
    """
    def __init__(self):
        self.model = None
        self.is_loaded = False
        self.model_name = "BGE-Small-Zh-v1.5"
        
        # 硬编码路径，指向 D 盘
        self.local_path = r"D:\Models\bge-small-zh-v1.5"
        
        if not HAS_LIB:
            print(f"❌ [{self.model_name}] 缺少 sentence_transformers 库")
            return
            
        try:
            print(f">>> [{self.model_name}] 正在初始化...")
            print(f">>> 目标路径: {self.local_path}")
            
            # 检查关键文件是否存在，避免无效加载
            bin_path = os.path.join(self.local_path, "pytorch_model.bin")
            if not os.path.exists(bin_path):
                print(f"❌ 关键文件丢失: {bin_path}")
                self.is_loaded = False
                return

            # Win7 性能保护：限制 Torch 线程数，防止加载瞬间 CPU 100% 卡死
            torch.set_num_threads(2)
            
            # 加载模型 (强制 CPU)
            self.model = SentenceTransformer(self.local_path, device='cpu')
            self.is_loaded = True
            print(f">>> ✅ [{self.model_name}] 加载成功！已准备好工作。")
            
        except Exception as e:
            print(f"❌ [{self.model_name}] 加载异常: {str(e)}")
            self.is_loaded = False

    def compute_similarity(self, query, texts):
        """
        计算接口 (与 LocalSemanticFilter 保持完全一致的多态接口)
        """
        if not self.is_loaded or not self.model or not texts:
            return [0.0] * len(texts)
        
        try:
            # BGE 模型通常需要在 Query 前加指令，但 v1.5 base 版通常直接输入即可
            # 为了保持纯净对比，这里暂不加 "Represent this sentence..." 指令，直接计算
            
            embeddings_query = self.model.encode(query, convert_to_tensor=True)
            embeddings_docs = self.model.encode(texts, convert_to_tensor=True)
            
            # 计算余弦相似度
            cos_scores = util.cos_sim(embeddings_query, embeddings_docs)[0]
            
            # 显式清理显存/内存引用 (Win7 优化)
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            
            return cos_scores.cpu().tolist()
        except Exception as e:
            print(f"[{self.model_name}] Sim Calculation Error: {e}")
            return [0.0] * len(texts)

    def unload(self):
        """主动释放内存"""
        if self.model:
            del self.model
        self.model = None
        self.is_loaded = False
        gc.collect()
        print(f">>> [{self.model_name}] 内存已释放")