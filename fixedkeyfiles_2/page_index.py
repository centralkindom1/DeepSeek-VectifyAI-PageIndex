import os
import json
import copy
import math
import random
import re
import asyncio
from datetime import datetime
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed

# Import from your utils file
from .utils import (
    ChatGPT_API,
    ChatGPT_API_async,
    ChatGPT_API_with_finish_reason,
    add_node_text,
    add_preface_if_needed,
    convert_page_to_int,
    clean_page_numbers,
    remove_structure_text,
    extract_json,
    count_tokens,
    get_page_tokens,
    write_node_id,
    post_processing,
    JsonLogger,
    ConfigLoader,
    get_pdf_name,
    convert_physical_index_to_int,
    get_json_content,
    config,
    get_nodes  # Ensure this is imported or defined if utils.py has it
)

# If get_nodes is not in utils, we define it here locally to be safe
def get_nodes_local(structure):
    if isinstance(structure, dict):
        sn = copy.deepcopy(structure)
        sn.pop('nodes', None)
        nodes = [sn]
        for k in list(structure.keys()):
            if 'nodes' in k: nodes.extend(get_nodes_local(structure[k]))
        return nodes
    elif isinstance(structure, list):
        res = []
        for i in structure: res.extend(get_nodes_local(i))
        return res
    return []

################### Helper: Robustness Utils ###################
def ensure_dict_result(data):
    """
    Robustness Helper:
    Ensures that the data extracted from JSON is a dictionary.
    LLMs sometimes return a list containing a single dict [ { ... } ] instead of just the dict { ... }.
    """
    if isinstance(data, list):
        if len(data) > 0 and isinstance(data[0], dict):
            return data[0]
        return {} 
    if isinstance(data, dict):
        return data
    return {}

################### Helper: Document Description ###################
async def generate_document_description(page_list, model=None):
    """
    Generates a global description of the document.
    ROBUSTNESS UPDATE: Limits input text size to prevent timeouts.
    """
    intro_text = ""
    # Use only first 2 pages or max 8000 chars to be safe for local LLMs
    limit_pages = min(2, len(page_list))
    for page in page_list[:limit_pages]:
        intro_text += page[0] + "\n"
    
    # Strict truncation
    safe_text = intro_text[:8000]
    
    prompt = f"""
    You are an expert document analyst. Please provide a concise, high-level description of the following document. 
    Focus on the main topic, key themes, and purpose of the text.
    
    Document Start:
    {safe_text}
    
    Output format: Just the description paragraph text. No JSON, no markdown.
    """
    try:
        # We use a slightly longer timeout implicitly via the utils retry logic
        description = await ChatGPT_API_async(model=model, prompt=prompt)
        return description.strip()
    except Exception as e:
        print(f"[Warning] Failed to generate doc description: {e}")
        return "Description generation failed due to API error."

################### Helper: Node Summaries ###################
async def generate_summaries_for_structure(structure, model=None):
    """
    Generates summaries for each node in the structure.
    ROBUSTNESS UPDATE: Uses Semaphore to limit concurrency.
    """
    # Use local get_nodes if not in utils, otherwise use imported
    try:
        from .utils import get_nodes
        nodes = get_nodes(structure)
    except ImportError:
        nodes = get_nodes_local(structure)

    # === CRITICAL FIX: CONCURRENCY CONTROL ===
    # Limit to 3 concurrent requests to prevent overwhelming the local Intranet API.
    # Increase this number only if your API is very fast/robust.
    sem = asyncio.Semaphore(3) 

    async def summarize_node(node):
        text_content = node.get('text', '')
        if not text_content: 
            node['summary'] = ""
            return
        
        # Truncate text for summary to avoid context overflow
        # 3000 chars is usually enough for a summary
        safe_content = text_content[:3000]
        
        prompt = f"Summarize the following section text in one concise sentence:\n\n{safe_content}"
        
        async with sem:
            try:
                summary = await ChatGPT_API_async(model, prompt)
                node['summary'] = summary.strip()
                # Optional: Simple print to show progress
                # print(f"[DEBUG] Summarized node: {node.get('title', 'Unknown')[:20]}...")
            except Exception as e:
                print(f"[ERROR] Failed to summarize node {node.get('title')}: {e}")
                node['summary'] = "Summary generation failed."

    tasks = []
    for node in nodes: 
        tasks.append(summarize_node(node))
    
    if tasks: 
        await asyncio.gather(*tasks)
    return structure

################### Helper: Init Node Fields ###################
def init_node_fields(structure):
    if isinstance(structure, list):
        for item in structure:
            init_node_fields(item)
    elif isinstance(structure, dict):
        if 'summary' not in structure:
            structure['summary'] = ""
        if 'nodes' in structure:
            init_node_fields(structure['nodes'])

