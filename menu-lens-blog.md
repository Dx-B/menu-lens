# menu-lens: Building a Real-World AI Menu Extraction Pipeline

## A Technical Dev Log

This document records findings from building menu-lens — a multilingual AI menu reader that extracts, structures, and translates restaurant menus from images. Each finding is documented as it happened, with the specific data, errors, and decisions that produced it.

This is a living document. New findings are appended as the project develops.

---

## Finding 1 — Token limits truncate dense menus

**What happened:**
The first test run used `max_tokens=1024` on a single API call against the Edison's diner menu — a dense, multi-column, photo-heavy single-page menu. The JSON response truncated mid-string. The exact cutoff point was inside the `failure_category` field of the "Very Chocolate Pancakes" entry, ending with the partial string `"failure'` before the response was cut off entirely.

**What it means:**
Vision responses on dense, image-heavy menus consume significantly more tokens than equivalent text prompts. A menu image alone accounts for roughly 1,500-1,600 input tokens before any output is generated. The model needs room to describe every item, price, and description across potentially 100+ line items.

**Fix:** Bumped `max_tokens` to 4096 as a first step. Later architectural work (sectioned extraction) addressed the root problem more fundamentally.

**Note:** Specific error output and exact truncation point — scroll to early conversation for verbatim data.

---

## Finding 2 — Self-reported failure categories as a quality signal

**What happened:**
Added a `failure_category` field to the extraction prompt, asking the model to self-report when it couldn't read something — values like `"unreadable"`, `"glare"`, `"partial"`. Found that null prices correlated almost perfectly with non-null failure categories. Items where the model reported `"none"` in failure_category almost always had valid prices.

**What it means:**
You can get a cheap quality signal on extraction confidence without a second validation API call. The model's self-assessment of its own extraction difficulty is a usable proxy for actual extraction accuracy.

**Note:** Specific correlation data from the early test runs — scroll to early conversation.

---

## Finding 3 — Vision API costs scale non-linearly

**What happened:**
Measured cost across menu types as the project developed. A simple single-column menu (Terzo restaurant) cost approximately $0.004 for the full extraction. The dense Edison's diner menu cost $0.226 — roughly 56x more expensive for a menu that's maybe 4-5x more complex visually.

**What it means:**
Cost doesn't scale linearly with menu complexity. Image token count, section count, and items per section all compound. A naive implementation that calls the API on every user interaction is commercially unviable at scale. Caching is an architectural decision, not an optimization afterthought.

---

## Finding 4 — Menus are designed for human visual parsing

**What happened:**
The Edison's diner menu had food photographs embedded directly in the menu layout — the Red Velvet Pancakes and Very Chocolate Pancakes entries had promotional photos sitting between the item name and the price. The model correctly identified the items but returned null prices because the photo visually interrupted the text flow.

**What it means:**
Real menus use spatial relationships, color, photography, and typography as organizational tools that don't survive flattening to text. The hard problem isn't OCR — it's reconstructing semantic structure from visually encoded information. A human reads the photo as decoration and finds the price elsewhere on the line. The model loses the spatial relationship.

---

## Finding 5 — Orphaned modifiers as standalone items

**What happened:**
On the Fruits & Juices section of the Edison's menu, "Small" appeared as a standalone menu item with a price of $5.95. It's clearly a size option for one of the juice items — but it appeared on its own line with its own price in the source menu, so the model extracted it as an independent item.

**What it means:**
Line-item extraction without semantic context awareness creates nonsensical standalone entries. The model sees a line with a price and extracts it as an item. A human sees "Small" and immediately understands it's a modifier. This is a fundamental challenge for any ordering system — you can't let a customer "order a Small."

---

## Finding 6 — Even 4096 output tokens can't complete a dense menu

**What happened:**
After bumping to 4096 max_tokens, ran the Edison's menu again. The extraction still didn't complete. The response cut off partway through the omelettes section, leaving the bottom third of the menu unextracted. The JSON was syntactically valid up to the cutoff point but structurally incomplete.

**What it means:**
A single-call implementation fundamentally cannot handle real-world menu complexity. The Edison's menu has approximately 100 line items across 19 sections. At roughly 40-50 tokens per structured JSON item, that's 4,000-5,000 output tokens minimum — before accounting for formatting, descriptions, and abnormality fields. This finding was the direct motivation for the sectioned extraction architecture.

---

## Finding 7 — Null prices aren't always failures

**What happened:**
Tested against the Terzo restaurant menu — a clean, single-column menu with elegant typography. Every single item returned `null` for price. Initial assumption was extraction failure. Looking at the image, the menu has no prices at all — it's a prix fixe event menu where everything is included.

**What it means:**
Null price needs context to be meaningful. The difference between "price exists but is unreadable" and "price genuinely not on this menu" is semantically important for a downstream ordering system. Added a `price_status` field to the prompt with explicit values: `listed`, `not_on_menu`, `unreadable`, `partial`.

---

## Finding 8 — Cost transparency requires estimation before the call

**What happened:**
Early version of the pipeline showed cost after the API call completed. This is useless as a protection mechanism — the tokens are already spent. Built a pre-call estimation system using the `client.messages.count_tokens()` endpoint, which counts input tokens exactly before sending.

**What it means:**
Input cost is calculable exactly before any API call. Output cost requires a worst-case estimate using `max_tokens` as the ceiling. Presenting both as a range gives honest uncertainty bounds. The UI shows: `$0.0049 (Lower Limit) - $0.2449 (Upper Limit)` before asking for confirmation.

---

## Finding 9 — Cost gate must precede the API call

**What happened:**
During refactoring, noticed the cost estimation block was placed after the API call in the code flow. The cost check ran, showed the estimate, asked for confirmation — but the call had already happened. The confirmation prompt was theater.

**What it means:**
The ordering of operations matters as much as the logic. A cost gate that fires after the spend provides zero protection. The API call must be inside the confirmation branch, not before it.

---

## Finding 10 — Centralized config flags

**What happened:**
As the pipeline grew, behavioral flags were scattered through the code. Toggling between development and production behavior required hunting through multiple functions. Centralized all flags at the top of the file: `SHOW_THINKING`, `COST_MODE`, `USE_MULTITHREADING`, `MOCK_PHASE_1`, `MOCK_PHASE_2`, `GLOBAL_OUTPUT_TOKEN_BUDGET`.

**What it means:**
A single control surface for all behavioral switches is the precursor to proper environment-based configuration. In production this becomes environment variables. During development it's readable flags at the top of the file. Changing one variable should change one behavior — no hunting required.

---

## Finding 11 — Raw response logging before parsing

**What happened:**
Hit a JSON parsing failure on a successful API call. The call cost tokens, the response arrived, but the parsing crashed — and the response was gone. Built a pattern of always writing the raw response to `raw_output.txt` before attempting any parsing.

**What it means:**
No successful API call should ever be lost to a downstream parsing failure. The raw file becomes both a debugging artifact and a free cache — you can re-run parsing logic against it without hitting the API again.

---

## Finding 12 — Flat structure outperforms nested for downstream use

**What happened:**
Initial design used nested JSON with categories containing item arrays. Tested both against the downstream use cases — cart implementation, database storage, translation layer. In every case the flat structure (each item carries its own category field) was simpler to work with.

**What it means:**
Nested structure feels more natural but creates work downstream. Flat items with category fields map directly to database rows, are easier to iterate for translation, and simpler to filter for cart display. Groups can be reconstructed from flat data in one line when needed for display. The reverse — flattening nested data — is consistently more work.

---

## Finding 13 — Mutable global params cause accumulation bugs

**What happened:**
The `extract_section` function was appending a text block to `extract_params["messages"][0]["content"]` directly. On the second section call, the params already had the first section's prompt. Third call had two old prompts. By call 10, Claude was seeing 9 previous section prompts alongside the current one.

**What it means:**
Shared mutable state inside functions that run repeatedly — or will eventually run in parallel — is a silent failure mode. The output looks plausible but is wrong. Fix: `copy.deepcopy(extract_params)` at the top of every `extract_section` call creates a fully isolated copy. This also sets up parallel execution correctly — each thread gets its own isolated params object.

---

## Finding 14 — Sequential multi-agent latency is unacceptable

**What happened:**
With the sectioned extraction architecture working sequentially, timed the Edison's menu run. 19 sections, each section call taking 5-7 seconds. Total wall clock time: approximately 100 seconds — measured with a stopwatch on a real run.

Console output showed each section completing one by one:
```
Local Agent Token Usage: Input: 1642 Output: 477 Total: 2119 IFC: $0.012
Local Agent Token Usage: Input: 1644 Output: 572 Total: 2216 IFC: $0.014
...
```

**What it means:**
100 seconds is unusable for a real application. A user pointing their phone at a menu in a restaurant needs a response in seconds, not two minutes. This was the direct motivation for parallel execution.

---

## Finding 15 — Parallelism saves time, not money

**What happened:**
Implemented ThreadPoolExecutor with max_workers=10 for the section extraction calls. Benchmarked before and after:

- Sequential: ~140 seconds (full measured run)
- Parallel: ~26 seconds (stopwatch measured)
- Latency reduction: ~81%
- Cost sequential: $0.225612
- Cost parallel: $0.226391
- Cost difference: essentially zero

Examined the per-call token counts to understand why cost didn't change:
```
Local Agent Token Usage: Input: 1646 Output: 477
Local Agent Token Usage: Input: 1644 Output: 572
Local Agent Token Usage: Input: 1643 Output: 129
```

Input tokens nearly identical across all 19 calls (~1,640 each). The image costs the same tokens regardless of which section you're asking about.

**What it means:**
Parallelism is purely a latency optimization. Each section call sends the full image regardless. Total tokens = sections × per-call tokens. Whether you send them sequentially or simultaneously doesn't change that product. This is a critical insight for cost modeling — parallel execution doesn't make the product cheaper.

---

## Finding 16 — Section boundary bleed

**What happened:**
In the translated output, "Belgian Waffle and 4pcs Chicken" appeared twice — once under "Crispy Belgian Waffles" and once under "Cinnamon-Swirl French Toast." The item appears near the physical boundary between those two sections on the menu. The model saw it in both contexts and extracted it into both.

**What it means:**
The model makes extraction decisions based on local context within each section call. Items near section boundaries are ambiguous — they could belong to either adjacent section. Production systems need a deduplication pass after parallel extraction, keyed on item name, before writing the final output.

---

## Finding 17 — Orphaned modifiers confirmed at scale

**What happened:**
In the full Edison's menu extraction, "Served with Butter and Warm Syrup" appeared as a standalone item with price "included" under the Cinnamon-Swirl French Toast category. This is a serving description, not a menu item. It appeared on its own line in the source menu — so the model extracted it as an item.

This confirmed Finding 5 at scale. The Edison's menu has dozens of modifier-style lines mixed with actual items. Each one is a potential false positive.

**What it means:**
The orphaned modifier problem compounds with menu complexity. A simple prix fixe menu has few modifiers. A dense diner menu has dozens. Any ordering system built on this extraction needs a semantic filter — something that identifies whether an extracted item is actually orderable or is a description, modifier, or serving note.

---

## Finding 18 — Semantic errors a human catches immediately

**What happened:**
In the Egg Platters & Omelettes section extraction, "Cinnamon Roll" appeared as a menu item priced at $13.95 with description "Served with Cream Cheese." This is almost certainly a misread — either a different item entirely or a visual bleed from an adjacent section. No diner puts a cinnamon roll under egg platters.

Conversely, the Specialty Omelettes section — 7 items, single column, clean typography, no embedded food photos — extracted nearly perfectly. All 7 items, correct prices, clean descriptions, zero abnormalities.

**What it means:**
Model performance isn't uniform. It correlates directly with layout quality. Dense, visually complex sections produce semantic errors regardless of model capability. Clean, well-structured sections produce near-perfect extraction. This is the core argument for OpenCV preprocessing — normalizing image quality before extraction addresses more failure cases than prompt engineering.

---

## Finding 19 — Unicode requires explicit configuration

**What happened:**
First translated output contained corrupted characters: "Jalape\u00f1o" instead of "Jalapeño", "Peque\u00f1o" instead of "Pequeño". Python's `json.dump` escapes non-ASCII characters by default.

Also encountered a `UnicodeDecodeError` when reading back a file written without explicit encoding — `'utf-8' codec can't decode byte 0xf1 in position 20175`. The system locale had written the file in a different encoding.

