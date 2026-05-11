# //////////////////////////////////////////////////////////////////////// Dotenv
from dotenv import load_dotenv
load_dotenv()

# //////////////////////////////////////////////////////////////////////// Primary Imports
import anthropic
import base64
import os

# //////////////////////////////////////////////////////////////////////// Helper Imports
import copy
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# //////////////////////////////////////////////////////////////////////// Helper Declarations
cost_lock = threading.Lock() # Parallel Race Condition Locking
client = anthropic.Anthropic()

# ////////////////////////////////////////////////////////////////////// Other Functions

def estimate_cost(input_tokens, output_tokens, config): # Calculate API Usage Cost
    input_cost = (input_tokens / 1_000_000) * config["INPUT_COST_PER_MILLION"]
    output_cost = (output_tokens / 1_000_000) * config["OUTPUT_COST_PER_MILLION"]
    return input_cost + output_cost

def clean_json_response(raw):
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()

def print_costs(response, state):
    if not isinstance(response, list):
        print("RAW Token Data:", response.usage)
        print("Program Total Cost")
        print("Input Tokens:", response.usage.input_tokens + state["GLOBAL_AGENT_TOKEN_INPUT_COST"])
        print("Output Tokens:", response.usage.output_tokens + state["GLOBAL_AGENT_TOKEN_OUTPUT_COST"])
        print("Total Tokens:", response.usage.input_tokens + response.usage.output_tokens + state["GLOBAL_AGENT_TOTAL_TOKEN_COST"])
    print("Actual Cost (IFC): $", state["GLOBAL_COST"])

# //////////////////////////////////////////////////////////////////////// Helper Functions

def translate(language, untranslated_items, input_dict, state, config): # Retrieves the input section items into a dictionary. INPUT: sections dict (section name, item count? as a expected length), menu.jpg, client OUTPUT: JSON
    # Deep copy so we don't mutate the global
    base_params = {
    "model": "claude-sonnet-4-6",
    "max_tokens": config["GLOBAL_OUTPUT_TOKEN_BUDGET"] if config["SHOW_THINKING"] else 4096,
    }

    local_params = copy.deepcopy(base_params)

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"Translate the following menu item into {language}. "
                        "Translate only the name and description fields. "
                        "You will be given an input dict with the following key format: key: 'untranslated category name', value: 'translated category name'."
                        "If the category field matches the key, replace it with the value. "
                        "Keep price and abnormalities exactly as they are. "
                        "Return only valid JSON representing a single item with fields: name, price, description, abnormalities, category. "
                        f"Item: {json.dumps(untranslated_items, ensure_ascii=False)}"
                        f"Input Dict: {json.dumps(input_dict, ensure_ascii=False)}"
                    )
                }
            ]
        }
    ]
    
    local_params["messages"] = messages
    
    try:
        response = client.messages.create(**local_params)

        print(f"Local Translator Agent Token Usage: Input: {response.usage.input_tokens} Output:  {response.usage.output_tokens} Total:  {response.usage.input_tokens + response.usage.output_tokens} IFC: $ {estimate_cost(response.usage.input_tokens, response.usage.output_tokens, config)}")
        state["GLOBAL_COST"] += estimate_cost(response.usage.input_tokens, response.usage.output_tokens, config)
        state["GLOBAL_AGENT_TOKEN_INPUT_COST"] += response.usage.input_tokens
        state["GLOBAL_AGENT_TOKEN_OUTPUT_COST"] += response.usage.output_tokens
        state["GLOBAL_AGENT_TOTAL_TOKEN_COST"] += response.usage.input_tokens + response.usage.output_tokens
    
    except Exception as e:
        print(f"Phase 3 Error: Local Translator Agent: {e}") 
        return []
    
    translated_items = clean_json_response(response.content[0].text)
    
    return json.loads(translated_items)

def run_translator_phase(language, transcribed_menu, input_dict, state, config):
    section_dict = input_dict
    untranslated_items = transcribed_menu
    translated_items = []
    
    if config["USE_MULTITHREADING"]:
        # Parallel
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(translate, language, item, section_dict, state, config) : item
                for item in untranslated_items
            }
            for future in as_completed(futures):
                item = future.result()
                translated_items.append(item)
    else:
        # Iterator, This should never be used unless directly testing for time comparison. It doesn't even work.
        for item in untranslated_items:
            translated_items.append(translate(language, item, section_dict, state, config))

    # Clean any bad output in translated file such as rate-limited returned JSON.
    translated_items = [item for item in translated_items if item]
    
    return translated_items