################### check title in page #########################################################
async def check_title_appearance(item, page_list, start_index=1, model=None):    
    title = item['title']
    
    if 'physical_index' not in item or item['physical_index'] is None:
        return {'list_index': item.get('list_index'), 'answer': 'no', 'title': title, 'page_number': None}
    
    try:
        page_number = int(item['physical_index'])
    except (ValueError, TypeError):
        return {'list_index': item.get('list_index'), 'answer': 'no', 'title': title, 'page_number': None}
    
    list_idx = page_number - start_index
    if list_idx < 0 or list_idx >= len(page_list):
        return {'list_index': item.get('list_index'), 'answer': 'no', 'title': title, 'page_number': page_number}

    page_text = page_list[list_idx][0]

    prompt = f"""
    Your job is to check if the given section appears or starts in the given page_text.
    Note: do fuzzy matching, ignore any space inconsistency in the page_text.
    The given section title is {title}.
    The given page_text is {page_text}.
    
    Reply format:
    {{
        "thinking": <why do you think the section appears or starts in the page_text>
        "answer": "yes or no" (yes if the section appears or starts in the page_text, no otherwise)
    }}
    Directly return the final JSON structure. Do not output anything else."""

    response = await ChatGPT_API_async(model=model, prompt=prompt)
    response = extract_json(response)
    response = ensure_dict_result(response)

    if 'answer' in response:
        answer = response['answer']
    else:
        answer = 'no'
    return {'list_index': item.get('list_index'), 'answer': answer, 'title': title, 'page_number': page_number}

async def check_title_appearance_in_start(title, page_text, model=None, logger=None):    
    prompt = f"""
    You will be given the current section title and the current page_text.
    Your job is to check if the current section starts in the beginning of the given page_text.
    If there are other contents before the current section title, then the current section does not start in the beginning of the given page_text.
    If the current section title is the first content in the given page_text, then the current section starts in the beginning of the given page_text.

    Note: do fuzzy matching, ignore any space inconsistency in the page_text.

    The given section title is {title}.
    The given page_text is {page_text}.
    
    reply format:
    {{
        "thinking": <why do you think the section appears or starts in the page_text>
        "start_begin": "yes or no" (yes if the section starts in the beginning of the page_text, no otherwise)
    }}
    Directly return the final JSON structure. Do not output anything else."""

    response = await ChatGPT_API_async(model=model, prompt=prompt)
    response = extract_json(response)
    response = ensure_dict_result(response)
    
    if logger:
        logger.info(f"Response: {response}")
    return response.get("start_begin", "no")

async def check_title_appearance_in_start_concurrent(structure, page_list, model=None, logger=None):
    if logger:
        logger.info("Checking title appearance in start concurrently")
    
    for item in structure:
        if item.get('physical_index') is None:
            item['appear_start'] = 'no'

    tasks = []
    valid_items = []
    for item in structure:
        if item.get('physical_index') is not None:
            idx = int(item['physical_index'])
            if 0 < idx <= len(page_list):
                page_text = page_list[idx - 1][0]
                tasks.append(check_title_appearance_in_start(item['title'], page_text, model=model, logger=logger))
                valid_items.append(item)

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for item, result in zip(valid_items, results):
        if isinstance(result, Exception):
            if logger:
                logger.error(f"Error checking start for {item['title']}: {result}")
            item['appear_start'] = 'no'
        else:
            item['appear_start'] = result

    return structure

def toc_detector_single_page(content, model=None):
    prompt = f"""
    Your job is to detect if there is a table of content provided in the given text.
    Given text: {content}
    return the following JSON format:
    {{
        "thinking": <why do you think there is a table of content in the given text>
        "toc_detected": "<yes or no>",
    }}
    Directly return the final JSON structure. Do not output anything else.
    Please note: abstract,summary, notation list, figure list, table list, etc. are not table of contents."""
    response = ChatGPT_API(model=model, prompt=prompt)
    json_content = extract_json(response)
    json_content = ensure_dict_result(json_content)
    
    return json_content.get('toc_detected', 'no')

def check_if_toc_extraction_is_complete(content, toc, model=None):
    prompt = f"""
    You are given a partial document and a table of contents.
    Your job is to check if the table of contents is complete.
    Reply format: {{ "thinking": "...", "completed": "yes" or "no" }}
    Directly return the final JSON structure."""
    prompt = prompt + '\n Document:\n' + content + '\n Table of contents:\n' + toc
    response = ChatGPT_API(model=model, prompt=prompt)
    json_content = extract_json(response)
    json_content = ensure_dict_result(json_content)
    
    return json_content.get('completed', 'no')

def check_if_toc_transformation_is_complete(content, toc, model=None):
    prompt = f"""
    You are given a raw table of contents and a table of contents.
    Your job is to check if the table of contents is complete.
    Reply format: {{ "thinking": "...", "completed": "yes" or "no" }}
    Directly return the final JSON structure."""
    prompt = prompt + '\n Raw Table of contents:\n' + content + '\n Cleaned Table of contents:\n' + toc
    response = ChatGPT_API(model=model, prompt=prompt)
    json_content = extract_json(response)
    json_content = ensure_dict_result(json_content)
    
    return json_content.get('completed', 'no')

def extract_toc_content(content, model=None):
    prompt = f"""
    Your job is to extract the full table of contents from the given text, replace ... with :
    Given text: {content}
    Directly return the full table of contents content. Do not output anything else."""
    response, finish_reason = ChatGPT_API_with_finish_reason(model=model, prompt=prompt)
    if_complete = check_if_toc_transformation_is_complete(content, response, model)
    if if_complete == "yes" and finish_reason == "finished":
        return response
    
    chat_history = [{"role": "user", "content": prompt}, {"role": "assistant", "content": response}]
    prompt = f"""please continue the generation of table of contents , directly output the remaining part of the structure"""
    new_response, finish_reason = ChatGPT_API_with_finish_reason(model=model, prompt=prompt, chat_history=chat_history)
    response = response + new_response
    if_complete = check_if_toc_transformation_is_complete(content, response, model)
    while not (if_complete == "yes" and finish_reason == "finished"):
        chat_history = [{"role": "user", "content": prompt}, {"role": "assistant", "content": response}]
        prompt = f"""please continue the generation of table of contents , directly output the remaining part of the structure"""
        new_response, finish_reason = ChatGPT_API_with_finish_reason(model=model, prompt=prompt, chat_history=chat_history)
        response = response + new_response
        if_complete = check_if_toc_transformation_is_complete(content, response, model)
        if len(chat_history) > 5: break 
    return response

