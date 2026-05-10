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

# //////////////////////////////////////////////////////////////////////// Setup

# Global Variables
SHOW_THINKING = False # Off, currently disfunctional.
COST_MODE = True # On by default. Outputs the cost range of an API call before proceeding with data parsing. Disabling this skips verification entirely. (useful for batch calls but watch API usage)
# Note about COST_MODE: By design, output values cannot be obtained until after an API request is sent and an output received. The Upper Limit is your token budget so you can confirm your API call before sending.

USE_MULTITHREADING = True # On by default. Change this to True if you have to use multiple threads and want to take advantage of parallel processing.
GLOBAL_OUTPUT_TOKEN_BUDGET = 16000 # Default 16000. Change this based on your token budget for total API calls. Large, complicated menus will burn through this.
GLOBAL_THINKING_TOKEN_BUDGET = 8000 # Default 8000. Change this based on how many tokens you want to dedicate to Claude thinking. Useful for seeing Claude's thoughts but will burn through your token budget.


# Minor Variables
output_dir = "output"
os.makedirs(output_dir, exist_ok=True)
OUTPUT_FILE = "output.json"
RAW_OUTPUT_FILE = "raw_output.txt"
TRANSLATED_OUTPUT = "translated_output.json"

TRANSLATE_TO_LANGUAGE = "Spanish"
MOCK_PHASE_1 = False # True = Read from Cache Mode, False = API call directly
MOCK_PHASE_2 = False # True = Read from Cache Mode, False = API call directly
PHASE1_CACHE = "output/phase1_cache.json"
PHASE2_CACHE = "output/phase2_cache.json"

GLOBAL_COST = 0
GLOBAL_AGENT_TOKEN_INPUT_COST = 0
GLOBAL_AGENT_TOKEN_OUTPUT_COST = 0
GLOBAL_AGENT_TOTAL_TOKEN_COST = 0
GLOBAL_AGENT_INTERNAL_FINAL_COST = 0

# Sonnet pricing as of 2025 https://www.anthropic.com/pricing. Each parameter is multiplied by 1,000,000. Example: 3.00 is $3 per million tokens.
INPUT_COST_PER_MILLION = 3.00
OUTPUT_COST_PER_MILLION = 15.00

# Load the image
with open("menu.jpg", "rb") as f:
    image_data = base64.standard_b64encode(f.read()).decode("utf-8")

# Create client
client = anthropic.Anthropic()

# ////////////////////////////////////////////////////////////////////////

# //////////////////////////////////////////////////////////////////////// Request Bodies

