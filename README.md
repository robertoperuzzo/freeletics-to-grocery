# freeletics-to-pie

Takes the shopping list shared from **Freeletics Nutrition**, normalises and sums the ingredients, and merges them into a **Buy Me a Pie!** list.

## What it does
- Reads only the lines between "Ingredients you need:" and "Catering for recipes:".
- Handles comma decimals (`0,5`), converts `kg`→`g` and `l`→`ml`, and strips notes in parentheses and words like "ripe" and "fresh".
- Merges duplicates. For example, `8 hard-boiled eggs` + `3 eggs` → `Eggs: 11`.
- Rounds up anything you buy whole (`0,5 avocados` → 1, `0,25 bunches cilantro` → 1 bunch).
- Never converts between unlike units. Instead it combines them: `200 g + 6 tbsp`.
- Merging into Buy Me a Pie:
  - adds new items,
  - sums into open items with a parseable amount,
  - re-opens items already crossed off,
  - leaves free-text amounts alone and adds a separate item instead.

## Setup
```bash
pip install -r requirements.txt
export BUYMEAPIE_USERNAME=you@example.com BUYMEAPIE_PIN=1234
export BUYMEAPIE_LIST="Grocery"      # existing list name
export API_TOKEN=some-long-random-string

python app.py --dry-run < sample.txt   # preview, no writes
uvicorn app:api --host 0.0.0.0 --port 8000
```

## iOS Shortcut
1. Create a new Shortcut. In its settings, turn on **Show in Share Sheet** and accept **Text**.
2. Add a **Get Contents of URL** action with:
   - URL: `https://<your-host>/freeletics`
   - Method: POST
   - Header: `X-Token: <API_TOKEN>`
   - Request Body: File → Shortcut Input
3. Add **Show Result** to see what changed.

Then, in Freeletics: Shopping List → **Share** → pick your Shortcut.

Tip: append `?dry_run=true` to the URL for a first test.

## Tuning
In `app.py`, edit:
- `DESCRIPTORS` for words to ignore,
- `ALIASES` for explicit renames,
- `ROUND_UP_UNITS` for which units round up.

## Caveat
Buy Me a Pie's API (`app.buymeapie.com`) is unofficial and undocumented. The endpoints come from the open-source `glitchcrab/buy-me-a-pie-mcp` client.