def detect_page_index(toc_content, model=None):
    print('start detect_page_index')
    prompt = f"""
    You will be given the table of contents.
    Your job is to detect if there are page numbers/indices given within the table of contents.
    Given text: {toc_content}
    Reply format: {{ "thinking": "...", "page_index_given_in_toc": "<yes or no>" }}
    Directly return the final JSON structure."""
    
    response = ChatGPT_API(model=model, prompt=prompt)
    json_content = extract_json(response)
    json_content = ensure_dict_result(json_content)
    
    return json_content.get('page_index_given_in_toc', 'no')

def toc_extractor(page_list, toc_page_list, model):
    def transform_dots_to_colon(text):
        text = re.sub(r'\.{5,}', ': ', text)
        text = re.sub(r'(?:\. ){5,}\.?', ': ', text)
        return text
    toc_content = ""
    for page_index in toc_page_list:
        toc_content += page_list[page_index][0]
    toc_content = transform_dots_to_colon(toc_content)
    has_page_index = detect_page_index(toc_content, model=model)
    return {"toc_content": toc_content, "page_index_given_in_toc": has_page_index}

def toc_index_extractor(toc, content, model=None):
    print('start toc_index_extractor')
    tob_extractor_prompt = """
    You are given a table of contents in a json format and several pages of a document, your job is to add the physical_index to the table of contents in the json format.
    The provided pages contains tags like <physical_index_X> and <physical_index_X> to indicate the physical location of the page X.
    The structure variable is the numeric system which represents the index of the hierarchy section in the table of contents.
    The response should be in the following JSON format: 
    [ { "structure": "...", "title": "...", "physical_index": "<physical_index_X>" }, ... ]
    Directly return the final JSON structure."""
    prompt = tob_extractor_prompt + '\nTable of contents:\n' + str(toc) + '\nDocument pages:\n' + content
    response = ChatGPT_API(model=model, prompt=prompt)
    json_content = extract_json(response)    
    return json_content

def toc_transformer(toc_content, model=None):
    print('start toc_transformer')
    init_prompt = """
    You are given a table of contents, You job is to transform the whole table of content into a JSON format included table_of_contents.
    The response should be in the following JSON format: 
    { table_of_contents: [ { "structure": "...", "title": "...", "page": <page number or None> }, ... ] }
    You should transform the full table of contents in one go. Directly return the final JSON structure."""
    prompt = init_prompt + '\n Given table of contents\n:' + toc_content
    last_complete, finish_reason = ChatGPT_API_with_finish_reason(model=model, prompt=prompt)
    if_complete = check_if_toc_transformation_is_complete(toc_content, last_complete, model)
    if if_complete == "yes" and finish_reason == "finished":
        last_complete = extract_json(last_complete)
        last_complete = ensure_dict_result(last_complete)
        
        if isinstance(last_complete, dict) and 'table_of_contents' in last_complete:
            cleaned_response=convert_page_to_int(last_complete['table_of_contents'])
            return cleaned_response
            
    last_complete = get_json_content(last_complete)
    while not (if_complete == "yes" and finish_reason == "finished"):
        position = last_complete.rfind('}')
        if position != -1: last_complete = last_complete[:position+2]
        prompt = f"""
        Your task is to continue the table of contents json structure, directly output the remaining part of the json structure.
        The raw table of contents json structure is: {toc_content}
        The incomplete transformed table of contents json structure is: {last_complete}
        Please continue the json structure."""
        new_complete, finish_reason = ChatGPT_API_with_finish_reason(model=model, prompt=prompt)
        if new_complete.startswith('```json'): new_complete =  get_json_content(new_complete)
        last_complete = last_complete + new_complete
        if_complete = check_if_toc_transformation_is_complete(toc_content, last_complete, model)
    try:
        last_complete = json.loads(last_complete)
        last_complete = ensure_dict_result(last_complete)
        cleaned_response=convert_page_to_int(last_complete.get('table_of_contents', []))
        return cleaned_response
    except: return []

def find_toc_pages(start_page_index, page_list, opt, logger=None):
    print('start find_toc_pages')
    last_page_is_yes = False
    toc_page_list = []
    i = start_page_index
    while i < len(page_list):
        if i >= opt.toc_check_page_num and not last_page_is_yes: break
        detected_result = toc_detector_single_page(page_list[i][0],model=opt.model)
        if detected_result == 'yes':
            if logger: logger.info(f'Page {i} has toc')
            toc_page_list.append(i)
            last_page_is_yes = True
        elif detected_result == 'no' and last_page_is_yes:
            if logger: logger.info(f'Found the last page with toc: {i-1}')
            break
        i += 1
    if not toc_page_list and logger: logger.info('No toc found')
    return toc_page_list

def remove_page_number(data):
    if isinstance(data, dict):
        data.pop('page_number', None)  
        for key in list(data.keys()):
            if 'nodes' in key: remove_page_number(data[key])
    elif isinstance(data, list):
        for item in data: remove_page_number(item)
    return data