def phase_3_section_dict_extractor(untranslated_menu, language, state, config):
    translated_dict = untranslated_menu
    
    translated_dict = list(set(item["category"] for item in untranslated_menu if "category" in item))
    
    base_params = {
        "model": "claude-sonnet-4-6",
        "max_tokens": config["GLOBAL_OUTPUT_TOKEN_BUDGET"] if config["SHOW_THINKING"] else 4096,
    }


    local_params = copy.deepcopy(base_params)
    translate_section_parameters = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "You will receive a JSON array of menu category names in English. "
                        f"Translate the category fields to {language}. "
                        "Return only valid JSON representing a single python dict item with the value: 'The new translated category name' and key: 'The original untranslated category name'. "
                        f"Item: {json.dumps(translated_dict, ensure_ascii=False)}"
                    )
                }
            ]
        }
    ]
    
    local_params["messages"] = translate_section_parameters
    
    try:
        response = client.messages.create(**local_params)

        print(f"Local Category Dict Translator Agent Token Usage: Input: {response.usage.input_tokens} Output:  {response.usage.output_tokens} Total:  {response.usage.input_tokens + response.usage.output_tokens} IFC: $ {estimate_cost(response.usage.input_tokens, response.usage.output_tokens, config)}")
        state["GLOBAL_COST"] += estimate_cost(response.usage.input_tokens, response.usage.output_tokens, config)
        state["GLOBAL_AGENT_TOKEN_INPUT_COST"] += response.usage.input_tokens
        state["GLOBAL_AGENT_TOKEN_OUTPUT_COST"] += response.usage.output_tokens
        state["GLOBAL_AGENT_TOTAL_TOKEN_COST"] += response.usage.input_tokens + response.usage.output_tokens
    
    except Exception as e:
        print(f"Phase 3 Error: Local Section Translator Agent: {e}") 
        return {}

    translated_dict = json.loads(clean_json_response(response.content[0].text))

    print("Phase 3: Parallel Translation -- Translated Dict Write Successful")
    return translated_dict

def phase_2_extraction_helper(section_name, expected_count, state, config, image_data): # Retrieves the input section items into a dictionary. INPUT: sections dict (section name, item count? as a expected length), menu.jpg, client OUTPUT: JSON
    # Deep copy so we don't mutate the global

    extract_params = {
        "model": "claude-sonnet-4-6",
        "max_tokens": config["GLOBAL_OUTPUT_TOKEN_BUDGET"] if config["SHOW_THINKING"] else 4096,
        "messages": [
            {
                "role":"user",
                "content": [
                    {
                        "type":"image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_data,
                        },
                    },
                ],
            }
        ],
    }

    local_params = copy.deepcopy(extract_params)
    
    local_params["messages"][0]["content"].append({
        "type": "text",
        "text": (
            f"Return a JSON array of every item in the '{section_name}' category. "
            f"There should be approximately {expected_count} items. "
            "If the count differs or there are abnormalities, indicate them. "
            "Each element should have: \"name\", \"price\", \"description\", \"abnormalities\". "
            "Return only valid JSON, no other text."
        )
    })
    
    try:
        response = client.messages.create(**local_params)

        print(f"Local Agent Token Usage: Input: {response.usage.input_tokens} Output:  {response.usage.output_tokens} Total:  {response.usage.input_tokens + response.usage.output_tokens} IFC: $ {estimate_cost(response.usage.input_tokens, response.usage.output_tokens, config)}")
        state["GLOBAL_COST"] += estimate_cost(response.usage.input_tokens, response.usage.output_tokens, config)
        state["GLOBAL_AGENT_TOKEN_INPUT_COST"] += response.usage.input_tokens
        state["GLOBAL_AGENT_TOKEN_OUTPUT_COST"] += response.usage.output_tokens
        state["GLOBAL_AGENT_TOTAL_TOKEN_COST"] += response.usage.input_tokens + response.usage.output_tokens

        raw = clean_json_response(response.content[0].text)
        
        items = json.loads(raw)
        for item in items:
            item["category"] = section_name
        return items
    
    except Exception as e:
        print(f"Section '{section_name}' failed: {e}")
        return []

def phase_2_extractor(section_headers, state, config, image_data):
    all_items = []
    if config["USE_MULTITHREADING"]:
        # Parallel
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(phase_2_extraction_helper, section["name"], section["item_count"], state, config, image_data) : section
                for section in section_headers
            }
            for future in as_completed(futures):
                items = future.result()
                all_items.extend(items)
    else:
        # Iterator, This should never be used unless directly testing for time comparison.
        for section in section_headers:
            items = phase_2_extraction_helper(section["name"], section["item_count"], state, config, image_data)
            all_items.extend(items)
    print(f"Total Sub-Agent Token Usage: Input: {state["GLOBAL_AGENT_TOKEN_INPUT_COST"]} OUTPUT: {state["GLOBAL_AGENT_TOKEN_OUTPUT_COST"]} TOTAL: {state["GLOBAL_AGENT_TOTAL_TOKEN_COST"]} IFC: $ {state["GLOBAL_AGENT_INTERNAL_FINAL_COST"]}")

    return all_items

