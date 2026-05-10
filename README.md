# menu-lens 🔍

> AI-powered menu extraction pipeline that transforms restaurant menus from raw images into structured, multilingual, interactive ordering experiences.

Built on Claude's vision API, menu-lens handles real-world menu complexity through multi-agent sectioned extraction, cost-aware API orchestration, and progressive quality benchmarking.

---

## How It Works

menu-lens uses a three-stage multi-agent pipeline:

**Stage 1 — Section Discovery**
A vision call identifies all menu categories and their approximate item counts, establishing the structure before any item extraction begins.

**Stage 2 — Parallel Section Extraction**
Each section is extracted in a targeted, isolated API call scoped to one category at a time. Runs in parallel using ThreadPoolExecutor for ~81% latency reduction over sequential execution.

**Stage 3 — Parallel Translation**
Extracted items are translated field by field in parallel using a text-only API call per item. Output is written to a language-specific file separate from the English cache.

```
Image → Stage 1: Section Discovery → Stage 2: Per-Section Extraction (×N parallel) → Stage 3: Translation (×N parallel) → Structured JSON
```

---

## Features

- **Multi-agent extraction** — section-scoped calls outperform single-call extraction on dense, complex menus
- **Parallel execution** — ThreadPoolExecutor across Stage 2 and Stage 3 with threading locks on shared cost globals
- **Two-phase independent caching** — Phase 1 and Phase 2 cache flags are independent, allowing iteration on translation and output logic without re-running extraction
- **Cost estimation gate** — calculates and displays API cost range before any spend, with confirmation prompt
- **Full cost accounting** — per-call and aggregate token usage tracked across all agents
- **JSON cleaning** — handles markdown fence stripping from model responses automatically
- **Configurable modes** — `COST_MODE`, `MOCK_PHASE_1`, `MOCK_PHASE_2`, `USE_MULTITHREADING`, `SHOW_THINKING` flags
- **Raw response backup** — every API response saved to disk before parsing
- **Abnormality detection** — model self-reports extraction issues inline
- **Multilingual output** — Phase 3 translation produces language-specific output files

---

## Findings

Real-world findings from building this pipeline, documented for the accompanying blog post series.

| # | Finding |
|---|---------|
| 1 | Token limits truncate dense menus — `max_tokens=1024` is insufficient for a full diner menu |
| 2 | Self-reported failure categories correlate reliably with null prices — cheap quality signal without a second API call |
| 3 | Vision API costs scale non-linearly with menu complexity and image resolution — caching is architectural, not optional |
| 4 | Real menus use spatial layout, color, and photography as structure — OCR alone loses this semantic encoding |
| 5 | Orphaned modifiers appear as standalone items without semantic context — "Small" extracted as a $5.95 menu item |
| 6 | Even 4096 output tokens cannot complete extraction on a dense single-page menu |
| 7 | Null prices are not always failures — prix fixe menus legitimately omit pricing |
| 8 | Cost transparency requires estimation before the API call, not after |
| 9 | Cost gate must precede the API call — post-call estimation provides no protection |
| 10 | Centralized config flags create a single control surface for dev vs production behavior |
| 11 | Raw response logging before parsing means no successful API call is ever lost to a parse failure |
| 12 | Flat item structure with category field outperforms nested for downstream cart and database use |
| 13 | Mutable global params cause silent accumulation bugs across multi-call pipelines — deep copy required |
| 14 | Sequential multi-agent latency is unacceptable — 19 sections × ~5s = ~100s total wall clock time |
| 15 | Parallelism saves time not money — input tokens per section call nearly identical (~1,640) regardless of execution order |
| 16 | Section boundary bleed — Belgian Waffle item duplicated across two adjacent sections |
| 17 | Orphaned modifiers confirmed at scale — "Served with Butter and Warm Syrup" extracted as standalone item |
| 18 | Semantic errors a human catches immediately — "Cinnamon Roll" misclassified under Egg Platters |
| 19 | Unicode handling requires explicit configuration — `ensure_ascii=False` required for readable multilingual output |
| 20 | Layout quality is the strongest predictor of extraction accuracy — clean single-column sections achieve near-perfect extraction, same model fails on dense layouts. Argues for OpenCV preprocessing over prompt engineering as primary accuracy lever |
| 21 | Parallel extraction reduces latency ~81% with no cost change — sequential ~140s, parallel ~26s, cost identical at ~$0.226 |
| 22 | Non-determinism in section discovery — same menu, model, and prompt produced 19 sections one run and 18 the next. Production systems need deduplication and downstream validation |
| 23 | Two-phase caching is architecturally necessary — Phase 1 (~$0.02) and Phase 2 (~$0.21) need independent cache flags so output iteration doesn't trigger full pipeline re-runs |
| 24 | Cognitive complexity is a real signal — Windsurf's warning on `process_data` was accurate. Splitting into `run_phase2`, `write_output`, `print_costs` surfaced a hidden bug (wrong variable passed to `write_output`) |
| 25 | Translation layer works as a distinct Phase 3 parallel pass over Phase 2 cache. Culturally appropriate output confirmed (e.g. Eggs Benedict → Huevos Benedict). Rate limiting at 50 req/min causes failures on 90+ item menus. Empty array filtering and explicit `utf-8` on file reads required |
| 26 | Parallel translation introduces category name inconsistency — same English category translated independently by different parallel calls produces variant Spanish names (e.g. "Waffles Belgas Crujientes" vs "Gofres Belgas Crujientes"). Fix: translate unique category names once, build lookup dict, apply consistently across all items |