def extract_matching_page_pairs(toc_page, toc_physical_index, start_page_index):
    pairs = []
    if not isinstance(toc_physical_index, list): return pairs
    for phy_item in toc_physical_index:
        for page_item in toc_page:
            if phy_item.get('title') == page_item.get('title'):
                physical_index = phy_item.get('physical_index')
                if physical_index is not None:
                    try:
                        p_idx = int(physical_index)
                        if p_idx >= start_page_index:
                            pairs.append({'title': phy_item.get('title'), 'page': page_item.get('page'), 'physical_index': p_idx})
                    except: pass
    return pairs

def calculate_page_offset(pairs):
    differences = []
    for pair in pairs:
        try:
            physical_index = pair['physical_index']
            page_number = pair['page']
            if physical_index is not None and page_number is not None:
                difference = physical_index - page_number
                differences.append(difference)
        except (KeyError, TypeError): continue
    if not differences: return 0
    difference_counts = {}
    for diff in differences: difference_counts[diff] = difference_counts.get(diff, 0) + 1
    most_common = max(difference_counts.items(), key=lambda x: x[1])[0]
    return most_common

def add_page_offset_to_toc_json(data, offset):
    for i in range(len(data)):
        if data[i].get('page') is not None and isinstance(data[i]['page'], int):
            data[i]['physical_index'] = data[i]['page'] + offset
    return data

def page_list_to_group_text(page_contents, token_lengths, max_tokens=20000, overlap_page=1):    
    num_tokens = sum(token_lengths)
    if num_tokens <= max_tokens:
        page_text = "".join(page_contents)
        return [page_text]
    subsets = []
    current_subset = []
    current_token_count = 0
    expected_parts_num = math.ceil(num_tokens / max_tokens)
    average_tokens_per_part = math.ceil(((num_tokens / expected_parts_num) + max_tokens) / 2)
    for i, (page_content, page_tokens) in enumerate(zip(page_contents, token_lengths)):
        if current_token_count + page_tokens > average_tokens_per_part:
            subsets.append(''.join(current_subset))
            overlap_start = max(i - overlap_page, 0)
            current_subset = page_contents[overlap_start:i]
            current_token_count = sum(token_lengths[overlap_start:i])
        current_subset.append(page_content)
        current_token_count += page_tokens
    if current_subset: subsets.append(''.join(current_subset))
    print('divide page_list to groups', len(subsets))
    return subsets

def add_page_number_to_toc(part, structure, model=None):
    fill_prompt_seq = """
    You are given an JSON structure of a document and a partial part of the document. Your task is to check if the title that is described in the structure is started in the partial given document.
    The provided text contains tags like <physical_index_X> and <physical_index_X> to indicate the physical location of the page X. 
    If the full target section starts in the partial given document, insert the given JSON structure with the "start": "yes", and "start_index": "<physical_index_X>".
    If the full target section does not start in the partial given document, insert "start": "no",  "start_index": None.
    The response should be in the following format. 
        [ { "structure": "...", "title": "...", "start": "<yes or no>", "physical_index": "<physical_index_X> (keep the format)" or None }, ... ]    
    The given structure contains the result of the previous part, you need to fill the result of the current part, do not change the previous result.
    Directly return the final JSON structure. Do not output anything else."""
    
    prompt = fill_prompt_seq + f"\n\nCurrent Partial Document:\n{part}\n\nGiven Structure\n{json.dumps(structure, indent=2, ensure_ascii=False)}\n"
    
    current_json_raw = ChatGPT_API(model=model, prompt=prompt)
    json_result = extract_json(current_json_raw)
    if isinstance(json_result, list):
        for item in json_result:
            if 'start' in item: del item['start']
        return json_result
    return structure

def remove_first_physical_index_section(text):
    pattern = r'<physical_index_\d+>.*?<physical_index_\d+>'
    match = re.search(pattern, text, re.DOTALL)
    if match: return text.replace(match.group(0), '', 1)
    return text

def generate_toc_continue(toc_content, part, model="gpt-4o-2024-11-20"):
    print('start generate_toc_continue')
    prompt = """
    You are an expert in extracting hierarchical tree structure.
    You are given a tree structure of the previous part and the text of the current part.
    Your task is to continue the tree structure from the previous part to include the current part.
    The response should be in the following format. 
        [ { "structure": "...", "title": "...", "physical_index": "<physical_index_X>" }, ... ]    
    Directly return the additional part of the final JSON structure. Do not output anything else."""
    
    prompt = prompt + '\nGiven text\n:' + part + '\nPrevious tree structure\n:' + json.dumps(toc_content, indent=2, ensure_ascii=False)
    
    response, finish_reason = ChatGPT_API_with_finish_reason(model=model, prompt=prompt)
    if finish_reason == 'finished': return extract_json(response)
    
    # [Robustness] Handle incomplete/failed extraction
    print("[WARNING] generate_toc_continue failed to complete. Returning partial/empty.")
    return []
    
def generate_toc_init(part, model=None):
    print('start generate_toc_init')
    prompt = """
    You are an expert in extracting hierarchical tree structure, your task is to generate the tree structure of the document.
    The response should be in the following format. 
        [ {{ "structure": "...", "title": "...", "physical_index": "<physical_index_X>" }}, ],
    Directly return the final JSON structure. Do not output anything else."""
    prompt = prompt + '\nGiven text\n:' + part
    response, finish_reason = ChatGPT_API_with_finish_reason(model=model, prompt=prompt)
    if finish_reason == 'finished': return extract_json(response)
    
    print("[WARNING] generate_toc_init failed. Returning empty list.")
    return []