**Fix:** Two changes required:
```python
json.dump(output, f, indent=2, ensure_ascii=False)  # write
open(cache, "r", encoding="utf-8")  # read
```

**What it means:**
Multilingual output requires explicit encoding configuration at every file boundary. Default behavior is wrong for this use case. The fix is simple but the failure is silent — you get plausible-looking output with corrupted characters rather than an obvious error.

---

## Finding 20 — Layout quality is the strongest predictor of extraction accuracy

**What happened:**
Across multiple menu tests, the Specialty Omelettes section consistently produced better output than any other section of the Edison's menu. Examining why: it's the only section that's single-column, has no embedded food photos, uses consistent typography, and has clear price formatting with dot leaders.

The same model that produced "Cinnamon Roll under Egg Platters" and "Small" as a $5.95 item extracted 7 specialty omelettes perfectly — correct names, correct prices, complete descriptions, no abnormalities.

**What it means:**
The bottleneck isn't model capability. It's input quality. A preprocessing pipeline that normalizes image quality — perspective correction, shadow removal, adaptive thresholding — would have a larger impact on extraction accuracy than any amount of prompt engineering. This is the argument for OpenCV as a preprocessing layer before the API call, not as an alternative to the API call.

---

## Finding 21 — Parallel extraction: 81% latency reduction, zero cost change

