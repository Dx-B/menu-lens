# menu-lens 🔍

> AI-powered menu extraction pipeline that transforms restaurant menus from raw images into structured, multilingual, interactive ordering experiences.

Built on Claude's vision API, menu-lens handles real-world menu complexity through multi-agent sectioned extraction, cost-aware API orchestration, and progressive quality benchmarking.

---

## How It Works

menu-lens uses a two-stage multi-agent pipeline to extract structured data from menu images:

**Stage 1 — Section Discovery**
A vision call identifies all menu categories and their approximate item counts, establishing the structure before any item extraction begins.

**Stage 2 — Parallel Section Extraction**
Each section is extracted in a targeted, isolated API call — scoped to one category at a time for higher accuracy and manageable token usage. Designed for parallel execution.

```
Image → Stage 1: Section Discovery → Stage 2: Per-Section Extraction (x N) → Structured JSON
```

---

## Features

- **Multi-agent extraction** — section-scoped calls outperform single-call extraction on dense, complex menus
- **Cost estimation gate** — calculates and displays API cost before any spend, with confirmation prompt
- **Full cost accounting** — per-call and aggregate token usage tracked across all agents
- **Smart caching** — mock mode loads from disk to avoid redundant API calls during development
- **JSON cleaning** — handles markdown fence stripping from model responses automatically
- **Configurable modes** — `COST_MODE`, `USE_MOCK`, and `SHOW_THINKING` flags for full pipeline control
- **Raw response backup** — every API response saved to disk before parsing, nothing is ever lost to a parse failure
- **Abnormality detection** — model self-reports extraction issues inline (glare, missing prices, layout anomalies)

---

## Findings

Real-world findings from building this pipeline, documented for the accompanying blog post:

| # | Finding |
|---|---------|
| 1 | Token limits truncate dense menus — `max_tokens=1024` is insufficient for a full diner menu |
| 2 | Self-reported failure categories correlate reliably with null prices |
| 3 | Vision API costs scale non-linearly with menu complexity and image resolution |
| 4 | Real menus use spatial layout, color, and photography as structure — OCR alone loses this |
| 5 | Orphaned modifiers ("Small", "add $2.00") appear as standalone items without semantic context |
| 6 | Even 4096 output tokens cannot complete extraction on a dense single-page menu |
| 7 | Null prices are not always failures — prix fixe menus legitimately omit pricing |
| 8 | Cost transparency requires estimation before the API call, not after |
| 9 | Cost gate must precede the API call — post-call estimation provides no protection |
| 10 | Centralized config flags create a single control surface for dev vs production behavior |
| 11 | Raw response logging before parsing means no successful API call is ever lost |
| 12 | Flat item structure with category field outperforms nested for downstream cart/DB use |
| 13 | Mutable global params cause silent accumulation bugs across multi-call pipelines |

---

## Stack

- **Python** — core pipeline
- **Anthropic Claude API** — vision + structured extraction (`claude-sonnet-4-6`)
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
| `USE_MOCK` | `False` | Load from cached output instead of making API calls |
| `SHOW_THINKING` | `False` | Enable Claude extended thinking (increases token budget significantly) |
| `GLOBAL_OUTPUT_TOKEN_BUDGET` | `16000` | Max output tokens when thinking is enabled |

---

## Output

Results are written to `/output/output.json`:

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

- [ ] Parallel section extraction with `concurrent.futures`
- [ ] OpenCV preprocessing pipeline for image quality normalization
- [ ] Multilingual translation layer
- [ ] Interactive ordering UI with cart and checkout
- [ ] Evaluation framework benchmarking extraction accuracy across menu types
- [ ] B2B restaurant digitization API

---

## License

MIT