def process_no_toc(page_list, start_index=1, model=None, logger=None):
    page_contents=[]
    token_lengths=[]
    for page_index in range(start_index, start_index+len(page_list)):
        page_text = f"<physical_index_{page_index}>\n{page_list[page_index-start_index][0]}\n<physical_index_{page_index}>\n\n"
        page_contents.append(page_text)
        token_lengths.append(count_tokens(page_text, model))
    group_texts = page_list_to_group_text(page_contents, token_lengths)
    if logger: logger.info(f'len(group_texts): {len(group_texts)}')
    
    # 处理第一部分
    toc_with_page_number = generate_toc_init(group_texts[0], model)
    if not isinstance(toc_with_page_number, list): toc_with_page_number = []

    # 处理后续部分
    for group_text in group_texts[1:]:
        toc_with_page_number_additional = generate_toc_continue(toc_with_page_number, group_text, model)    
        if isinstance(toc_with_page_number_additional, list):
            toc_with_page_number.extend(toc_with_page_number_additional)
            
    if logger: logger.info(f'generate_toc: {toc_with_page_number}')
    toc_with_page_number = convert_physical_index_to_int(toc_with_page_number)
    if logger: logger.info(f'convert_physical_index_to_int: {toc_with_page_number}')
    return toc_with_page_number

def process_toc_no_page_numbers(toc_content, toc_page_list, page_list,  start_index=1, model=None, logger=None):
    page_contents=[]
    token_lengths=[]
    toc_content = toc_transformer(toc_content, model)
    if logger: logger.info(f'toc_transformer: {toc_content}')
    for page_index in range(start_index, start_index+len(page_list)):
        page_text = f"<physical_index_{page_index}>\n{page_list[page_index-start_index][0]}\n<physical_index_{page_index}>\n\n"
        page_contents.append(page_text)
        token_lengths.append(count_tokens(page_text, model))
    group_texts = page_list_to_group_text(page_contents, token_lengths)
    if logger: logger.info(f'len(group_texts): {len(group_texts)}')
    toc_with_page_number=copy.deepcopy(toc_content)
    for group_text in group_texts:
        toc_with_page_number = add_page_number_to_toc(group_text, toc_with_page_number, model)
    if logger: logger.info(f'add_page_number_to_toc: {toc_with_page_number}')
    toc_with_page_number = convert_physical_index_to_int(toc_with_page_number)
    if logger: logger.info(f'convert_physical_index_to_int: {toc_with_page_number}')
    return toc_with_page_number

def process_toc_with_page_numbers(toc_content, toc_page_list, page_list, toc_check_page_num=None, model=None, logger=None):
    toc_with_page_number = toc_transformer(toc_content, model)
    if logger: logger.info(f'toc_with_page_number: {toc_with_page_number}')
    toc_no_page_number = remove_page_number(copy.deepcopy(toc_with_page_number))
    start_page_index = toc_page_list[-1] + 1
    main_content = ""
    for page_index in range(start_page_index, min(start_page_index + toc_check_page_num, len(page_list))):
        if page_index < len(page_list):
            main_content += f"<physical_index_{page_index+1}>\n{page_list[page_index][0]}\n<physical_index_{page_index+1}>\n\n"
    toc_with_physical_index = toc_index_extractor(toc_no_page_number, main_content, model)
    if logger: logger.info(f'toc_with_physical_index: {toc_with_physical_index}')
    toc_with_physical_index = convert_physical_index_to_int(toc_with_physical_index)
    if logger: logger.info(f'toc_with_physical_index: {toc_with_physical_index}')
    matching_pairs = extract_matching_page_pairs(toc_with_page_number, toc_with_physical_index, start_page_index)
    if logger: logger.info(f'matching_pairs: {matching_pairs}')
    offset = calculate_page_offset(matching_pairs)
    if logger: logger.info(f'offset: {offset}')
    toc_with_page_number = add_page_offset_to_toc_json(toc_with_page_number, offset)
    if logger: logger.info(f'toc_with_page_number: {toc_with_page_number}')
    toc_with_page_number = process_none_page_numbers(toc_with_page_number, page_list, model=model)
    if logger: logger.info(f'toc_with_page_number: {toc_with_page_number}')
    return toc_with_page_number

def process_none_page_numbers(toc_items, page_list, start_index=1, model=None):
    for i, item in enumerate(toc_items):
        if "physical_index" not in item:
            prev_physical_index = 0
            for j in range(i - 1, -1, -1):
                if toc_items[j].get('physical_index') is not None:
                    prev_physical_index = toc_items[j]['physical_index']
                    break
            next_physical_index = len(page_list) 
            for j in range(i + 1, len(toc_items)):
                if toc_items[j].get('physical_index') is not None:
                    next_physical_index = toc_items[j]['physical_index']
                    break
            page_contents = []
            for page_index in range(prev_physical_index, next_physical_index+1):
                list_index = page_index - start_index
                if list_index >= 0 and list_index < len(page_list):
                    page_text = f"<physical_index_{page_index}>\n{page_list[list_index][0]}\n<physical_index_{page_index}>\n\n"
                    page_contents.append(page_text)
                else: continue
            item_copy = copy.deepcopy(item)
            if 'page' in item_copy: del item_copy['page']
            result = add_page_number_to_toc(page_contents, item_copy, model)
            if result and isinstance(result, list):
                res_item = result[0]
                if isinstance(res_item.get('physical_index'), str) and res_item['physical_index'].startswith('<physical_index'):
                    item['physical_index'] = int(res_item['physical_index'].split('_')[-1].rstrip('>').strip())
                    if 'page' in item: del item['page']
    return toc_items