# Retrieves the section headers and corresponding item counts. INPUT: menu.jpg, client OUTPUT: dict (key = section name, value = item count)
request_params = {
    "model": "claude-sonnet-4-6",
    "max_tokens": GLOBAL_OUTPUT_TOKEN_BUDGET if SHOW_THINKING else 4096,
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

extract_params = {
    "model": "claude-sonnet-4-6",
    "max_tokens": GLOBAL_OUTPUT_TOKEN_BUDGET if SHOW_THINKING else 4096,
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

base_params = {
    "model": "claude-sonnet-4-6",
    "max_tokens": GLOBAL_OUTPUT_TOKEN_BUDGET if SHOW_THINKING else 4096,
}

cost_params = {
    "model": request_params["model"],
    "messages": request_params["messages"]
}

if SHOW_THINKING:
    request_params["thinking"] = {
        "type": "enabled",
        "budget_tokens": GLOBAL_THINKING_TOKEN_BUDGET
    }

# ////////////////////////////////////////////////////////////////////////

# //////////////////////////////////////////////////////////////////////// Data Output and Cost Estimation



# //////////////////////////////////////////////////////////////////////// Helper Functions
def clean_json_response(raw):
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()

def add_global_cost(cost):
    global GLOBAL_COST
    with cost_lock:
        GLOBAL_COST += cost

def estimate_cost(input_tokens, output_tokens): # Calculate API Usage Cost
    input_cost = (input_tokens / 1_000_000) * INPUT_COST_PER_MILLION
    output_cost = (output_tokens / 1_000_000) * OUTPUT_COST_PER_MILLION
    return input_cost + output_cost

def estimate_input_cost(input_tokens): # Calculate API Usage Cost
    input_cost = (input_tokens / 1_000_000) * INPUT_COST_PER_MILLION
    return input_cost

def add_agent_cost(input_tokens, output_tokens, total, ifc):
    global GLOBAL_AGENT_TOTAL_TOKEN_COST
    global GLOBAL_AGENT_TOKEN_INPUT_COST
    global GLOBAL_AGENT_TOKEN_OUTPUT_COST
    global GLOBAL_AGENT_INTERNAL_FINAL_COST
    with cost_lock:
        GLOBAL_AGENT_TOKEN_INPUT_COST += input_tokens
        GLOBAL_AGENT_TOKEN_OUTPUT_COST += output_tokens
        GLOBAL_AGENT_TOTAL_TOKEN_COST += total
        GLOBAL_AGENT_INTERNAL_FINAL_COST += ifc

# //////////////////////////////////////////////////////////////////////// Main Functions

# //////////////////////////////////////////////////////////////////////// Phase 2: Multi-threaded Section Population
def run_phase2(menu_data):
    all_items = []

    if MOCK_PHASE_2:
        try:
            with open(PHASE2_CACHE, "r") as f:
                all_items = json.load(f)
            print("Phase 2: Parallel Section Extraction -- Read from Cache Mode Enabled (MOCK_PHASE_2 = True)")
        except FileNotFoundError:
            print(f"Phase 2: Parallel Section Extraction --  Cache not found. Populate with the API first. MOCK_PHASE_2 = False to use the API. [Failed to find {PHASE2_CACHE} at {os.path.abspath(PHASE2_CACHE)}].")
            exit()
    else:
        print(f"Stage 2: Parallel Section Extraction | Multithreading: {USE_MULTITHREADING}")
        if USE_MULTITHREADING:
            # Parallel
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = {
                    executor.submit(extract_section, section["name"], section["item_count"]) : section
                    for section in menu_data
                }
                for future in as_completed(futures):
                    items = future.result()
                    all_items.extend(items)
        else:
            # Iterator, This should never be used unless directly testing for time comparison.
            for section in menu_data:
                items = extract_section(section["name"], section["item_count"])
                all_items.extend(items)
        print(f"Total Sub-Agent Token Usage: Input: {GLOBAL_AGENT_TOKEN_INPUT_COST} OUTPUT: {GLOBAL_AGENT_TOKEN_OUTPUT_COST} TOTAL: {GLOBAL_AGENT_TOTAL_TOKEN_COST} IFC: $ {GLOBAL_AGENT_INTERNAL_FINAL_COST}")

    return all_items


# //////////////////////////////////////////////////////////////////////// Phase 3: Translation
def translate(language, untranslated_items, input_dict): # Retrieves the input section items into a dictionary. INPUT: sections dict (section name, item count? as a expected length), menu.jpg, client OUTPUT: JSON
    # Deep copy so we don't mutate the global
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

        print(f"Local Translator Agent Token Usage: Input: {response.usage.input_tokens} Output:  {response.usage.output_tokens} Total:  {response.usage.input_tokens + response.usage.output_tokens} IFC: $ {estimate_cost(response.usage.input_tokens, response.usage.output_tokens)}")
        add_global_cost(estimate_cost(response.usage.input_tokens, response.usage.output_tokens))
        add_agent_cost(response.usage.input_tokens, response.usage.output_tokens, response.usage.input_tokens + response.usage.output_tokens, estimate_cost(response.usage.input_tokens, response.usage.output_tokens))
    
    except Exception as e:
        print(f"Phase 3 Error: Local Translator Agent: {e}") 
        return []
    
    translated_items = clean_json_response(response.content[0].text)
    
    return json.loads(translated_items)

def run_translator_phase(language, cache, input_dict):
    section_dict = input_dict
    translated_items = []
    try:
        with open(cache, "r", encoding="utf-8", errors="replace") as f:
            untranslated_items = json.load(f)
        print("Phase 3: Parallel Translation -- Cache Read Successful")
    except FileNotFoundError:
        print("Phase 3: Parallel Translation -- Cache not found. Populate with the API first. [Failed to find {cache} at {os.path.abspath(cache)}].")
        return []
    
    if USE_MULTITHREADING:
        print(f"Stage 3: Parallel Translation | Multithreading: {USE_MULTITHREADING}")
        # Parallel
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(translate, language, item, section_dict) : item
                for item in untranslated_items
            }
            for future in as_completed(futures):
                item = future.result()
                translated_items.append(item)
    else:
        # Iterator, This should never be used unless directly testing for time comparison. It doesn't even work.
        for item in untranslated_items:
            translated_items.append(translate(language, item, section_dict))

    # Clean any bad output in translated file such as rate-limited returned JSON.
    translated_items = [item for item in translated_items if item]
    
    return translated_items

def extract_translator_dict(cache, language):
    translated_dict = {}
    all_items = []
    try:
        with open(cache, "r", encoding="utf-8", errors="replace") as f:
            all_items = json.load(f)

    except FileNotFoundError:
        print("Phase 3: Parallel Translation -- Phase 2 Cache not found. Populate with the API first. [Failed to find {cache} at {os.path.abspath(cache)}].")
        return {}
    
    translated_dict = list(set(item["category"] for item in all_items if "category" in item))
    
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

        print(f"Local Category Dict Translator Agent Token Usage: Input: {response.usage.input_tokens} Output:  {response.usage.output_tokens} Total:  {response.usage.input_tokens + response.usage.output_tokens} IFC: $ {estimate_cost(response.usage.input_tokens, response.usage.output_tokens)}")
        add_global_cost(estimate_cost(response.usage.input_tokens, response.usage.output_tokens))
        add_agent_cost(response.usage.input_tokens, response.usage.output_tokens, response.usage.input_tokens + response.usage.output_tokens, estimate_cost(response.usage.input_tokens, response.usage.output_tokens))
    
    except Exception as e:
        print(f"Phase 3 Error: Local Section Translator Agent: {e}") 
        return {}

    translated_dict = json.loads(clean_json_response(response.content[0].text))

    print("Phase 3: Parallel Translation -- Translated Dict Write Successful")
    return translated_dict


# //////////////////////////////////////////////////////////////////////// Phase finish: Output
def write_output(all_items):
    output = {
        "all_items": all_items,
        "usage": {
            "total_cost": GLOBAL_COST
        }
    }

    # After all_items is populated, before writing output.json (Creates the Cache)
    if not MOCK_PHASE_2:
        with open(PHASE2_CACHE, "w", encoding="utf-8") as f:
            json.dump(all_items, f, indent=2, ensure_ascii=False)

    # Writes the section dict before passing into the translator
    translated_sections_dict = extract_translator_dict(PHASE2_CACHE, language=TRANSLATE_TO_LANGUAGE)

    # Write translated items
    with open(os.path.join(output_dir, TRANSLATED_OUTPUT), "w", encoding="utf-8") as f:
        json.dump(run_translator_phase(TRANSLATE_TO_LANGUAGE, PHASE2_CACHE, translated_sections_dict), f, indent=2, ensure_ascii=False)
    
    # Write the output file to the output directory
    with open(os.path.join(output_dir, OUTPUT_FILE), "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
        
    message = (
        f"READ CACHE MODE ENABLED: Phase 1 Output created in {os.path.abspath(OUTPUT_FILE)}"
        if MOCK_PHASE_1
        else f"READ CACHE MODE DISABLED: Cache for Phase 1 created and saved to {os.path.abspath(PHASE1_CACHE)}"
    )

    p2_message = (
        f"READ CACHE MODE ENABLED: Phase 2 Output created in {os.path.abspath(OUTPUT_FILE)}"
        if MOCK_PHASE_2
        else f"READ CACHE MODE DISABLED: Cache for Phase 2 created and saved to {os.path.abspath(PHASE2_CACHE)}"
    )

    print(f"\nSuccess.\n{message}\n{p2_message}\n")

def print_costs(response):
    if not isinstance(response, list):
        print("RAW Token Data:", response.usage)
        print("Program Total Cost")
        print("Input Tokens:", response.usage.input_tokens + GLOBAL_AGENT_TOKEN_INPUT_COST)
        print("Output Tokens:", response.usage.output_tokens + GLOBAL_AGENT_TOKEN_OUTPUT_COST)
        print("Total Tokens:", response.usage.input_tokens + response.usage.output_tokens + GLOBAL_AGENT_TOTAL_TOKEN_COST)
    print("Actual Cost (IFC): $", GLOBAL_COST)

# //////////////////////////////////////////////////////////////////////// Phase 1
def extract_section(section_name, expected_count): # Retrieves the input section items into a dictionary. INPUT: sections dict (section name, item count? as a expected length), menu.jpg, client OUTPUT: JSON
    # Deep copy so we don't mutate the global
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

        print(f"Local Agent Token Usage: Input: {response.usage.input_tokens} Output:  {response.usage.output_tokens} Total:  {response.usage.input_tokens + response.usage.output_tokens} IFC: $ {estimate_cost(response.usage.input_tokens, response.usage.output_tokens)}")
        add_global_cost(estimate_cost(response.usage.input_tokens, response.usage.output_tokens))
        add_agent_cost(response.usage.input_tokens, response.usage.output_tokens, response.usage.input_tokens + response.usage.output_tokens, estimate_cost(response.usage.input_tokens, response.usage.output_tokens))

        raw = clean_json_response(response.content[0].text)
        
        items = json.loads(raw)
        for item in items:
            item["category"] = section_name
        return items
    
    except Exception as e:
        print(f"Section '{section_name}' failed: {e}")
        return []

def process_data(response):

    # Type Check
    if isinstance(response, list):
        print("Phase 1: Section Discovery -- Read from Cache Mode Enabled (MOCK_PHASE_1 = True)")
        menu_data=response
    else:
        # Cost Analytics for first call
        print("Stage 1: Section Discovery -- Read from Cache Mode Disabled (MOCK_PHASE_1 = False)")
        print(f"Main Agent Token Usage: Input: {response.usage.input_tokens} OUTPUT: {response.usage.output_tokens} TOTAL: {response.usage.input_tokens + response.usage.output_tokens} IFC: $ {estimate_cost(response.usage.input_tokens, response.usage.output_tokens)}")
        add_global_cost(estimate_cost(response.usage.input_tokens, response.usage.output_tokens))

        # Always save raw response first
        raw = clean_json_response(response.content[0].text)
        with open(os.path.join(output_dir, RAW_OUTPUT_FILE), "w", encoding="utf-8") as f:
            f.write(raw)

        # parse response, log costs, save cache
        menu_data = json.loads(raw)
        with open(PHASE1_CACHE, "w") as f:
            json.dump(menu_data, f, indent=2)
    # Then try to parse
    try:
        all_items = run_phase2(menu_data)
        # Output JSON
        write_output(all_items)

    except json.JSONDecodeError as e:
        print(f"Parsing failed: {e}")
        print("Raw output saved to raw_output.txt for inspection")
    print_costs(response)

def populate_menu_data():
    if MOCK_PHASE_1:
        try:
            with open(PHASE1_CACHE, "r") as f:
                menu_data = json.load(f)
            process_data(menu_data)
        except FileNotFoundError:
            print(f"Phase 1 cache not found. Populate with the API first. MOCK_PHASE_1 = False to use the API. [Failed to find {PHASE1_CACHE} at {os.path.abspath(PHASE1_CACHE)}].")
            exit()
    else:
        response = client.messages.create(
            **request_params
        )
        process_data(response)

# //////////////////////////////////////////////////////////////////////// Main Thread

if COST_MODE:
    token_response = client.messages.count_tokens(
        **cost_params
    )
    estimated_input = token_response.input_tokens
    estimated_cost = estimate_cost(estimated_input, GLOBAL_OUTPUT_TOKEN_BUDGET)  # estimate output
    
    # print(f"Calculated input tokens: {estimated_input}")
    print(f"Estimated cost: ${estimate_input_cost(estimated_input):.4f} (Lower Limit) ({estimated_input} Tokens) - ${estimated_cost:.4f} (Upper Limit) ({GLOBAL_OUTPUT_TOKEN_BUDGET} Tokens)")
    
    print(f"Cache Mode: {MOCK_PHASE_1 or MOCK_PHASE_2} / P1 Cache Mode: {MOCK_PHASE_1} / P2 Cache Mode: {MOCK_PHASE_2}")
    confirm = input("Proceed? (y/n): ")
    if confirm.lower() != "y":
        print("Aborted.")
        exit()
    else:
        use_mock_p1 = input("Use Mock Phase 1? Y = Cache will be used, N = API will be used (y/n): ")
        if use_mock_p1.lower() == "y":
            MOCK_PHASE_1 = True
        else:
            MOCK_PHASE_1 = False
        use_mock_p2 = input("Use Mock Phase 2? Y = Cache will be used, N = API will be used (y/n): ")
        if use_mock_p2.lower() == "y":
            MOCK_PHASE_2 = True
            populate_menu_data()
        else:
            MOCK_PHASE_2 = False
            populate_menu_data()
else:
    populate_menu_data()

# ////////////////////////////////////////////////////////////////////////