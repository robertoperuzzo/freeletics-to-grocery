"""
freeletics-to-pie: Freeletics Nutrition shared shopping list -> Buy Me a Pie!

Flow: iOS Share sheet -> Shortcut POSTs the text here -> parse, normalise,
sum -> merge into an existing Buy Me a Pie list via its (unofficial) web API.

Run locally:   python app.py --dry-run < sample.txt
Run server:    uvicorn app:api --host 0.0.0.0 --port 8000
Env vars:      BUYMEAPIE_USERNAME, BUYMEAPIE_PIN, BUYMEAPIE_LIST (list name),
               API_TOKEN (shared secret the Shortcut sends as X-Token)
"""
from __future__ import annotations

import math
import os
import re
import sys
from collections import OrderedDict
from dataclasses import dataclass, field

# ---------------------------------------------------------------- config ---

# Leading words that don't change what you buy. Extend to taste.
DESCRIPTORS = {
    "ripe", "fresh", "small", "large", "medium", "natural", "unrefined",
    "hard-boiled", "chopped", "virgin", "fine", "firm",
}
# Explicit rewrites applied after cleaning (matching key -> canonical key).
ALIASES = {
    "cold cuts turkey breast": "turkey breast",
}
# Units Freeletics uses; value = (canonical unit, factor).
UNITS = {
    "g": ("g", 1), "kg": ("g", 1000),
    "ml": ("ml", 1), "l": ("ml", 1000),
    "tsp": ("tsp", 1), "tbsp": ("tbsp", 1),
    "slice": ("slices", 1), "slices": ("slices", 1),
    "bunch": ("bunches", 1), "bunches": ("bunches", 1),
    "clove": ("cloves", 1), "cloves": ("cloves", 1),
    "pinch": ("pinch", 1), "pinches": ("pinch", 1),
}
# Units you buy whole: round partial amounts up (0.5 bunch -> 1 bunch).
ROUND_UP_UNITS = {None, "slices", "bunches", "cloves"}

LINE_RE = re.compile(
    r"^(?P<qty>\d+(?:[.,]\d+)?)\s+"
    r"(?:(?P<unit>" + "|".join(sorted(UNITS, key=len, reverse=True)) + r")\s+)?"
    r"(?P<name>.+)$",
    re.IGNORECASE,
)

# ----------------------------------------------------------------- parse ---


@dataclass
class Entry:
    key: str                       # matching key (singular, lowercase)
    display: str                   # title shown in Buy Me a Pie
    amounts: dict = field(default_factory=OrderedDict)  # unit -> qty

    def amount_str(self) -> str:
        parts = []
        for unit, qty in self.amounts.items():
            if unit in ROUND_UP_UNITS:
                qty = math.ceil(qty - 1e-9)
            q = f"{qty:g}"
            if unit in ("slices", "bunches", "cloves") and qty == 1:
                unit = {"slices": "slice", "bunches": "bunch", "cloves": "clove"}[unit]
            parts.append(q if unit is None else f"{q} {unit}")
        return " + ".join(parts)


def singular(word: str) -> str:
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("oes"):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def clean_name(raw: str) -> str:
    name = re.sub(r"\(.*?\)", "", raw).strip().lower()
    words = name.split()
    while words and words[0] in DESCRIPTORS:
        words.pop(0)
    return " ".join(words)


def make_key(name: str, countable: bool) -> str:
    if countable:  # "2 red onions" -> "red onion"; leave "100 g oats" alone
        words = name.split()
        words[-1] = singular(words[-1])
        name = " ".join(words)
    return ALIASES.get(name, name)


def parse(text: str) -> list[tuple[str, str, str | None, float]]:
    """Return (key, display, unit, qty) for each ingredient line."""
    out, in_section = [], False
    for line in text.splitlines():
        line = line.strip().lstrip("⬜☐□✅☑-•* ").strip()
        low = line.lower()
        if low.startswith("ingredients you need"):
            in_section = True
            continue
        if low.startswith("catering for recipes"):
            break
        if not in_section or not line:
            continue
        m = LINE_RE.match(line)
        if not m:
            print(f"! could not parse: {line!r}", file=sys.stderr)
            continue
        qty = float(m["qty"].replace(",", "."))
        unit = None
        if m["unit"]:
            unit, factor = UNITS[m["unit"].lower()]
            qty *= factor
        name = clean_name(m["name"])
        key = make_key(name, countable=unit is None)
        out.append((key, ALIASES.get(name, name), unit, qty))
    return out


def aggregate(rows) -> "OrderedDict[str, Entry]":
    entries: OrderedDict[str, Entry] = OrderedDict()
    for key, display, unit, qty in rows:
        e = entries.setdefault(key, Entry(key, display.capitalize()))
        e.amounts[unit] = e.amounts.get(unit, 0) + qty
    return entries