# //////////////////////////////////////////////////////////////////////// Main Functions

def phase3(state, config, transcribed_menu, language):
# Writes the section dict before passing into the translator
    translated_section_dict = phase_3_section_dict_extractor(transcribed_menu, language=config["TRANSLATE_TO_LANGUAGE"], state=state, config=config)
    return run_translator_phase(language, transcribed_menu, translated_section_dict, state, config)

def phase2(state, config, section_headers, image_data):
    transcribed_menu = []
    output = {
        "all_items": [],
        "usage": {
            "total_cost": 0
        }
    }
    try:
        transcribed_menu = phase_2_extractor(section_headers, state, config, image_data)
        output = {
            "all_items": transcribed_menu,
            "usage": {"total_cost": state["GLOBAL_COST"]}
        }
    except json.JSONDecodeError as e:
        print(f"Parsing failed: {e}")
    return output

def phase1(state, config, image_data):

    request_params = {
        "model": "claude-sonnet-4-6",
        "max_tokens": config["GLOBAL_OUTPUT_TOKEN_BUDGET"] if config["SHOW_THINKING"] else 4096,
        "messages": [
            {
                "role":"user",
                "content": [
                    {
                        "type":"image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "Return a JSON array of every menu category you can see. "
                            "Each element should have exactly these fields: "
                            "\"name\" (string), \"item_count\" (integer), \"abnormalities\" (string, either 'none' or a brief description). "
                            "Return only valid JSON, no other text."
                        )
                    }
                ],
            }
        ],
    }

    response = client.messages.create(
        **request_params
    )
    # Cost Analytics for first call
    print(f"Main Agent Token Usage: Input: {response.usage.input_tokens} OUTPUT: {response.usage.output_tokens} TOTAL: {response.usage.input_tokens + response.usage.output_tokens} IFC: $ {estimate_cost(response.usage.input_tokens, response.usage.output_tokens, config)}")
    state["GLOBAL_AGENT_TOTAL_TOKEN_COST"] += response.usage.input_tokens + response.usage.output_tokens
    state["GLOBAL_COST"] += estimate_cost(response.usage.input_tokens, response.usage.output_tokens,config)

    # Always save raw response first
    raw = clean_json_response(response.content[0].text)

    # parse response, log costs, save cache
    menu_data = json.loads(raw)

    print_costs(response, state)
    return menu_data

# //////////////////////////////////////////////////////////////////////// Run the Agent
def process_menu(image_bytes: bytes, config: dict = None) -> dict:
    image_data = base64.standard_b64encode(image_bytes).decode("utf-8")
    if config is None:
        config = {
            "TRANSLATE": False,
            "TRANSLATE_TO_LANGUAGE": "Spanish",
            "USE_MULTITHREADING": True,
            "GLOBAL_OUTPUT_TOKEN_BUDGET": 16000,
            "GLOBAL_THINKING_TOKEN_BUDGET": 8000,
            "COST_MODE": True,
            "SHOW_THINKING": False,

            "INPUT_COST_PER_MILLION": 3.00,
            "OUTPUT_COST_PER_MILLION": 15.00
        }

    # State accumulated during a run
    state = {
        "GLOBAL_COST": 0,
        "GLOBAL_AGENT_TOKEN_INPUT_COST": 0,
        "GLOBAL_AGENT_TOKEN_OUTPUT_COST": 0,
        "GLOBAL_AGENT_TOTAL_TOKEN_COST": 0,
        "GLOBAL_AGENT_INTERNAL_FINAL_COST": 0
    }

    print("Stage 1: Section Discovery")
    section_headers = phase1(state, config, image_data)
    print(f"Stage 2: Parallel Section Extraction | Multithreading: {config["USE_MULTITHREADING"]}")
    transcribed_menu = phase2(state, config, section_headers, image_data)

    print("\nSuccess.\n")

    # # Write translated items
    if config["TRANSLATE"]:
        print(f"Stage 3: Parallel Translation | Multithreading: {config["USE_MULTITHREADING"]}")
        return phase3(state, config, transcribed_menu, config["TRANSLATE_TO_LANGUAGE"])
    else:
        return transcribed_menu
