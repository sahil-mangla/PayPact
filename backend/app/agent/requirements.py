"""Deterministic extraction and verification of what a purchase request asks for.

The shopper agent used to return the one catalogue item in a category whatever the
query said (any flight request got DEL -> BLR). This module reads the explicit
requirements out of the prompt (product kind, route, class, trip type, airline, dates,
quantity) and checks a candidate item against them, so a proposal is only built for an
item that matches. No language model is involved: an LLM may later explain a verified
match, but it is never the judge of one.

Requirements the prompt does not state are not enforced. Requirements the catalogue
cannot verify (a travel date, a window seat) count as unmet rather than being waved
through.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

MAX_QUANTITY = 10

# canonical code -> (display name, aliases as written in a prompt)
_CITIES: Dict[str, tuple] = {
    "DEL": ("New Delhi", ["new delhi", "delhi", "del", "ndls"]),
    "BLR": ("Bengaluru", ["bengaluru", "bangalore", "blr"]),
    "BOM": ("Mumbai", ["mumbai", "bombay", "bom"]),
    "GOI": ("Goa", ["goa"]),
    "MAA": ("Chennai", ["chennai", "madras", "maa"]),
    "CCU": ("Kolkata", ["kolkata", "calcutta", "ccu"]),
    "HYD": ("Hyderabad", ["hyderabad", "hyd"]),
    "PNQ": ("Pune", ["pune"]),
    "JAI": ("Jaipur", ["jaipur"]),
    "AMD": ("Ahmedabad", ["ahmedabad"]),
    "COK": ("Kochi", ["kochi", "cochin"]),
    "DXB": ("Dubai", ["dubai"]),
    "SIN": ("Singapore", ["singapore"]),
    "LHR": ("London", ["london"]),
    "JFK": ("New York", ["new york", "nyc"]),
}
_ALIAS_TO_CODE = {a: code for code, (_, aliases) in _CITIES.items() for a in aliases}
_KNOWN_CITY = "|".join(sorted(map(re.escape, _ALIAS_TO_CODE), key=len, reverse=True))
# a known city, else one plain word that is not a filler word
_NOT_A_PLACE = (
    r"the|a|an|my|me|be|get|see|do|buy|book|find|go|your|our|this|that|it|reach|"
    r"avoid|work|travel|fly|under|within|below|for|with|and|or|on|in|at|by|via|"
    r"economy|business|premium|first|class|coach|cheap|budget|total|just|only|any|some"
)
_CITY = rf"(?:{_KNOWN_CITY}|(?!(?:{_NOT_A_PLACE})\b)[a-z]{{3,}})"

# Product kinds in match order. Earlier patterns mask their text from later ones, so
# "mouse pad" is a desk mat and not a mouse.
_KINDS = [
    ("desk mat", r"\b(?:desk\s?mats?|mouse\s?pads?|wrist\s?rests?|mats?)\b"),
    ("flight", r"\b(?:flights?|fly|flying|airfare|airline|air\s+tickets?)\b"),
    ("train", r"\b(?:trains?|railways?|rail|irctc)\b"),
    ("bus", r"\b(?:buses|bus)\b"),
    ("cab", r"\b(?:cabs?|taxis?|uber)\b"),
    (
        "hotel",
        r"\b(?:hotels?|resorts?|lodging|accommodation|hostels?|"
        r"(?:\d+|one|two|three|four|five|six|seven)[ -]nights?)\b",
    ),
    ("keyboard", r"\bkeyboards?\b"),
    ("mouse", r"\b(?:mouse|mice)\b"),
    ("monitor", r"\b(?:monitors?|displays?)\b"),
    ("dock", r"\b(?:docks?|organi[sz]ers?|docking)\b"),
]
_TRAVEL_KINDS = {"flight", "hotel", "train", "bus", "cab"}

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}  # fmt: skip
_NUM = rf"(?:\d{{1,2}}|{'|'.join(_NUMBER_WORDS)})"
_QTY_UNIT = (
    r"(?:tickets?|flights?|bookings?|seats?|passengers?|travell?ers?|people|persons|adults|pax|"
    r"keyboards?|mice|mouses?|mats?|docks?|units?|pieces?|pcs)"
)

_AIRLINES = {
    "indigo": ["indigo", "6e"],
    "air india": ["air india"],
    "vistara": ["vistara"],
    "spicejet": ["spicejet", "spice jet"],
    "akasa": ["akasa"],
    "airasia": ["airasia", "air asia"],
    "emirates": ["emirates"],
    "qatar": ["qatar"],
    "lufthansa": ["lufthansa"],
    "british airways": ["british airways"],
}

_CLASSES = [
    ("premium economy", r"\bpremium[ -]economy\b"),
    ("business", r"\bbusiness(?:[ -]class)?\b"),
    ("first", r"\bfirst[ -]class\b"),
    ("economy", r"\b(?:economy|coach)\b"),
]

_MONTHS = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_WHEN_PATTERNS = [
    rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTHS}\b",
    rf"\b{_MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?\b",
    r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b",
    r"\b(?:today|tomorrow|tonight|day after tomorrow|next\s+(?:week|month|weekend))\b",
    r"\b(?:on\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    r"\b(?:morning|evening|afternoon|overnight|red-?eye)\b",
    r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b",
]
_PREFERENCES = r"\b(?:window|aisle|extra legroom|wheelchair|vegetarian|vegan|jain|halal|refundable)\b"
_STARS = r"\b(\d)[ -]?stars?\b"


@dataclass
class Requirements:
    """What the prompt explicitly asks for. None / empty means 'not stated'."""

    kinds: Set[str] = field(default_factory=set)
    origin: Optional[str] = None  # canonical code, or the literal word if unknown
    destination: Optional[str] = None
    travel_class: Optional[str] = None
    round_trip: bool = False
    airline: Optional[str] = None
    when: Optional[str] = None  # a date or time the catalogue cannot verify
    preference: Optional[str] = None  # a seat or service preference
    stars: Optional[int] = None
    quantity: int = 1
    quantity_given: bool = False


@dataclass
class ProductFacts:
    """The attributes of a catalogue item that requirements are checked against."""

    sku: str
    kind: str = ""
    origin: Optional[str] = None
    destination: Optional[str] = None
    travel_class: Optional[str] = None
    trip_type: Optional[str] = None
    airline: Optional[str] = None


def city_name(code_or_word: Optional[str]) -> str:
    if not code_or_word:
        return ""
    if code_or_word in _CITIES:
        return _CITIES[code_or_word][0]
    return code_or_word.title()


def _canon_city(word: str) -> str:
    word = word.strip().lower()
    return _ALIAS_TO_CODE.get(word, word)


def _kinds(prompt: str) -> Set[str]:
    """Product kinds the prompt asks for, one per noun group (a compound like
    'keyboard desk mat' is one request whose head noun is the last word)."""
    masked = prompt
    mentions = []
    for kind, pattern in _KINDS:
        for m in re.finditer(pattern, masked):
            mentions.append((m.start(), m.end(), kind))
            masked = (
                masked[: m.start()] + " " * (m.end() - m.start()) + masked[m.end() :]
            )
    mentions.sort()
    groups: List[List[tuple]] = []
    for mention in mentions:
        if groups and not prompt[groups[-1][-1][1] : mention[0]].strip(" -"):
            groups[-1].append(mention)
        else:
            groups.append([mention])
    return {group[-1][2] for group in groups}


def _route(prompt: str) -> tuple:
    m = re.search(rf"\bfrom\s+({_CITY})\s+(?:to|towards|->|→)\s+({_CITY})\b", prompt)
    if m:
        return _canon_city(m.group(1)), _canon_city(m.group(2))
    m = re.search(rf"\b({_KNOWN_CITY})\s*(?:to|->|→|–|-|—)\s*({_KNOWN_CITY})\b", prompt)
    if m:
        return _canon_city(m.group(1)), _canon_city(m.group(2))
    origin = destination = None
    m = re.search(rf"\bfrom\s+({_CITY})\b", prompt)
    if m:
        origin = _canon_city(m.group(1))
    m = re.search(rf"\b(?:to|towards|in|at|near)\s+({_CITY})\b", prompt)
    if m:
        destination = _canon_city(m.group(1))
    if origin is None and destination is None:
        # "Mumbai flight", "hotel Bangalore": one bare city is where they want to go
        mentioned = {
            _canon_city(c) for c in re.findall(rf"\b({_KNOWN_CITY})\b", prompt)
        }
        if len(mentioned) == 1:
            destination = mentioned.pop()
    return origin, destination


def _quantity(prompt: str, kinds: Set[str]) -> tuple:
    found = []
    for m in re.finditer(
        rf"\b({_NUM})\s*(?:x\s*)?(?:[a-z\-]+\s+){{0,2}}?({_QTY_UNIT}|nights?|rooms?)\b",
        prompt,
    ):
        n = _NUMBER_WORDS.get(m.group(1)) or int(m.group(1))
        found.append((n, m.group(2).rstrip("s")))
    for m in re.finditer(r"\bx\s?(\d{1,2})\b|\b(\d{1,2})\s?x\b", prompt):
        found.append((int(m.group(1) or m.group(2)), "x"))
    if not found:
        return 1, False
    if "hotel" in kinds:  # rooms and nights multiply
        total = 1
        for n, unit in found:
            if unit in ("night", "room"):
                total *= n
        if total > 1 or any(unit in ("night", "room") for _, unit in found):
            return total, True
    return found[0][0], True


def parse_requirements(prompt: str) -> Requirements:
    p = prompt.lower()
    req = Requirements(kinds=_kinds(p))
    travel = bool(req.kinds & {"flight", "hotel"})
    if travel:
        req.origin, req.destination = _route(p)
        if "flight" not in req.kinds:
            req.origin = None  # a hotel has no departure city
    for name, pattern in _CLASSES:
        if re.search(pattern, p):
            req.travel_class = name
            break
    req.round_trip = bool(
        re.search(r"\b(?:round[ -]?trip|two[ -]way|return)\b", p)
    ) and not re.search(r"\bone[ -]way\b", p)
    for name, aliases in _AIRLINES.items():
        if any(re.search(rf"\b{re.escape(a)}\b", p) for a in aliases):
            req.airline = name
            break
    for pattern in _WHEN_PATTERNS:
        m = re.search(pattern, p)
        if m:
            req.when = m.group(0).strip()
            break
    m = re.search(_PREFERENCES, p)
    if m:
        req.preference = m.group(0)
    m = re.search(_STARS, p)
    if m:
        req.stars = int(m.group(1))
    req.quantity, req.quantity_given = _quantity(p, req.kinds)
    return req


_GENERIC = {
    "order", "buy", "find", "book", "want", "need", "please", "budget", "maximum", "minimum",
    "ceiling", "under", "over", "below", "above", "limit", "limits", "auto", "approval",
    "approvals", "require", "proceed", "automatically", "immediately", "without", "with",
    "from", "that", "this", "have", "suitable", "best", "good", "cheap", "premium", "custom",
    "luxury", "high", "quality", "enterprise", "standard", "professional", "compact", "full",
    "wireless", "new", "latest", "something", "anything", "item", "product", "purchase",
    "buying", "get", "search", "looking", "for", "your", "will", "must", "total", "spend",
}  # fmt: skip


def topic_overlap(prompt: str, item_text: str) -> int:
    """How many distinct topic words the prompt and the item text have in common."""

    def words(text: str) -> Set[str]:
        return {
            w.rstrip("s")
            for w in re.findall(r"[a-z]{4,}", text.lower())
            if w not in _GENERIC and w.rstrip("s") not in _GENERIC
        }

    return len(words(prompt) & words(item_text))


def shares_topic(prompt: str, item_text: str) -> bool:
    """True if the prompt names at least one thing the item text also names.

    Used only when the prompt names no product type we recognise, so that something
    like "buy me a yacht" cannot be satisfied by an arbitrary catalogue item.
    """
    return topic_overlap(prompt, item_text) > 0


def unmet_requirements(req: Requirements, item: ProductFacts) -> List[str]:
    """Reasons this item does not satisfy the request; empty means it matches."""
    unmet: List[str] = []

    if len(req.kinds) > 1:
        unmet.append(
            f"the request asks for {' and '.join(sorted(req.kinds))} together, but one "
            "proposal covers a single item; request them separately"
        )
    elif req.kinds and item.kind not in req.kinds:
        asked = next(iter(req.kinds))
        unmet.append(
            f"you asked for a {asked}, but this item is a {item.kind or 'different product'}"
        )

    if req.quantity > MAX_QUANTITY:
        unmet.append(
            f"quantity {req.quantity} is above the limit of {MAX_QUANTITY} per proposal"
        )

    if item.kind == "flight":
        if req.origin and req.origin != item.origin:
            unmet.append(
                f"it departs {city_name(item.origin)}, not {city_name(req.origin)}"
            )
        if req.destination and req.destination != item.destination:
            unmet.append(
                f"it flies to {city_name(item.destination)}, not {city_name(req.destination)}"
            )
        if req.travel_class and req.travel_class != item.travel_class:
            unmet.append(f"it is {item.travel_class} class, not {req.travel_class}")
        if req.round_trip and item.trip_type != "round-trip":
            unmet.append("it is a one-way fare, not a return")
        if req.airline and req.airline != item.airline:
            unmet.append(
                f"it is operated by {(item.airline or 'another airline').title()}, "
                f"not {req.airline.title()}"
            )
    elif item.kind == "hotel":
        if req.destination and req.destination != item.destination:
            unmet.append(
                f"it is in {city_name(item.destination)}, not {city_name(req.destination)}"
            )
        if req.stars:
            unmet.append(
                f"the catalogue does not state a star rating ({req.stars}-star requested)"
            )

    if item.kind in ("flight", "hotel"):
        if req.when:
            unmet.append(
                f"the catalogue has no date or time specific inventory ('{req.when}' requested)"
            )
        if req.preference:
            unmet.append(
                f"the catalogue cannot confirm a '{req.preference}' preference"
            )
    return unmet


def verified_facts(req: Requirements, item: ProductFacts) -> List[str]:
    """The explicit requirements this item was checked against and satisfies."""
    facts: List[str] = []
    if req.kinds:
        facts.append(f"product type: {item.kind}")
    if item.kind == "flight":
        if req.origin and req.destination:
            facts.append(
                f"route {city_name(req.origin)} to {city_name(req.destination)}"
            )
        elif req.destination:
            facts.append(f"destination {city_name(req.destination)}")
        elif req.origin:
            facts.append(f"departure {city_name(req.origin)}")
        if req.travel_class:
            facts.append(f"{req.travel_class} class")
        if req.airline:
            facts.append(f"airline {req.airline}")
    elif item.kind == "hotel" and req.destination:
        facts.append(f"city {city_name(req.destination)}")
    if req.quantity_given:
        facts.append(f"quantity {req.quantity}")
    return facts