def check_toc(page_list, opt=None):
    toc_page_list = find_toc_pages(start_page_index=0, page_list=page_list, opt=opt)
    if len(toc_page_list) == 0:
        print('no toc found')
        return {'toc_content': None, 'toc_page_list': [], 'page_index_given_in_toc': 'no'}
    else:
        print('toc found')
        toc_json = toc_extractor(page_list, toc_page_list, opt.model)
        
        if isinstance(toc_json, dict) and toc_json.get('page_index_given_in_toc') == 'yes':
            print('index found')
            return {'toc_content': toc_json['toc_content'], 'toc_page_list': toc_page_list, 'page_index_given_in_toc': 'yes'}
        else:
            current_start_index = toc_page_list[-1] + 1
            while (isinstance(toc_json, dict) and toc_json.get('page_index_given_in_toc') == 'no' and 
                   current_start_index < len(page_list) and 
                   current_start_index < opt.toc_check_page_num):
                additional_toc_pages = find_toc_pages(start_page_index=current_start_index, page_list=page_list, opt=opt)
                if len(additional_toc_pages) == 0: break
                additional_toc_json = toc_extractor(page_list, additional_toc_pages, opt.model)
                if isinstance(additional_toc_json, dict) and additional_toc_json.get('page_index_given_in_toc') == 'yes':
                    print('index found')
                    return {'toc_content': additional_toc_json['toc_content'], 'toc_page_list': additional_toc_pages, 'page_index_given_in_toc': 'yes'}
                else:
                    current_start_index = additional_toc_pages[-1] + 1
            print('index not found')
            return {'toc_content': toc_json['toc_content'], 'toc_page_list': toc_page_list, 'page_index_given_in_toc': 'no'}

def single_toc_item_index_fixer(section_title, content, model="gpt-4o-2024-11-20"):
    tob_extractor_prompt = """
    You are given a section title and several pages of a document, your job is to find the physical index of the start page of the section in the partial document.
    Reply in a JSON format: { "thinking": "...", "physical_index": "<physical_index_X>" }
    Directly return the final JSON structure."""
    prompt = tob_extractor_prompt + '\nSection Title:\n' + str(section_title) + '\nDocument pages:\n' + content
    response = ChatGPT_API(model=model, prompt=prompt)
    json_content = extract_json(response)
    json_content = ensure_dict_result(json_content)
    
    return convert_physical_index_to_int([json_content])[0].get('physical_index')

async def fix_incorrect_toc(toc_with_page_number, page_list, incorrect_results, start_index=1, model=None, logger=None):
    print(f'start fix_incorrect_toc with {len(incorrect_results)} incorrect results')
    incorrect_indices = {result['list_index'] for result in incorrect_results}
    end_index = len(page_list) + start_index - 1
    
    async def process_and_check_item(incorrect_item):
        try:
            list_index = incorrect_item['list_index']
            if list_index < 0 or list_index >= len(toc_with_page_number): return None
            prev_correct = None
            for i in range(list_index-1, -1, -1):
                if i not in incorrect_indices and i >= 0 and i < len(toc_with_page_number):
                    physical_index = toc_with_page_number[i].get('physical_index')
                    if physical_index is not None:
                        prev_correct = physical_index
                        break
            if prev_correct is None: prev_correct = start_index - 1
            next_correct = None
            for i in range(list_index+1, len(toc_with_page_number)):
                if i not in incorrect_indices and i >= 0 and i < len(toc_with_page_number):
                    physical_index = toc_with_page_number[i].get('physical_index')
                    if physical_index is not None:
                        next_correct = physical_index
                        break
            if next_correct is None: next_correct = end_index
            page_contents=[]
            for page_index in range(prev_correct, next_correct+1):
                list_index_local = page_index - start_index
                if list_index_local >= 0 and list_index_local < len(page_list):
                    page_text = f"<physical_index_{page_index}>\n{page_list[list_index_local][0]}\n<physical_index_{page_index}>\n\n"
                    page_contents.append(page_text)
                else: continue
            content_range = ''.join(page_contents)
            physical_index_int = single_toc_item_index_fixer(incorrect_item['title'], content_range, model)
            if physical_index_int is None: return None
            check_item = incorrect_item.copy()
            check_item['physical_index'] = physical_index_int
            check_result = await check_title_appearance(check_item, page_list, start_index, model)
            return {
                'list_index': list_index,
                'title': incorrect_item['title'],
                'physical_index': physical_index_int,
                'is_valid': check_result['answer'] == 'yes'
            }
        except Exception as e:
            if logger: logger.error(f"Error fixing item {incorrect_item}: {e}")
            return None

    tasks = [process_and_check_item(item) for item in incorrect_results]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    valid_results = []
    for r in results:
        if r and not isinstance(r, Exception): valid_results.append(r)
    invalid_results = []
    for result in valid_results:
        if result['is_valid']:
            list_idx = result['list_index']
            if 0 <= list_idx < len(toc_with_page_number):
                toc_with_page_number[list_idx]['physical_index'] = result['physical_index']
            else: invalid_results.append(result)
        else: invalid_results.append(result)
    return toc_with_page_number, invalid_results

async def fix_incorrect_toc_with_retries(toc_with_page_number, page_list, incorrect_results, start_index=1, max_attempts=3, model=None, logger=None):
    print('start fix_incorrect_toc')
    fix_attempt = 0
    current_toc = toc_with_page_number
    current_incorrect = incorrect_results
    while current_incorrect:
        print(f"Fixing {len(current_incorrect)} incorrect results")
        current_toc, current_incorrect = await fix_incorrect_toc(current_toc, page_list, current_incorrect, start_index, model, logger)
        fix_attempt += 1
        if fix_attempt >= max_attempts:
            if logger: logger.info("Maximum fix attempts reached")
            break
    return current_toc, current_incorrect

