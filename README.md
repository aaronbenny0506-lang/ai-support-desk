# AI Support Desk

Sends customer support tickets to an LLM (Claude) and turns each raw reply
into structured, usable information — `category`, `urgency` and a
`suggested_action`, instead of leaving a human to re-read raw text.

## Files

| File | Purpose |
|---|---|
| `support_desk.py` | Main script: loads tickets, classifies each via the Anthropic API, validates the response, writes `results.json` and `summary.md`. Falls back to a keyword-based heuristic if the API is unreachable or a key isn't configured. |
| `sample_tickets.json` | 7 sample tickets covering billing, technical bugs, account access, a general/feature question, and mixed tones (angry, casual, urgent). |
| `results.json` | Generated output: structured classification per ticket. |
| `summary.md` | Generated output: counts by category/urgency and a "needs attention first" list. |
| `obstacle_log.md` | Issues hit during the build and how they were fixed. |
| `.env.example` | Template for the required `ANTHROPIC_API_KEY`. Copy to `.env` and fill in your real key. |
| `.gitignore` | Excludes `.env`, `__pycache__/`, `*.pyc`, `.venv/` from version control. |
| `requirements.txt` | `anthropic`, `python-dotenv`. |

## Setup & Run

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env and add your real ANTHROPIC_API_KEY

python support_desk.py
```

This writes/overwrites `results.json` and `summary.md` in place.

## Note on the included results

The `results.json` / `summary.md` in this repo were generated in a sandboxed
build environment with **no outbound network access**, so every ticket went
through the documented `heuristic_classify()` fallback rather than the LLM
(see `obstacle_log.md`, item 1). Each result's `"source"` field records this
honestly (`"fallback_heuristic"` vs `"llm"`). On a machine with a valid
`ANTHROPIC_API_KEY` and normal internet access, running `python
support_desk.py` will classify tickets with Claude on the first attempt and
regenerate both output files from real model output.
