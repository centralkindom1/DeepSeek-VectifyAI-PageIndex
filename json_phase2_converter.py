#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unified Tree-to-Flat JSON Converter for RAG (Optimized Edition)
结合了百度Comate的工程稳健性与用户自定义的语义优化策略。
功能：将树状 PageIndex JSON 转换为向量数据库所需的扁平化格式。
"""

import json
import os
import sys
import argparse
import time
from typing import Dict, List, Any

# ==========================================
# 辅助类与核心逻辑
# ==========================================

class RAGConverter:
    def __init__(self, input_path: str, output_path: str = None):
        self.input_path = input_path
        self.output_path = output_path if output_path else self._derive_output_path(input_path)
        self.flat_nodes = []
        self.processed_count = 0
        self.doc_title = "Unknown Document"

    def log(self, msg: str, level: str = "INFO"):
        """标准日志输出，兼容前端 Worker"""
        print(f"[{level}] {msg}", flush=True)

    def _derive_output_path(self, input_path: str) -> str:
        """自动生成对标格式的输出文件名"""
        base, ext = os.path.splitext(input_path)
        dirname, filename = os.path.split(base)
        # 加上 vector_RAG_ 前缀，便于识别
        return os.path.join(dirname, f"vector_RAG_{filename}{ext}")

    def _determine_section_hint(self, title: str, content: str) -> str:
        """
        [混合策略] 智能推断章节类型
        优先级：
        1. 结构性关键词 (您的逻辑: 目录/附录/参考文献)
        2. 内容性关键词 (百度逻辑: 警告/图表/步骤)
        3. 默认兜底
        """
        title_lower = title.lower() if title else ""
        content_lower = content.lower() if content else ""

        # --- 策略 A: 基于标题的结构判断 (Structure Hint) ---
        if any(x in title_lower for x in ["content", "目录", "index", "table of contents"]):
            return "目录列表"
        elif any(x in title_lower for x in ["intro", "引言", "概述", "summary", "abstract"]):
            return "引言/概述"
        elif any(x in title_lower for x in ["conclusion", "结论", "结语"]):
            return "结论"
        elif any(x in title_lower for x in ["glossary", "术语", "definition"]):
            return "术语表/定义"
        elif any(x in title_lower for x in ["appendix", "appendices", "附录"]):
            return "附录"
        elif any(x in title_lower for x in ["reference", "参考"]):
            return "参考文献"
        elif any(x in title_lower for x in ["disclaimer", "声明", "legal", "copyright"]):
            return "法律声明"

        # --- 策略 B: 基于内容的特征判断 (Content Hint) ---
        # 仅当标题没有明确结构特征时，分析内容
        if "table" in content_lower and ("row" in content_lower or "col" in content_lower):
            return "数据表格"
        elif any(x in content_lower for x in ["warning", "caution", "danger", "警告", "注意", "危险"]):
            return "安全警告"
        elif any(x in content_lower for x in ["step 1", "step 2", "步骤", "procedure", "流程"]):
            return "操作流程"
        elif any(x in content_lower for x in ["spec", "specification", "参数", "规格"]):
            return "技术规格"

        return "正文章节"

    def _generate_embedding_text(self, path_list: List[str], content: str, hint: str, node: Dict) -> str:
        """
        [语义优化] 构造用于向量化的文本 (Embedding Text)
        采用自然语言模板，增强语义检索能力。
        """
        path_str = " > ".join(path_list)
        
        # 尝试获取节点自带的摘要，如果没有则动态生成一句描述
        summary = node.get('summary', '')
        if not summary:
            summary = f"该部分属于文档的【{hint}】，位于路径 '{path_list[-1] if path_list else '根节点'}' 下。"

        # 组合最终的语义文本 (Prompt Template)
        # 这种拟人化的描述比单纯的 Key-Value 更容易被 Embedding 模型理解
        embedding_text = (
            f"这段内容位于文档 '{self.doc_title}' 的章节路径 '{path_str}' 中。\n"
            f"内容类型提示: {hint}\n"
            f"主要概述: {summary}\n\n"
            f"【原始数据内容】:\n{content}"
        )
        return embedding_text

    def _recursive_walk(self, nodes: List[Dict], path: List[str], depth: int):
        """递归遍历树形结构"""
        for node in nodes:
            # 1. 获取基础信息
            current_title = node.get("title", "Untitled").replace('\n', ' ').strip()
            current_path = path + [current_title]
            
            # 获取内容，优先用 text，其次用 content，最后为空
            original_text = node.get("text", node.get("content", "")).strip()
            
            # 2. 处理 Node ID (优先用原有的，没有则生成)
            node_id = node.get("node_id", f"gen_id_{self.processed_count:05d}")

            # 3. 生成智能标签 (Hint)
            section_hint = self._determine_section_hint(current_title, original_text)

            # 4. 生成语义化 Embedding 文本 (核心优化点)
            # 即使内容为空（只是目录节点），也生成一条记录，保留结构信息
            display_text = original_text if original_text else "(无正文内容，仅作为章节标题存在)"
            embedding_text = self._generate_embedding_text(current_path, display_text, section_hint, node)

            # 5. 构建最终数据对象 (Tab B 标准格式)
            rag_item = {
                "embedding_text": embedding_text,
                "section_hint": section_hint,
                "metadata": {
                    "doc_title": self.doc_title,
                    "section_id": node_id,
                    "section_path": current_path,
                    "depth": depth,
                    "original_length": len(original_text),
                    "strategy": 1,  # 标记为策略1：Rule-Based Hybrid
                    "is_leaf": not bool(node.get("nodes")) # 标记是否为叶子节点
                },
                "original_snippet": original_text
            }

            self.flat_nodes.append(rag_item)
            self.processed_count += 1

            # 进度条反馈 (Comate 风格，每处理 50 个节点反馈一次，减少 IO)
            if self.processed_count % 50 == 0:
                print(f"@@PROGRESS@@{{\"phase\": \"Converting\", \"current\": {self.processed_count}, \"total\": 0}}", flush=True)

            # 6. 递归处理子节点
            if "nodes" in node and isinstance(node["nodes"], list):
                self._recursive_walk(node["nodes"], current_path, depth + 1)

    def run(self):
        """执行转换主流程"""
        self.log(f"Starting Conversion: {self.input_path} -> {self.output_path}")

        if not os.path.exists(self.input_path):
            self.log(f"Input file not found: {self.input_path}", "ERROR")
            return False

        try:
            # 读取文件 (utf-8-sig 兼容 Windows BOM)
            with open(self.input_path, 'r', encoding='utf-8-sig') as f:
                data = json.load(f)

            # 解析根结构
            root_nodes = []
            if isinstance(data, list):
                root_nodes = data
                self.doc_title = "Unknown Document"
            elif isinstance(data, dict):
                # 尝试获取文档标题
                self.doc_title = data.get("doc_name", data.get("title", "Unknown Document"))
                # 兼容不同的子节点键名 (structure 或 nodes)
                root_nodes = data.get("structure", data.get("nodes", []))

            self.log(f"Document identified: {self.doc_title}")
            
            # 开始递归
            self._recursive_walk(root_nodes, [], 1)

            # 写入结果
            with open(self.output_path, 'w', encoding='utf-8') as f:
                json.dump(self.flat_nodes, f, indent=2, ensure_ascii=False)

            # 最终状态汇报
            print(f"@@PROGRESS@@{{\"phase\": \"Converting\", \"current\": {self.processed_count}, \"total\": {self.processed_count}}}", flush=True)
            self.log(f"Success! Processed {self.processed_count} segments.", "SUCCESS")
            self.log(f"Output saved to: {self.output_path}")
            return True

        except Exception as e:
            self.log(f"Critical Error: {str(e)}", "ERROR")
            import traceback
            traceback.print_exc()
            return False

# ==========================================
# 命令行入口
# ==========================================

def main():
    parser = argparse.ArgumentParser(description="Hybrid Rule-Based Tree-to-Flat JSON Converter")
    parser.add_argument("input", help="Input JSON file path (tree structure)")
    # output 变为可选参数，如果不传则自动生成
    parser.add_argument("output", nargs='?', help="Output JSON file path (flat structure)", default=None)
    
    args = parser.parse_args()

    # 强制 stdout 使用 utf-8，防止 Windows 控制台乱码
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

    converter = RAGConverter(args.input, args.output)
    success = converter.run()

    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()