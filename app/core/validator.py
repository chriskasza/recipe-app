"""Semantic validation for parsed recipes.

Errors block writes (sync skips the file). Warnings are recorded but don't block —
they cover things like unknown vocabulary terms that the user may legitimately
introduce.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.core.ids import is_ulid, is_valid_slug
from app.core.models import Recipe
from app.core.vocab import DIETARY_FLAGS, MEAL_TYPES, UNITS


class IssueLevel(StrEnum):
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class ValidationIssue:
    level: IssueLevel
    code: str
    message: str
    path: str = ""  # dotted field path within the recipe, e.g. "ingredients[2].unit"

    def __str__(self) -> str:
        loc = f" @ {self.path}" if self.path else ""
        return f"[{self.level.value}] {self.code}: {self.message}{loc}"


def validate_recipe(recipe: Recipe, *, expected_slug: str | None = None) -> list[ValidationIssue]:
    """Return all issues found in ``recipe``. ``expected_slug`` is the filename stem.

    Distinct issue codes let callers filter (e.g. sync only blocks on ``ERROR`` issues).
    """
    issues: list[ValidationIssue] = []

    if not is_ulid(recipe.id):
        issues.append(
            ValidationIssue(
                IssueLevel.ERROR, "id.invalid", "id must be a 26-char ULID", "id"
            )
        )

    if not is_valid_slug(recipe.slug):
        issues.append(
            ValidationIssue(
                IssueLevel.ERROR,
                "slug.invalid",
                "slug must match ^[a-z0-9][a-z0-9-]{0,79}$",
                "slug",
            )
        )
    elif expected_slug is not None and recipe.slug != expected_slug:
        issues.append(
            ValidationIssue(
                IssueLevel.ERROR,
                "slug.mismatch",
                f"slug {recipe.slug!r} does not match filename stem {expected_slug!r}",
                "slug",
            )
        )

    if not recipe.title.strip():
        issues.append(
            ValidationIssue(IssueLevel.ERROR, "title.empty", "title is required", "title")
        )

    for label, value in (
        ("prep_minutes", recipe.prep_minutes),
        ("cook_minutes", recipe.cook_minutes),
        ("total_minutes", recipe.total_minutes),
        ("servings", recipe.servings),
    ):
        if value is not None and value < 0:
            issues.append(
                ValidationIssue(
                    IssueLevel.ERROR, f"{label}.negative", f"{label} must be ≥ 0", label
                )
            )

    if (
        recipe.prep_minutes is not None
        and recipe.cook_minutes is not None
        and recipe.total_minutes is not None
        and recipe.prep_minutes + recipe.cook_minutes != recipe.total_minutes
    ):
        issues.append(
            ValidationIssue(
                IssueLevel.WARNING,
                "time.math",
                f"prep+cook ({recipe.prep_minutes + recipe.cook_minutes}) ≠ total ({recipe.total_minutes})",
                "total_minutes",
            )
        )

    for mt in recipe.meal_type:
        if mt not in MEAL_TYPES:
            issues.append(
                ValidationIssue(
                    IssueLevel.WARNING,
                    "meal_type.unknown",
                    f"unknown meal_type {mt!r}",
                    "meal_type",
                )
            )
    for d in recipe.dietary:
        if d not in DIETARY_FLAGS:
            issues.append(
                ValidationIssue(
                    IssueLevel.WARNING,
                    "dietary.unknown",
                    f"unknown dietary flag {d!r}",
                    "dietary",
                )
            )

    for i, ing in enumerate(recipe.ingredients):
        path_prefix = f"ingredients[{i}]"
        if not ing.name.strip():
            issues.append(
                ValidationIssue(
                    IssueLevel.ERROR,
                    "ingredient.name.empty",
                    "ingredient name is required",
                    f"{path_prefix}.name",
                )
            )
        if not ing.original.strip():
            issues.append(
                ValidationIssue(
                    IssueLevel.ERROR,
                    "ingredient.original.empty",
                    "ingredient original text is required",
                    f"{path_prefix}.original",
                )
            )
        if ing.qty is not None and ing.qty <= 0:
            issues.append(
                ValidationIssue(
                    IssueLevel.WARNING,
                    "ingredient.qty.nonpositive",
                    f"qty should be > 0 (got {ing.qty})",
                    f"{path_prefix}.qty",
                )
            )
        if ing.unit is not None and ing.unit not in UNITS:
            issues.append(
                ValidationIssue(
                    IssueLevel.WARNING,
                    "ingredient.unit.unknown",
                    f"unknown unit {ing.unit!r}",
                    f"{path_prefix}.unit",
                )
            )

    if (
        recipe.source
        and recipe.source.url
        and not recipe.source.url.startswith(("http://", "https://"))
    ):
        issues.append(
            ValidationIssue(
                IssueLevel.WARNING,
                "source.url.scheme",
                "source.url should start with http:// or https://",
                "source.url",
            )
        )

    return issues


def has_errors(issues: list[ValidationIssue]) -> bool:
    return any(i.level is IssueLevel.ERROR for i in issues)