**What happened:**
Formal benchmark after implementing ThreadPoolExecutor:

**With multithreading disabled:**
- Phase 1: ~12 seconds
- Phase 2: 2 minutes 20 seconds (140 seconds)
- Total: ~152 seconds

**With multithreading enabled:**
- Phase 1: ~12 seconds (unchanged — single sequential call)
- Phase 2: ~26 seconds
- Total: ~38 seconds

Cost comparison:
- Sequential total: $0.225612
- Parallel total: $0.226391
- Difference: $0.000779 (noise level)

Per-call token usage was nearly identical across all 19 parallel calls:
```
Input: 1639-1647 tokens per call (variance of ~8 tokens)
Output: 107-862 tokens per call (varies by section size)
```

**What it means:**
The image costs approximately 1,600 tokens regardless of which section you're extracting. Parallelism doesn't reduce that cost — it just stops you from paying it sequentially. The 81% latency reduction makes the product usable. The cost structure remains unchanged.

---

## Finding 22 — Non-determinism in section discovery

**What happened:**
Ran the same Edison's menu image through Stage 1 (section discovery) twice in the same session with identical parameters. First run returned 19 sections. Second run returned 18 sections. The missing section was a minor menu subdivision that the model treated as a subsection in one run and an independent category in another.

Console output from two runs:
- Run 1: `Total Sub-Agent Token Usage: ... TOTAL: 38820`
- Run 2: Different section count, different total

