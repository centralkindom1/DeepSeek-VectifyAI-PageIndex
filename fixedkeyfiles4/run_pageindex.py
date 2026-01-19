import argparse
import os
import sys
import json
import asyncio

# === 【关键修改】强制标准输出使用 UTF-8 编码 ===
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr:
    sys.stderr.reconfigure(encoding='utf-8')
# ============================================

# Ensure the script can find the 'pageindex' package in the current directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Fix: Import 'config' explicitly from utils so it can be used to create 'opt'
from pageindex.utils import config, ConfigLoader 
from pageindex.page_index import page_index_main

def main():
    # Define arguments matching those passed by pgui.py
    parser = argparse.ArgumentParser(description="PageIndex Pro CLI")
    parser.add_argument('--pdf_path', type=str, required=True, help="Path to the PDF file")
    parser.add_argument('--model', type=str, default="DeepSeek-V3", help="AI Model to use")
    parser.add_argument('--toc-check-pages', type=int, default=3, help="Number of pages to check for TOC")
    
    # === 新增：接收处理策略参数 ===
    parser.add_argument('--add_text', type=str, default='yes', help="Include full text (yes/no)")
    parser.add_argument('--add_summary', type=str, default='yes', help="Generate AI summary (yes/no)")
    parser.add_argument('--add_desc', type=str, default='yes', help="Generate Doc Description (yes/no)")
    
    # Parse arguments
    args = parser.parse_args()

    # Create the configuration object using 'config' (SimpleNamespace) imported from utils
    # Ensure description and summary features are explicitly enabled ('yes')
    opt = config(
        pdf_path=args.pdf_path,
        model=args.model,
        toc_check_page_num=args.toc_check_pages,
        # Set default values for other options expected by the processor
        max_page_num_each_node=10,
        max_token_num_each_node=5000,
        if_add_node_id='yes',
        
        # --- CRITICAL SETTINGS CONTROLLED BY CLI ---
        if_add_node_text=args.add_text,       # Controlled by GUI Strategy
        if_add_node_summary=args.add_summary, # Controlled by GUI Strategy
        if_add_doc_description=args.add_desc  # Controlled by GUI Strategy
    )

    print(f"[INFO] Starting indexing for: {args.pdf_path}")
    print(f"[INFO] Strategy: Text={args.add_text}, Summary={args.add_summary}, Desc={args.add_desc}")
    
    try:
        # Call the main processing function
        # The result will now be a dictionary containing {doc_name, doc_description, structure}
        result = page_index_main(doc=args.pdf_path, opt=opt)
        
        # === FIX: Disable Printing Massive JSON to Console ===
        # The GUI reads the console output (stdout). Printing thousands of lines of JSON 
        # buries the [SUCCESS] message and makes the log window unusable.
        # The file is already saved to disk by page_index_main.
        
        # print(json.dumps(result, ensure_ascii=False, indent=2)) 
        
    except Exception as e:
        print(f"[ERROR] Failed to process PDF: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()