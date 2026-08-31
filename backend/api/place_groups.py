"""The eight place groups (מחנה/מוצב/צומת/מחלף/שטח אש/כביש/מחסום/אחר) and their display prefixes.

A place's full display string (e.g. "מ. אלפורן") is always what the API sends
and receives — the wire contract never changed. Internally, ``api.db.Database``
stores each place as a numeric id in a registry (``places.json``:
``{id: {"name": base_name, "group": group_key}}``) so that two distinct places
which happen to share a base name after stripping their prefix (e.g. "מ. גולני"
the camp and "מחלף גולני" the interchange) can never collide — this module is
what ``Database`` uses to parse a display string's prefix into
``(group, base_name)`` when resolving/minting that id, and to reconstruct the
display string back from a registry entry.

``frontend/src/utils/placeGroups.js`` is a separate, independent copy of this
same group/prefix vocabulary, used purely for *client-side* classification
(HomePage's type-filters, and deciding when the route editor's "which group?"
popover should appear) — since the frontend only ever sees full display
strings, it never needs to resolve or store an id at all. Keeping the two
copies conceptually aligned matters for UX consistency (so the client doesn't
prompt for a group the server would have parsed automatically, or vice versa),
but any drift is low-stakes: the server remains the sole authority for what
actually gets persisted.
"""

import re

DEFAULT_GROUP = "other"

# Key order matters: it is the group filter-chip render order on the frontend,
# kept identical there.
GROUPS = {
    "camp": {"label": "מחנה", "prefix": "מ."},
    "post": {"label": "מוצב", "prefix": "מוצב"},
    "junction": {"label": "צומת", "prefix": "צ."},
    "interchange": {"label": "מחלף", "prefix": "מחלף"},
    "firing_zone": {"label": "שטח אש", "prefix": "ש.א"},
    "road": {"label": "כביש", "prefix": "כביש"},
    "checkpoint": {"label": "מחסום", "prefix": "מחסום"},
    DEFAULT_GROUP: {"label": "אחר", "prefix": None},
}

GROUP_KEYS = set(GROUPS)

# One regex per group with a real prefix (skips "other", which has none). Order
# matters: "מוצב" must be tried before a bare "מ." pattern could ever partially
# match it, though the patterns below are specific enough that order is not
# actually load-bearing today — kept explicit regardless for parity with the
# frontend list's order.
PREFIX_PATTERNS = [
    ("camp", re.compile(r"^מ(?:\.\s*|\s+)(?=\S)")),
    ("post", re.compile(r"^מוצב\s+(?=\S)")),
    ("junction", re.compile(r"^צ(?:\.\s*|\s+)(?=\S)")),
    ("interchange", re.compile(r"^מחלף\s*(?=\S)")),
    ("firing_zone", re.compile(r"^ש[.\s]?א\s*(?=\S)")),
    ("road", re.compile(r"^כביש\s+(?=\S)")),
    ("checkpoint", re.compile(r"^מחסום\s+(?=\S)")),
]


def parse_prefixed_name(text):
    """Split a typed/stored string into ``(group_key, base_name)`` if it starts
    with one of the five recognized prefixes, else ``None``.

    The caller decides what "no match" means: the one-time migration defaults it
    to :data:`DEFAULT_GROUP`, while the live route editor asks the user instead
    of guessing.
    """
    trimmed = (text or "").strip()
    for group_key, pattern in PREFIX_PATTERNS:
        match = pattern.match(trimmed)
        if match:
            base = trimmed[match.end():].strip()
            if base:
                return group_key, base
    return None


def format_place(base_name, group_key):
    """The prefixed display string for a base name + group.

    Used by the migration command's log output; the frontend module
    (``placeGroups.js``) is the real display authority for the UI.
    """
    prefix = GROUPS.get(group_key, GROUPS[DEFAULT_GROUP])["prefix"]
    return f"{prefix} {base_name}" if prefix else base_name