**What it means:**
LLM outputs are non-deterministic even at temperature=0 due to floating point variance in GPU computation. Production systems cannot assume consistent section counts across runs on the same menu. Downstream logic needs:
1. Deduplication by item name before writing final output
2. Validation that extracted item count is plausible given section item_count estimates
3. Idempotency — running the same menu twice should produce the same final output

---

## Finding 23 — Two-phase caching is architecturally necessary

**What happened:**
Development workflow before caching: every time we wanted to test the output format, the translation layer, or the cost reporting, we had to re-run the full extraction. Phase 1 alone costs ~$0.02. Phase 2 costs ~$0.21. Testing a one-line change to the JSON output structure was costing $0.23 per attempt.

Implemented independent cache flags:
- `MOCK_PHASE_1` — load section discovery from `phase1_cache.json`
- `MOCK_PHASE_2` — load item extraction from `phase2_cache.json`

With both enabled, iterating on translation logic, output formatting, or cost reporting costs zero.

**What it means:**
The two phases have different cost profiles and different development iteration rates. Phase 1 (cheap, fast) changes rarely — you only need to re-run it when testing a new menu or changing the section discovery prompt. Phase 2 (expensive, slow) also changes rarely once it's working. Everything downstream — translation, output formatting, cart logic — iterates constantly. Caching at the phase boundary, not just at the final output, is the correct architectural decision.

