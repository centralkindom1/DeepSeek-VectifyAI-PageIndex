"""
低成本预筛选模型，用于在发送给重排序模型前过滤切片
该模块使用轻量级算法评估切片与查询的相关性置信度，减少tokens消耗
"""
import re
import jieba
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import time


class LowCostFilter:
    """
    低成本切片预筛选器
    使用轻量级算法评估切片与查询的相关性，返回置信度分数
    """
    
    def __init__(self, confidence_threshold=0.3, max_chunks_to_rerank=20):
        """
        初始化预筛选器
        
        Args:
            confidence_threshold: 置信度阈值，低于此值的切片将被过滤
            max_chunks_to_rerank: 发送给重排序模型的最大切片数
        """
        self.confidence_threshold = confidence_threshold
        self.max_chunks_to_rerank = max_chunks_to_rerank
        self.vectorizer = TfidfVectorizer(
            tokenizer=self._jieba_tokenize,
            lowercase=True,
            stop_words=None,
            max_features=5000  # 限制特征数量以保持轻量级
        )
        
    def _jieba_tokenize(self, text):
        """使用jieba进行中文分词"""
        return list(jieba.cut(text))
    
    def calculate_keyword_overlap(self, query, chunk_text):
        """
        计算查询和切片之间的关键词重叠度
        
        Args:
            query: 查询文本
            chunk_text: 切片文本
            
        Returns:
            float: 重叠度分数 (0-1)
        """
        # 中英文分词
        query_words = set(self._jieba_tokenize(query.lower()))
        chunk_words = set(self._jieba_tokenize(chunk_text.lower()))
        
        # 过滤掉长度小于2的词语
        query_words = {w for w in query_words if len(w) >= 2}
        chunk_words = {w for w in chunk_words if len(w) >= 2}
        
        if not query_words and not chunk_words:
            return 0.0
            
        intersection = query_words.intersection(chunk_words)
        union = query_words.union(chunk_words)
        
        if len(union) == 0:
            return 0.0
            
        return len(intersection) / len(union)  # Jaccard相似度
    
    def calculate_semantic_similarity(self, query, chunk_texts):
        """
        使用TF-IDF计算语义相似度
        
        Args:
            query: 查询文本
            chunk_texts: 切片文本列表
            
        Returns:
            list: 相似度分数列表
        """
        try:
            # 创建文档集合（查询+切片）
            all_texts = [query] + chunk_texts
            tfidf_matrix = self.vectorizer.fit_transform(all_texts)
            
            # 查询向量（第一个）
            query_vector = tfidf_matrix[0]
            # 切片向量（其余的）
            chunk_vectors = tfidf_matrix[1:]
            
            # 计算余弦相似度
            similarities = cosine_similarity(query_vector, chunk_vectors).flatten()
            return similarities.tolist()
        except Exception as e:
            print(f"TF-IDF相似度计算错误: {e}")
            # 如果TF-IDF失败，返回基于关键词重叠的分数
            similarities = []
            for chunk_text in chunk_texts:
                similarities.append(self.calculate_keyword_overlap(query, chunk_text))
            return similarities
    
    def calculate_confidence_score(self, query, chunk_text):
        """
        计算单个切片的置信度分数
        
        Args:
            query: 查询文本
            chunk_text: 切片文本
            
        Returns:
            float: 置信度分数 (0-1)
        """
        # 计算关键词重叠度
        keyword_score = self.calculate_keyword_overlap(query, chunk_text)
        
        # 计算语义相似度（使用TF-IDF）
        semantic_score = self.calculate_semantic_similarity(query, [chunk_text])[0]
        
        # 组合分数 (关键词重叠占40%, 语义相似度占60%)
        combined_score = 0.4 * keyword_score + 0.6 * semantic_score
        
        return max(0.0, min(1.0, combined_score))  # 限制在0-1范围内
    
    def filter_chunks_by_confidence(self, query, chunks):
        """
        根据置信度过滤切片
        
        Args:
            query: 查询文本
            chunks: 切片列表，每个元素应包含'id', 'content', 'path'等字段
            
        Returns:
            tuple: (过滤后的切片列表, 置信度分数列表)
        """
        if not chunks:
            return [], []
            
        # 计算所有切片的置信度
        confidence_scores = []
        chunk_contents = [chunk.get('content', '') for chunk in chunks]
        
        # 批量计算语义相似度
        semantic_similarities = self.calculate_semantic_similarity(query, chunk_contents)
        
        for i, chunk in enumerate(chunks):
            content = chunk.get('content', '')
            keyword_score = self.calculate_keyword_overlap(query, content)
            semantic_score = semantic_similarities[i]
            
            # 组合分数
            combined_score = 0.4 * keyword_score + 0.6 * semantic_score
            confidence_scores.append(max(0.0, min(1.0, combined_score)))
            
            # 添加置信度到切片数据中
            chunk['confidence_score'] = combined_score
        
        # 创建(切片, 分数)对并按分数排序
        chunk_score_pairs = list(zip(chunks, confidence_scores))
        chunk_score_pairs.sort(key=lambda x: x[1], reverse=True)
        
        # 应用置信度阈值过滤
        filtered_pairs = [(chunk, score) for chunk, score in chunk_score_pairs 
                         if score >= self.confidence_threshold]
        
        # 限制发送给重排序模型的最大数量
        if len(filtered_pairs) > self.max_chunks_to_rerank:
            filtered_pairs = filtered_pairs[:self.max_chunks_to_rerank]
        
        # 分离切片和分数
        filtered_chunks = [pair[0] for pair in filtered_pairs]
        filtered_scores = [pair[1] for pair in filtered_pairs]
        
        return filtered_chunks, filtered_scores


# 示例使用方法
if __name__ == "__main__":
    # 创建预筛选器实例
    filter_model = LowCostFilter(confidence_threshold=0.2, max_chunks_to_rerank=15)
    
    # 示例查询和切片
    sample_query = "飞机维护程序"
    sample_chunks = [
        {"id": "1", "content": "飞机维护是指对民用飞机进行全面检查、修理和改装的过程，以确保飞行安全。", "path": "维护 > 安全"},
        {"id": "2", "content": "燃油经济性是指飞机在单位距离内消耗燃油的效率。", "path": "性能 > 燃油"},
        {"id": "3", "content": "定期维护计划包括日常检查、周检、月检和年检等不同级别的维护活动。", "path": "维护 > 计划"},
        {"id": "4", "content": "乘客座位布局设计关系到舒适度和安全性。", "path": "客舱 > 设计"},
        {"id": "5", "content": "发动机性能测试是确保飞机正常运行的重要环节。", "path": "维护 > 测试"}
    ]
    
    # 过滤切片
    filtered_chunks, confidence_scores = filter_model.filter_chunks_by_confidence(sample_query, sample_chunks)
    
    print(f"原始切片数量: {len(sample_chunks)}")
    print(f"过滤后切片数量: {len(filtered_chunks)}")
    print("过滤结果:")
    for i, (chunk, score) in enumerate(zip(filtered_chunks, confidence_scores)):
        print(f"  {i+1}. ID: {chunk['id']}, Score: {score:.3f}, Content: {chunk['content'][:50]}...")