async def verify_toc(page_list, list_result, start_index=1, N=None, model=None):
    print('start verify_toc')
    last_physical_index = None
    for item in reversed(list_result):
        if item.get('physical_index') is not None:
            last_physical_index = item['physical_index']
            break
    if last_physical_index is None: return 0, []
    if N is None:
        print('check all items')
        sample_indices = range(0, len(list_result))
    else:
        N = min(N, len(list_result))
        print(f'check {N} items')
        sample_indices = random.sample(range(0, len(list_result)), N)
    indexed_sample_list = []
    for idx in sample_indices:
        item = list_result[idx]
        if item.get('physical_index') is not None:
            item_with_index = item.copy()
            item_with_index['list_index'] = idx
            indexed_sample_list.append(item_with_index)
    tasks = [check_title_appearance(item, page_list, start_index, model) for item in indexed_sample_list]
    results = await asyncio.gather(*tasks)
    correct_count = 0
    incorrect_results = []
    for result in results:
        if result['answer'] == 'yes': correct_count += 1
        else: incorrect_results.append(result)
    checked_count = len(results)
    accuracy = correct_count / checked_count if checked_count > 0 else 0
    print(f"accuracy: {accuracy*100:.2f}%")
    return accuracy, incorrect_results

async def meta_processor(page_list, mode=None, toc_content=None, toc_page_list=None, start_index=1, opt=None, logger=None):
    print(mode)
    print(f'start_index: {start_index}')
    if mode == 'process_toc_with_page_numbers':
        toc_with_page_number = process_toc_with_page_numbers(toc_content, toc_page_list, page_list, toc_check_page_num=opt.toc_check_page_num, model=opt.model, logger=logger)
    elif mode == 'process_toc_no_page_numbers':
        toc_with_page_number = process_toc_no_page_numbers(toc_content, toc_page_list, page_list, model=opt.model, logger=logger)
    else:
        toc_with_page_number = process_no_toc(page_list, start_index=start_index, model=opt.model, logger=logger)
            
    toc_with_page_number = [item for item in toc_with_page_number if item.get('physical_index') is not None] 
    toc_with_page_number = validate_and_truncate_physical_indices(toc_with_page_number, len(page_list), start_index=start_index, logger=logger)
    accuracy, incorrect_results = await verify_toc(page_list, toc_with_page_number, start_index=start_index, model=opt.model)
    if logger: logger.info({'mode': 'process_toc_with_page_numbers', 'accuracy': accuracy, 'incorrect_results': incorrect_results})
    
    if accuracy == 1.0 and len(incorrect_results) == 0:
        return toc_with_page_number
    
    if accuracy > 0.6 and len(incorrect_results) > 0:
        toc_with_page_number, incorrect_results = await fix_incorrect_toc_with_retries(toc_with_page_number, page_list, incorrect_results,start_index=start_index, max_attempts=3, model=opt.model, logger=logger)
        return toc_with_page_number
    else:
        if mode == 'process_toc_with_page_numbers':
            return await meta_processor(page_list, mode='process_toc_no_page_numbers', toc_content=toc_content, toc_page_list=toc_page_list, start_index=start_index, opt=opt, logger=logger)
        elif mode == 'process_toc_no_page_numbers':
            return await meta_processor(page_list, mode='process_no_toc', start_index=start_index, opt=opt, logger=logger)
        else:
            warning_msg = f"Low accuracy ({accuracy:.2%}) in final fallback mode. Forcing return of best-effort results."
            print(f"[WARNING] {warning_msg}")
            if logger: logger.info(warning_msg)
            return toc_with_page_number
        
async def process_large_node_recursively(node, page_list, opt=None, logger=None):
    if node['end_index'] <= node['start_index']: return node
    node_page_list = page_list[node['start_index']-1:node['end_index']]
    token_num = sum([page[1] for page in node_page_list])
    if node['end_index'] - node['start_index'] > opt.max_page_num_each_node and token_num >= opt.max_token_num_each_node:
        print('large node:', node['title'], 'start_index:', node['start_index'], 'end_index:', node['end_index'], 'token_num:', token_num)
        node_toc_tree = await meta_processor(node_page_list, mode='process_no_toc', start_index=node['start_index'], opt=opt, logger=logger)
        node_toc_tree = await check_title_appearance_in_start_concurrent(node_toc_tree, page_list, model=opt.model, logger=logger)
        valid_node_toc_items = [item for item in node_toc_tree if item.get('physical_index') is not None]
        if valid_node_toc_items and node['title'].strip() == valid_node_toc_items[0]['title'].strip():
            node['nodes'] = post_processing(valid_node_toc_items[1:], node['end_index'])
            if len(valid_node_toc_items) > 1: node['end_index'] = valid_node_toc_items[1]['start_index'] 
        else:
            node['nodes'] = post_processing(valid_node_toc_items, node['end_index'])
            if valid_node_toc_items: node['end_index'] = valid_node_toc_items[0]['start_index']
    if 'nodes' in node and node['nodes']:
        tasks = [process_large_node_recursively(child_node, page_list, opt, logger=logger) for child_node in node['nodes']]
        await asyncio.gather(*tasks)
    return node

