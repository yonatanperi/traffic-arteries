"""Filesystem "database".

Two JSON files under ``backend/data``:

  * ``routes.json`` — the source of truth: a list of routes (lists of place names).
  * ``graph.json``  — derived adjacency list, rebuilt on every save so the graph
    can be loaded straight from disk without recomputation.

Writes are atomic (temp file + ``os.replace``) so a crash mid-write can never
leave a half-written file. On first access an empty store is initialised.
"""

import json
import os
import tempfile

from . import graph

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
DATA_DIR = os.path.abspath(DATA_DIR)
ROUTES_FILE = os.path.join(DATA_DIR, "routes.json")
GRAPH_FILE = os.path.join(DATA_DIR, "graph.json")


class ValidationError(ValueError):
    """Raised when incoming routes are malformed."""


def _atomic_write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def _read_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def validate_routes(routes):
    """Validate and normalise routes. Returns cleaned routes or raises.

    Rules: ``routes`` is a list; each route is a list of at least two non-empty
    strings. Place names are trimmed of surrounding whitespace.
    """
    if not isinstance(routes, list):
        raise ValidationError("הנתונים חייבים להיות רשימה של מסלולים.")

    cleaned = []
    for index, route in enumerate(routes):
        if not isinstance(route, list):
            raise ValidationError(f"מסלול מספר {index + 1} אינו רשימה.")
        places = []
        for place in route:
            if not isinstance(place, str) or not place.strip():
                raise ValidationError(
                    f"מסלול מספר {index + 1} מכיל שם מקום ריק או לא תקין."
                )
            places.append(place.strip())
        if len(places) < 2:
            raise ValidationError(
                f"מסלול מספר {index + 1} חייב לכלול לפחות שתי נקודות."
            )
        cleaned.append(places)
    return cleaned


def _ensure_files():
    if not os.path.exists(ROUTES_FILE):
        # Start empty; routes are added through the editor.
        _atomic_write_json(ROUTES_FILE, [])
        _rebuild_graph([])
    elif not os.path.exists(GRAPH_FILE):
        # routes exist but graph is missing/stale — rebuild it.
        _rebuild_graph(_read_json(ROUTES_FILE))


def _rebuild_graph(routes):
    adjacency = graph.build_adjacency(routes)
    _atomic_write_json(GRAPH_FILE, adjacency)
    return adjacency


def load_routes():
    _ensure_files()
    return _read_json(ROUTES_FILE)


def load_graph():
    """Load the pre-built adjacency list straight from disk."""
    _ensure_files()
    return _read_json(GRAPH_FILE)


def save_routes(routes):
    """Validate, persist routes, and regenerate the derived graph.

    Returns the cleaned routes that were saved.
    """
    cleaned = validate_routes(routes)
    _atomic_write_json(ROUTES_FILE, cleaned)
    _rebuild_graph(cleaned)
    return cleaned
