# Obstacle Log : AI Support Desk

## 1. No live API access in the build/test environment
The sandbox I used to write and test this script has no outbound network
access at all, so `client.messages.create(...)` could never actually reach
the API here, regardless of whether a key was configured.

**Fix:** rather than let a network-less run crash or produce nothing,
`classify_ticket()` retries a few times and then falls back to a small
rule-based `heuristic_classify()` (simple keyword matching for category and
urgency) so the rest of the pipeline, parsing, validation, summary
generation — could still be exercised end-to-end. Every result records its
`"source"` (`"llm"` or `"fallback_heuristic"`) and, when it fell back, the
`"error"` that caused it, so nothing is silently mislabeled as a real model
classification. On a machine with a valid `ANTHROPIC_API_KEY` and normal
internet access, tickets are classified by the model on the first attempt
and this fallback path never triggers. The attached `results.json` /
`summary.md` were generated via the fallback path in this environment —
that's expected and documented, not a bug in the classification logic.

## 2. Getting the model to return *only* JSON
The prompt asks for a bare JSON object, but LLMs will sometimes wrap it in
a ```json code fence or add a stray sentence before/after, which breaks a
naive `json.loads()` call.

**Fix:** the system prompt is explicit about "no markdown fences, no
commentary," and the parsing step defensively strips a leading/trailing
code fence before calling `json.loads()`, so a fenced response still parses
correctly instead of raising.

## 3. A syntactically valid but semantically wrong response
Even when `json.loads()` succeeds, the model could return a category or
urgency value outside the fixed set (eg: "Billing Issue" instead of
"billing"), which would quietly corrupt the summary counts.

**Fix:** added explicit validation after parsing — `category` and
`urgency` are checked against fixed allow-lists, and a missing
`suggested_action` is also treated as a failure. Any of these trigger a
retry rather than being accepted as-is.

## 4. Keeping the API key out of the repo
It's easy to accidentally commit a `.env` file with a real key in it,
especially early in a project before `.gitignore` is set up.

**Fix:** the script reads the key via `python-dotenv` / `os.environ`, only
an `.env.example` (with a placeholder, safe to commit) is checked in, and
`.gitignore` excludes `.env` from the start of the project rather than
being added after the fact.
