#!/usr/bin/env python3
"""
AI Support Desk
================
Sends each customer support ticket to an LLM (Claude) and turns the raw
response into structured, usable information: category, urgency and a
suggested action, instead of leaving a human to re-read raw text.

Usage:
    python support_desk.py

Requires:
    ANTHROPIC_API_KEY set in the environment or in a local .env file
    (see .env.example). Never commit your real .env file.

Outputs (written next to this script):
    results.json   - structured classification for every ticket
    summary.md     - counts by category and by urgency
"""

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # pulls ANTHROPIC_API_KEY from a local .env file if present

MODEL = "claude-sonnet-5"
MAX_RETRIES = 3
TIMEOUT_SECONDS = 30
TICKETS_FILE = Path(__file__).parent / "sample_tickets.json"

ALLOWED_CATEGORIES = ["billing", "technical", "account", "general_question", "feature_request"]
ALLOWED_URGENCY = ["low", "medium", "high", "critical"]

SYSTEM_PROMPT = f"""You are a support-ticket triage assistant. Given a single
customer support ticket, respond with ONLY a JSON object — no markdown
fences, no commentary before or after — with exactly these keys:

- "category": one of {ALLOWED_CATEGORIES}
- "urgency": one of {ALLOWED_URGENCY}
- "suggested_action": a short (1-2 sentence) concrete next step for the
  support agent handling this ticket

Base urgency on business impact and tone (e.g. blocked work, money at
stake, or angry/urgent language pushes urgency up), not just politeness.
Respond with the JSON object and nothing else."""


# ---------------------------------------------------------------------------
# Step 2 + 3: Call the LLM for one ticket, parse its JSON, handle failures
# ---------------------------------------------------------------------------
def classify_ticket(client, ticket: dict) -> dict:
    """
    Sends one ticket to the model and returns a structured result dict.
    Never raises — API failures and malformed responses are captured in the
    returned dict instead of crashing the batch.
    """
    user_prompt = f"Subject: {ticket['subject']}\n\nMessage: {ticket['message']}"

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=300,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
                timeout=TIMEOUT_SECONDS,
            )
            raw_text = response.content[0].text.strip()

            # Models occasionally wrap JSON in ```json fences despite instructions;
            # strip those defensively before parsing.
            if raw_text.startswith("```"):
                raw_text = raw_text.strip("`")
                raw_text = raw_text.split("\n", 1)[1] if "\n" in raw_text else raw_text
                raw_text = raw_text.rsplit("```", 1)[0]

            parsed = json.loads(raw_text)

            # Validate the shape we asked for; treat a bad value as a parse failure
            if parsed.get("category") not in ALLOWED_CATEGORIES:
                raise ValueError(f"unexpected category: {parsed.get('category')!r}")
            if parsed.get("urgency") not in ALLOWED_URGENCY:
                raise ValueError(f"unexpected urgency: {parsed.get('urgency')!r}")
            if not parsed.get("suggested_action"):
                raise ValueError("missing suggested_action")

            return {
                "ticket_id": ticket["ticket_id"],
                "subject": ticket["subject"],
                "category": parsed["category"],
                "urgency": parsed["urgency"],
                "suggested_action": parsed["suggested_action"],
                "source": "llm",
                "error": None,
            }

        except json.JSONDecodeError as e:
            last_error = f"malformed JSON from model: {e}"
        except ValueError as e:
            last_error = f"response failed validation: {e}"
        except Exception as e:  # covers API/auth/rate-limit/timeout errors generically
            last_error = f"API call failed: {type(e).__name__}: {e}"

        print(f"  [attempt {attempt}/{MAX_RETRIES}] {ticket['ticket_id']}: {last_error}")
        time.sleep(1.5 * attempt)

    # All retries exhausted — fall back to a simple heuristic classifier so a
    # ticket never just gets dropped from the summary, and flag it clearly.
    fallback = heuristic_classify(ticket)
    fallback["source"] = "fallback_heuristic"
    fallback["error"] = last_error
    return fallback


# ---------------------------------------------------------------------------
# Fallback used only if the LLM is completely unreachable after retries
# ---------------------------------------------------------------------------
def heuristic_classify(ticket: dict) -> dict:
    text = (ticket["subject"] + " " + ticket["message"]).lower()

    if any(w in text for w in ("charge", "refund", "billing", "invoice", "subscription", "seats")):
        category = "billing"
    elif any(w in text for w in ("crash", "error", "bug", "freeze", "typeerror", "sync")):
        category = "technical"
    elif any(w in text for w in ("locked", "log in", "login", "password", "account")):
        category = "account"
    elif any(w in text for w in ("feature", "suggestion", "dark mode", "consider adding")):
        category = "feature_request"
    else:
        category = "general_question"

    if any(w in text for w in ("urgent", "asap", "immediately", "today", "!!")):
        urgency = "high"
    elif any(w in text for w in ("no rush", "not a big deal", "whenever")):
        urgency = "low"
    else:
        urgency = "medium"

    return {
        "ticket_id": ticket["ticket_id"],
        "subject": ticket["subject"],
        "category": category,
        "urgency": urgency,
        "suggested_action": "Route to a human agent for review (LLM classification unavailable).",
    }


# ---------------------------------------------------------------------------
# Step 4: Summary
# ---------------------------------------------------------------------------
def build_summary(results: list[dict]) -> str:
    by_category = Counter(r["category"] for r in results)
    by_urgency = Counter(r["urgency"] for r in results)
    llm_count = sum(1 for r in results if r["source"] == "llm")
    fallback_count = len(results) - llm_count

    lines = ["# Support Ticket Summary\n", f"**Total tickets processed:** {len(results)}",
              f"**Classified by LLM:** {llm_count}  |  **Fell back to heuristic:** {fallback_count}\n"]

    lines.append("## By Category")
    for cat, n in by_category.most_common():
        lines.append(f"- {cat}: {n}")
    lines.append("\n## By Urgency")
    urgency_order = ["critical", "high", "medium", "low"]
    for level in urgency_order:
        if by_urgency.get(level):
            lines.append(f"- {level}: {by_urgency[level]}")

    lines.append("\n## Tickets Needing Attention First (critical/high urgency)")
    urgent = [r for r in results if r["urgency"] in ("critical", "high")]
    if urgent:
        for r in urgent:
            lines.append(f"- **{r['ticket_id']}** ({r['category']}): {r['suggested_action']}")
    else:
        lines.append("- None.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    out_dir = Path(__file__).parent

    with open(TICKETS_FILE) as f:
        tickets = json.load(f)
    print(f"Loaded {len(tickets)} tickets from {TICKETS_FILE.name}")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    client = None
    if api_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
        except ImportError:
            print("[warn] 'anthropic' package not installed (pip install anthropic). "
                  "Falling back to heuristic classification for all tickets.")
    else:
        print("[warn] ANTHROPIC_API_KEY not set (check your .env file). "
              "Falling back to heuristic classification for all tickets.")

    results = []
    for ticket in tickets:
        print(f"Processing {ticket['ticket_id']}: {ticket['subject']}")
        if client:
            result = classify_ticket(client, ticket)
        else:
            result = heuristic_classify(ticket)
            result["source"] = "fallback_heuristic"
            result["error"] = "no API client available"
        results.append(result)

    (out_dir / "results.json").write_text(json.dumps(results, indent=2))

    summary_text = build_summary(results)
    (out_dir / "summary.md").write_text(summary_text)

    print("\nDone. Wrote:")
    print("  - results.json")
    print("  - summary.md")


if __name__ == "__main__":
    main()
