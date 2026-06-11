"""Operator CLI."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from app import __version__
from app.auth import store as auth_store
from app.auth import tokens as auth_tokens
from app.config import load_settings
from app.core.validator import IssueLevel
from app.db import queries, sync
from app.importer.save import RecipePayload, SaveResult, save_recipe, to_report

app = typer.Typer(help="Recipe app operator CLI.", no_args_is_help=True)
console = Console()


@app.command()
def doctor() -> None:
    """Print runtime versions and counts so we can confirm the install."""
    settings = load_settings()
    recipe_count = (
        sum(1 for _ in sync._iter_recipe_files(settings.recipes_dir))
        if settings.recipes_dir.exists()
        else 0
    )
    db_present = settings.db_path.exists()
    db_recipe_count = queries.count_recipes(settings.db_path) if db_present else 0
    fts_rows = queries.count_fts_rows(settings.db_path) if db_present else 0
    last = queries.last_sync_run(settings.db_path) if db_present else None

    table = Table(title="Recipe app doctor")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("app version", __version__)
    table.add_row("python", sys.version.split()[0])
    table.add_row("recipes_dir", str(settings.recipes_dir))
    table.add_row("data_dir", str(settings.data_dir))
    table.add_row("recipe files", str(recipe_count))
    table.add_row("db recipes", str(db_recipe_count))
    table.add_row("fts rows", str(fts_rows))
    table.add_row("last sync", str(last.get("finished_at")) if last else "—")
    console.print(table)


@app.command()
def validate() -> None:
    """Validate every recipe file. Exit nonzero if any has an error-level issue."""
    settings = load_settings()
    results = sync.validate_all(settings.recipes_dir)
    had_error = False
    for path, issues in results:
        if not issues:
            console.print(f"[green]✓[/green] {path.name}")
            continue
        errors = [i for i in issues if i.level is IssueLevel.ERROR]
        warnings = [i for i in issues if i.level is IssueLevel.WARNING]
        color = "red" if errors else "yellow"
        console.print(
            f"[{color}]{'✗' if errors else '⚠'}[/] {path.name} — {len(errors)} error(s), {len(warnings)} warning(s)"
        )
        for issue in issues:
            console.print(f"    {issue}")
        if errors:
            had_error = True
    raise typer.Exit(code=1 if had_error else 0)


@app.command(name="sync")
def sync_command(
    force: Annotated[
        bool, typer.Option("--force", help="Re-upsert every file regardless of mtime")
    ] = False,
) -> None:
    """Sync the corpus into the SQLite mirror."""
    settings = load_settings()
    report = sync.sync_all(settings.recipes_dir, settings.db_path, force=force)
    console.print(
        f"seen={report.files_seen} changed={report.files_changed} removed={report.files_removed} errors={len(report.errors)}"
    )
    for err in report.errors:
        console.print(f"[red]{err}[/red]")
    if report.errors:
        raise typer.Exit(code=1)


@app.command("rebuild-index")
def rebuild_index() -> None:
    """Drop the DB and rebuild from scratch."""
    settings = load_settings()
    report = sync.rebuild_index(settings.recipes_dir, settings.db_path)
    console.print(
        f"rebuilt: seen={report.files_seen} changed={report.files_changed} errors={len(report.errors)}"
    )
    for err in report.errors:
        console.print(f"[red]{err}[/red]")
    if report.errors:
        raise typer.Exit(code=1)


@app.command()
def search(query: str, limit: int = 25) -> None:
    """FTS5 search over the SQLite mirror."""
    settings = load_settings()
    rows = queries.search_recipes(settings.db_path, query, limit=limit)
    if not rows:
        console.print("[dim]no results[/dim]")
        return
    table = Table(title=f"search: {query!r}")
    table.add_column("slug")
    table.add_column("title")
    table.add_column("cuisine")
    table.add_column("min")
    for r in rows:
        table.add_row(
            r.slug,
            r.title,
            r.cuisine or "",
            str(r.total_minutes) if r.total_minutes is not None else "",
        )
    console.print(table)


@app.command()
def show(slug: str) -> None:
    """Pretty-print a recipe from the DB."""
    settings = load_settings()
    row = queries.get_recipe_by_slug(settings.db_path, slug)
    if row is None:
        console.print(f"[red]no recipe with slug {slug!r}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[bold]{row.title}[/bold] ({row.slug})")
    console.print(f"  id: {row.id}")
    console.print(f"  cuisine: {row.cuisine or '—'}")
    console.print(f"  servings: {row.servings or '—'}")
    console.print(
        f"  time: prep={row.prep_minutes or '—'}m cook={row.cook_minutes or '—'}m total={row.total_minutes or '—'}m"
    )
    console.print(f"  file: {row.file_path}")
    console.print(f"  updated: {row.updated_at}")
    tags = queries.list_tags(settings.db_path, row.id)
    if tags:
        console.print(f"  tags: {', '.join(tags)}")
    ingredients = queries.get_ingredients(settings.db_path, row.id)
    console.print("[bold]Ingredients[/bold]")
    for ing in ingredients:
        mark = " (optional)" if ing.optional else ""
        console.print(f"  • {ing.original_text}{mark}")


@app.command("save-recipe")
def save_recipe_command(
    payload_file: Annotated[
        Path | None,
        typer.Argument(metavar="PAYLOAD", help="JSON payload file; reads stdin when omitted."),
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit the machine-readable JSON report.")
    ] = False,
) -> None:
    """Write a recipe from a JSON payload straight into RECIPES_DIR/<slug>.md.

    The payload describes one recipe (the recipe-from-url skill builds it from a fetched
    page); this command renders it through the canonical pipeline and writes a validated,
    byte-stable file into the corpus. Fix any issues afterward from the web UI's edit form.
    """
    raw = payload_file.read_text(encoding="utf-8") if payload_file is not None else sys.stdin.read()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        _emit_save_error({"status": "error", "stage": "json", "message": str(exc)}, json_output)

    try:
        payload = RecipePayload.model_validate(data)
    except ValidationError as exc:
        _emit_save_error({"status": "error", "stage": "build", "message": str(exc)}, json_output)

    settings = load_settings()
    result = save_recipe(payload, settings.recipes_dir)
    report = to_report(result)

    display_path = _relativize(result.path) if result.path is not None else None
    if display_path is not None:
        report["path"] = display_path

    if json_output:
        typer.echo(json.dumps(report, indent=2))
    else:
        _print_save_human(result, display_path)

    if not result.ok:
        raise typer.Exit(code=1)


def _emit_save_error(report: dict[str, Any], json_output: bool) -> NoReturn:
    if json_output:
        typer.echo(json.dumps(report, indent=2))
    else:
        console.print(f"[red]✗ {report['stage']}: {report.get('message', '')}[/red]")
    raise typer.Exit(code=1)


def _relativize(path_str: str) -> str:
    """Show the recipe path relative to the working dir when possible, else absolute."""
    path = Path(path_str)
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return path_str


def _print_save_human(result: SaveResult, display_path: str | None) -> None:
    if result.ok:
        console.print(f"[green]✓[/green] wrote recipe {display_path}")
        console.print(f"  slug: {result.slug}")
        console.print(f"  id:   {result.id}")
        if result.roundtrip_byte_stable is False:
            console.print("  [yellow]⚠ roundtrip not byte-stable[/yellow]")
    else:
        console.print(f"[red]✗ {result.stage}: {result.message or ''}[/red]")
        for err in result.errors:
            console.print(f"  [red]{err}[/red]")
    for warning in result.warnings:
        console.print(f"  [yellow]⚠ {warning}[/yellow]")


@app.command("set-password")
def set_password_command(
    username: Annotated[str | None, typer.Argument(help="Account username.")] = None,
) -> None:
    """Create or update a login account in DATA_DIR/auth.json (outside the DB)."""
    settings = load_settings()
    if username is None:
        username = typer.prompt("Username")
    password = typer.prompt("Password", hide_input=True, confirmation_prompt=True)
    auth_store.set_password(settings.auth_path, username, password)
    console.print(f"[green]✓[/green] set password for {username!r} in {settings.auth_path}")


@app.command("list-users")
def list_users_command() -> None:
    """List login accounts."""
    settings = load_settings()
    users = auth_store.load_users(settings.auth_path)
    if not users:
        console.print("[dim]no users[/dim]")
        return
    for name in sorted(users):
        console.print(name)


@app.command("delete-user")
def delete_user_command(username: str) -> None:
    """Remove a login account."""
    settings = load_settings()
    if auth_store.delete_user(settings.auth_path, username):
        console.print(f"[green]✓[/green] removed {username!r}")
    else:
        console.print(f"[red]no user {username!r}[/red]")
        raise typer.Exit(code=1)


@app.command("create-token")
def create_token_command(
    name: Annotated[str, typer.Argument(help="Name identifying this token.")],
) -> None:
    """Create an API bearer token in DATA_DIR/api_tokens.json. Prints the plaintext once."""
    settings = load_settings()
    try:
        plaintext = auth_tokens.create_token(settings.tokens_path, name)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None
    console.print(f"[green]✓[/green] created token {name!r}:")
    console.print(plaintext)
    console.print("[dim]This value is shown only once — store it securely.[/dim]")


@app.command("list-tokens")
def list_tokens_command() -> None:
    """List API bearer tokens by name and creation time."""
    settings = load_settings()
    tokens = auth_tokens.load_tokens(settings.tokens_path)
    if not tokens:
        console.print("[dim]no tokens[/dim]")
        return
    for name in sorted(tokens):
        console.print(f"{name}\t{tokens[name].get('created_at', '')}")


@app.command("revoke-token")
def revoke_token_command(name: str) -> None:
    """Revoke an API bearer token."""
    settings = load_settings()
    if auth_tokens.revoke_token(settings.tokens_path, name):
        console.print(f"[green]✓[/green] revoked {name!r}")
    else:
        console.print(f"[red]no token {name!r}[/red]")
        raise typer.Exit(code=1)


@app.command("run-dev")
def run_dev(host: str = "127.0.0.1", port: int = 3142) -> None:
    """Run uvicorn in dev mode with autoreload."""
    import uvicorn

    uvicorn.run("app.main:app", host=host, port=port, reload=True)


if __name__ == "__main__":
    app()
