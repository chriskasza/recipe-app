"""Controlled vocabularies used by the validator. Unknown values become warnings, not errors,
so the user can extend without editing code — but the warning surfaces the typo."""

from __future__ import annotations

from typing import Final

DIETARY_FLAGS: Final[frozenset[str]] = frozenset(
    {
        "vegan",
        "vegetarian",
        "gluten-free",
        "dairy-free",
        "nut-free",
        "low-carb",
        "keto",
        "paleo",
        "pescatarian",
        "halal",
        "kosher",
    }
)

MEAL_TYPES: Final[frozenset[str]] = frozenset(
    {
        "breakfast",
        "brunch",
        "lunch",
        "dinner",
        "snack",
        "dessert",
        "side",
        "drink",
        "sauce",
        "base",
    }
)

UNITS: Final[frozenset[str]] = frozenset(
    {
        # weight
        "g",
        "kg",
        "mg",
        "oz",
        "lb",
        # volume
        "ml",
        "l",
        "tsp",
        "tbsp",
        "cup",
        "fl_oz",
        "pint",
        "quart",
        "gallon",
        # count / shape
        "whole",
        "slice",
        "clove",
        "sprig",
        "bunch",
        "head",
        "stalk",
        "leaf",
        # vague but useful
        "pinch",
        "dash",
        "can",
        "package",
        "jar",
    }
)
