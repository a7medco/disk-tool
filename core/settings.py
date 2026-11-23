"""Tiny settings store next to the app/exe (settings.json)."""
import json
import os

from .paths import DATA

FILE = os.path.join(DATA, "settings.json")


def get(key, default=None):
    try:
        with open(FILE, encoding="utf-8") as f:
            return json.load(f).get(key, default)
    except (OSError, ValueError):
        return default


def put(key, value):
    try:
        with open(FILE, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    d[key] = value
    try:
        with open(FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
    except OSError:
        pass