def parse_amount(s: str) -> dict:
    """Parse an amount we previously wrote, e.g. '250 g + 6 tbsp' or '3'."""
    out = OrderedDict()
    for part in filter(None, (p.strip() for p in (s or "").split("+"))):
        m = re.match(r"^(\d+(?:[.,]\d+)?)\s*(\S+)?$", part)
        if not m:
            return {}  # free text written by a human: don't touch it
        unit = m[2]
        if unit:
            if unit.lower() not in UNITS:
                return {}
            unit, factor = UNITS[unit.lower()]
        else:
            factor = 1
        out[unit] = out.get(unit, 0) + float(m[1].replace(",", ".")) * factor
    return out

# ---------------------------------------------------------- Buy Me a Pie ---


class BuyMeAPie:
    """Minimal client for the unofficial web API at app.buymeapie.com."""
    BASE = "https://app.buymeapie.com"

    def __init__(self, username: str, pin: str):
        import requests
        self.s = requests.Session()
        self.s.auth = (username, pin)
        self.s.headers.update({
            "Origin": self.BASE,
            "Accept": "application/json, text/plain, */*",
        })
        self._req("get", "bauth")

    def _req(self, method, path, **kw):
        r = self.s.request(method, f"{self.BASE}/{path}", timeout=15, **kw)
        if r.status_code not in (200, 201):
            raise RuntimeError(f"{method.upper()} {path}: {r.status_code} {r.text}")
        return r.json() if r.text else {}

    def list_id(self, name: str) -> int:
        for lst in self._req("get", "lists"):
            if lst["name"].strip().lower() == name.strip().lower():
                return lst["id"]
        raise RuntimeError(f"Buy Me a Pie list {name!r} not found")

    def items(self, list_id):
        return self._req("get", f"lists/{list_id}/items")

    def add(self, list_id, title, amount):
        return self._req("post", f"lists/{list_id}/items",
                         json={"title": title, "amount": amount, "is_purchased": False})

    def update(self, list_id, item_id, title, amount):
        return self._req("put", f"lists/{list_id}/items/{item_id}",
                         json={"title": title, "amount": amount, "is_purchased": False})


def push(entries, client: BuyMeAPie, list_name: str) -> list[str]:
    """Merge entries into the list: sum into open items, revive purchased ones."""
    lid = client.list_id(list_name)
    existing = {}
    for it in client.items(lid):
        name = clean_name(it["title"])
        existing.setdefault(make_key(name, True), it)
        existing.setdefault(make_key(name, False), it)

    log = []
    for e in entries.values():
        it = existing.get(e.key)
        if it is None:
            client.add(lid, e.display, e.amount_str())
            log.append(f"+ {e.display}: {e.amount_str()}")
            continue
        if it.get("is_purchased"):
            new = e  # already bought last time: start fresh
        else:
            old = parse_amount(it.get("amount", ""))
            if not old and it.get("amount"):
                log.append(f"? {it['title']} has free-text amount "
                           f"{it['amount']!r}; added {e.amount_str()} separately")
                client.add(lid, e.display, e.amount_str())
                continue
            new = Entry(e.key, e.display, OrderedDict(old))
            for u, q in e.amounts.items():
                new.amounts[u] = new.amounts.get(u, 0) + q
        client.update(lid, it["id"], it["title"], new.amount_str())
        log.append(f"~ {it['title']}: {new.amount_str()}")
    return log

# --------------------------------------------------------------- entry points


def preview(entries) -> list[str]:
    return [f"{e.display}: {e.amount_str()}" for e in entries.values()]


try:
    from fastapi import FastAPI, Header, HTTPException, Request

    api = FastAPI(title="freeletics-to-pie")

    @api.post("/freeletics")
    async def freeletics(request: Request, dry_run: bool = False,
                         x_token: str = Header(default="")):
        if x_token != os.environ.get("API_TOKEN", ""):
            raise HTTPException(401, "bad token")
        text = (await request.body()).decode("utf-8")
        entries = aggregate(parse(text))
        if dry_run:
            return {"items": preview(entries)}
        client = BuyMeAPie(os.environ["BUYMEAPIE_USERNAME"], os.environ["BUYMEAPIE_PIN"])
        return {"changes": push(entries, client, os.environ.get("BUYMEAPIE_LIST", "Grocery"))}
except ImportError:  # FastAPI optional for CLI use
    api = None


if __name__ == "__main__":
    entries = aggregate(parse(sys.stdin.read()))
    if "--dry-run" in sys.argv:
        print("\n".join(preview(entries)))
    else:
        client = BuyMeAPie(os.environ["BUYMEAPIE_USERNAME"], os.environ["BUYMEAPIE_PIN"])
        print("\n".join(push(entries, client, os.environ.get("BUYMEAPIE_LIST", "Grocery"))))