async def tree_parser(page_list, opt, doc=None, logger=None):
    check_toc_result = check_toc(page_list, opt)
    if logger: logger.info(check_toc_result)
    if check_toc_result.get("toc_content") and check_toc_result["toc_content"].strip() and check_toc_result["page_index_given_in_toc"] == "yes":
        toc_with_page_number = await meta_processor(page_list, mode='process_toc_with_page_numbers', start_index=1, toc_content=check_toc_result['toc_content'], toc_page_list=check_toc_result['toc_page_list'], opt=opt, logger=logger)
    else:
        toc_with_page_number = await meta_processor(page_list, mode='process_no_toc', start_index=1, opt=opt, logger=logger)
    toc_with_page_number = add_preface_if_needed(toc_with_page_number)
    toc_with_page_number = await check_title_appearance_in_start_concurrent(toc_with_page_number, page_list, model=opt.model, logger=logger)
    valid_toc_items = [item for item in toc_with_page_number if item.get('physical_index') is not None]
    toc_tree = post_processing(valid_toc_items, len(page_list))
    tasks = [process_large_node_recursively(node, page_list, opt, logger=logger) for node in toc_tree]
    await asyncio.gather(*tasks)
    return toc_tree

def page_index_main(doc, opt=None):
    logger = JsonLogger(doc)
    is_valid_pdf = (
        (isinstance(doc, str) and os.path.isfile(doc) and doc.lower().endswith(".pdf")) or 
        isinstance(doc, BytesIO)
    )
    if not is_valid_pdf:
        raise ValueError("Unsupported input type. Expected a PDF file path or BytesIO object.")

    print('Parsing PDF...')
    page_list = get_page_tokens(doc)
    
    # 检查是否成功读取
    if not page_list:
        print("[CRITICAL] No text extracted from PDF. Check if pdfplumber is installed and file is valid.")
        return {"error": "PDF extraction failed"}

    logger.info({'total_page_number': len(page_list)})
    logger.info({'total_token': sum([page[1] for page in page_list])})

    async def page_index_builder():
        structure = []
        doc_description = ""
        
        try:
            # 1. Parse Structure
            structure = await tree_parser(page_list, opt, doc=doc, logger=logger)
            
            # 2. Add Node IDs
            if opt.if_add_node_id == 'yes':
                write_node_id(structure)    
            
            # 3. Add Full Text
            if opt.if_add_node_text == 'yes' or opt.if_add_node_summary == 'yes':
                add_node_text(structure, page_list)
            
            # 4. Add Summaries (Robust Version)
            if opt.if_add_node_summary == 'yes':
                print("Generating summaries... (throttled for robust API usage)")
                init_node_fields(structure)
                try:
                    await generate_summaries_for_structure(structure, model=opt.model)
                except Exception as e:
                    print(f"[ERROR] Summary generation failed: {e}")

            # 5. Generate Document Description (Robust Version)
            if opt.if_add_doc_description == 'yes':
                 print("Generating document description...")
                 doc_description = await generate_document_description(page_list, model=opt.model)

        except Exception as e:
            print(f"\n[CRITICAL ERROR] Process interrupted: {e}")
            print("[INFO] Attempting to save partial results...")
            import traceback
            traceback.print_exc()
        
        finally:
            # === EMERGENCY SAVE BLOCK ===
            # 强制保存，防止白跑
            final_data = {
                "doc_name": get_pdf_name(doc),
                "doc_description": doc_description if doc_description else "Description failed or skipped.",
                "structure": structure if structure else [{"title": "Extraction Failed / Empty", "nodes": []}]
            }

            pdf_name = get_pdf_name(doc)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            full_save_path = os.path.join("results", f"{pdf_name}_{timestamp}.json")
            os.makedirs("results", exist_ok=True)
            
            try:
                with open(full_save_path, 'w', encoding='utf-8-sig') as f:
                    json.dump(final_data, f, ensure_ascii=False, indent=2)
                print(f"\n[SUCCESS] Data Saved (Complete or Partial): {os.path.abspath(full_save_path)}")
            except Exception as e:
                print(f"[ERROR] Failed to save result file: {e}")

            if opt.if_add_node_text == 'no':
                 remove_structure_text(final_data['structure'])
            
            return final_data  

    return asyncio.run(page_index_builder())

def page_index(doc, model=None, toc_check_page_num=None, max_page_num_each_node=None, max_token_num_each_node=None,
               if_add_node_id=None, if_add_node_summary=None, if_add_doc_description=None, if_add_node_text=None):
    user_opt = {
        arg: value for arg, value in locals().items()
        if arg != "doc" and value is not None
    }
    opt = ConfigLoader().load(user_opt)
    return page_index_main(doc, opt)

def validate_and_truncate_physical_indices(toc_with_page_number, page_list_length, start_index=1, logger=None):
    if not toc_with_page_number:
        return toc_with_page_number
    max_allowed_page = page_list_length + start_index - 1
    truncated_items = []
    for i, item in enumerate(toc_with_page_number):
        if item.get('physical_index') is not None:
            try:
                original_index = int(item['physical_index'])
                if original_index > max_allowed_page:
                    item['physical_index'] = None
                    truncated_items.append({
                        'title': item.get('title', 'Unknown'),
                        'original_index': original_index
                    })
            except:
                item['physical_index'] = None
    if truncated_items and logger:
        logger.info(f"Total removed items: {len(truncated_items)}")
    print(f"Document validation: {page_list_length} pages, max allowed index: {max_allowed_page}")
    if truncated_items:
        print(f"Truncated {len(truncated_items)} TOC items that exceeded document length")
    return toc_with_page_number