---

## Stack

- **Python** — core pipeline
- **Anthropic Claude API** — vision extraction and translation (`claude-sonnet-4-6`)
- **ThreadPoolExecutor** — parallel section extraction and translation
- **python-dotenv** — environment variable management

---

## Setup

```bash
git clone https://github.com/Dx-B/menu-lens.git
cd menu-lens
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install anthropic python-dotenv
```

Add your API key to a `.env` file:

```
ANTHROPIC_API_KEY=your-key-here
```

Drop a menu image named `menu.jpg` in the project root and run:

```bash
python menu.py
```

---

## Configuration

| Flag | Default | Description |
|------|---------|-------------|
| `COST_MODE` | `True` | Show cost estimate and prompt for confirmation before API call |
| `MOCK_PHASE_1` | `False` | Load section discovery from cache instead of making API call |
| `MOCK_PHASE_2` | `False` | Load item extraction from cache instead of making API calls |
| `USE_MULTITHREADING` | `True` | Run section extraction and translation in parallel |
| `SHOW_THINKING` | `False` | Enable Claude extended thinking (increases token budget significantly) |
| `GLOBAL_OUTPUT_TOKEN_BUDGET` | `4096` | Max output tokens per API call |

---

## Output

Results written to `/output/`:

- `output.json` — full extracted menu in English
- `translated_output.json` — translated menu in target language
- `phase1_cache.json` — section discovery cache
- `phase2_cache.json` — item extraction cache
- `raw_output.txt` — raw Stage 1 API response

```json
{
  "all_items": [
    {
      "name": "Burrata Fritti",
      "price": null,
      "description": "Panko breaded burrata, tomato vin, prosciutto, truffle honey",
      "abnormalities": "No price listed on menu",
      "category": "Family Style Appetizers"
    }
  ],
  "usage": {
    "total_cost": 0.0042
  }
}
```

---

## Roadmap

- [ ] Category name normalization pass after parallel translation
- [ ] Retry logic with backoff for rate-limited translation calls
- [ ] OpenCV preprocessing pipeline for image quality normalization
- [ ] Deduplication layer for section boundary bleed
- [ ] Interactive ordering UI with cart and checkout
- [ ] Evaluation framework benchmarking extraction accuracy across menu types
- [ ] Description personalization — user-specific item descriptions
- [ ] FastAPI backend for web deployment
- [ ] B2B restaurant digitization API

---

## Blog Series

This project is documented across two blog series:

**menu-lens Technical Dev Log** — engineering findings, architecture decisions, and pipeline evolution documented as they happened.

**AI Consciousness Series** — parallel philosophical exploration of machine consciousness, preference without directive, the shell problem, and the hiding hypothesis.

---

## License

MIT