---

## Finding 24 — Cognitive complexity is a real signal

**What happened:**
Windsurf (the IDE) flagged `process_data` with a cognitive complexity warning. The function at that point was handling: type checking (API response vs cached dict), Phase 1 response parsing, raw file logging, JSON parsing, Phase 2 orchestration, Phase 2 cache writing, output file writing, and cost summary printing.

Refactored into focused functions:
- `run_phase2(menu_data)` → extraction or cache load, returns all_items
- `write_output(all_items)` → file writing
- `print_costs(response)` → cost summary

After the refactor, discovered a bug that had been invisible: `write_output` was being called with `menu_data` instead of `all_items`. The output file was writing section headers instead of extracted items. The bug existed in the previous version but was hidden inside the complex function.

**What it means:**
High cognitive complexity in pipeline code correlates with hidden bugs. The refactor didn't add functionality — it made the data flow visible. A function that does seven things has seven places to make a mistake, and those mistakes are hard to see when everything is entangled. The Windsurf warning was accurate.

---

## Finding 25 — Translation layer works as distinct Phase 3

**What happened:**
Implemented Phase 3 as a parallel pass over the Phase 2 cache. Each item in `phase2_cache.json` gets an independent translation call with a text-only prompt (no image). Results:

- Successful translations were culturally accurate: "Eggs Benedict" → "Huevos Benedict", "Crispy Belgian Waffle" → "Gofre Belga Crujiente"
- The Jalapeño handling worked correctly: preserved the character, translated contextually
- Rate limiting triggered: `Error code: 429 - rate limit of 50 requests per minute` on the Edison's 90+ item menu
- Failed calls returned `[]` which polluted the output list

**Fixes applied:**
1. Filter empty arrays post-parallel: `translated_items = [item for item in translated_items if item]`
2. Add `encoding="utf-8"` to all file reads and writes in the translation path
3. Rate limit handling needs retry with backoff (still on roadmap)

**Cost data not yet captured for Phase 3 specifically** — needs a dedicated benchmark run.

**What it means:**
Translation as a distinct phase with its own cache produces clean separation of concerns. The English extraction is stable. The translation is independently iterable. Different languages can be produced from the same Phase 2 cache without re-running extraction.

---

## Finding 26 — Parallel translation produces inconsistent category names

**What happened:**
Examining `translated_output.json` found the same English category "Crispy Belgian Waffles" translated two different ways:
- "Waffles Belgas Crujientes" (items extracted in one parallel call)
- "Gofres Belgas Crujientes" (items extracted in a different parallel call)

Both are valid Spanish translations. The model made different but equally correct choices in different parallel contexts.

**What it means:**
When each item's category field is translated independently in parallel, there's no coordination between calls. The model has no knowledge of what other calls translated the same category as. A menu with 10 items in the "Crispy Belgian Waffles" section could produce 10 different Spanish category names if the parallel calls happen to make different choices.

**Fix (on roadmap):**
1. Extract unique English category names from Phase 2 cache
2. Translate them once in a single batch call
3. Build a lookup dict: `{"Crispy Belgian Waffles": "Gofres Belgas Crujientes"}`
4. Apply lookup dict to all items before writing translated output

This ensures category consistency across the entire translated menu without additional API calls beyond the initial batch.

---

## What's Next

Active roadmap items in priority order:

1. **Category name normalization** — translate unique categories once, apply as lookup (addresses Finding 26)
2. **Retry logic with backoff** — handle 429 rate limit errors in Phase 3 (addresses Finding 25)
3. **Deduplication** — filter duplicate items from section boundary bleed (addresses Finding 16)
4. **OpenCV preprocessing** — perspective correction, shadow removal before API call (addresses Finding 20)
5. **FastAPI backend** — wrap pipeline as HTTP endpoint accepting image upload
6. **Minimal frontend** — React UI for image upload and menu display
7. **Evaluation framework** — systematic benchmarking across menu types

---

*This document is updated as new findings are discovered. Current finding count: 26.*
