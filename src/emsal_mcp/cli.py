from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer

from . import __version__
from .cache import Cache
from .citation import format_legal_citation, verify_legal_citation
from .document import controlled_draft, export_bundle, markdown_to_docx
from .models import Document
from .release import archive_release, compare_history, readiness_dashboard, release_notes, release_smoke, write_history
from .research import refresh_research_bundle, research_quality_dashboard, research_topic
from .safety import build_input_pack, citation_check
from .sources.registry import capabilities, get_source, registry, smoke_all_sync
from .petition import (
    inspect_petition_pack,
    prepare_controlled_petition_draft,
    prepare_drafting_input_pack,
    prepare_petition_outline,
)
from .exporter import prepare_docx_export, prepare_export_package_bundle
from .udf import probe_udf, read_udf, udf_to_markdown, write_udf

app = typer.Typer(help="Emsal-mcp citation-safe hukuk araştırma CLI")
udf_app = typer.Typer(help="UDF okuma/yazma araçları")
release_app = typer.Typer(help="Release smoke/dashboard/history/regression/notes/archive")
cache_app = typer.Typer(help="Cache v2: istatistik, listeleme, arama, yedekleme, import/export")
research_app = typer.Typer(help="Research workflow: topic search, refresh, quality dashboard")
cite_app = typer.Typer(help="Citation verification and formatting")
petition_app = typer.Typer(help="Petition pack: prepare drafting input, inspect packs")
app.add_typer(udf_app, name="udf")
app.add_typer(release_app, name="release")
app.add_typer(cache_app, name="cache")
app.add_typer(research_app, name="research")
app.add_typer(cite_app, name="cite")
app.add_typer(petition_app, name="petition")


def _print(obj, json_out: bool):
    def emit(text: str):
        sys.stdout.buffer.write((text + "\n").encode("utf-8"))
    if json_out:
        emit(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
    else:
        emit(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=2, default=str))


@app.command()
def version():
    typer.echo(__version__)


@app.command()
def sources(json_out: bool = typer.Option(False, "--json")):
    _print(capabilities(), json_out)


@app.command("sources-smoke")
def sources_smoke(
    offline: bool = typer.Option(True, help="Run offline smoke checks"),
    online: bool = typer.Option(False, help="Run online connectivity checks"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Run per-source smoke tests (offline by default, online opt-in)."""
    results = smoke_all_sync(online=online)
    summary = {
        "ok": all(r.get("offline_ok", False) for r in results),
        "online_requested": online,
        "source_count": len(results),
        "sources": results,
    }
    _print(summary, json_out)


@app.command()
def search(source: str, query: str, limit: int = 10, page: int = 1, json_out: bool = typer.Option(False, "--json")):
    import asyncio
    src = get_source(source)
    results = asyncio.run(src.search(query, limit=limit, page=page))
    cache = Cache()
    Cache().set(f"search:{source}:{query}:{limit}:{page}", [r.model_dump(mode="json") for r in results])
    _print([r.model_dump(mode="json") for r in results], json_out)
    cache.close()


@app.command()
def get(source: str, document_id: str, json_out: bool = typer.Option(False, "--json")):
    import asyncio
    doc = asyncio.run(get_source(source).get_document(document_id))
    cache = Cache()
    cache.set(f"doc:{source}:{document_id}", doc.model_dump(mode="json"))
    cache.store_document(doc)
    cache.log("get", {"source": source, "document_id": document_id})
    _print(doc.model_dump(mode="json"), json_out)
    cache.close()


@app.command("citation-check")
def citation_check_cmd(source: str, document_id: str, json_out: bool = typer.Option(False, "--json")):
    import asyncio
    doc = asyncio.run(get_source(source).get_document(document_id))
    _print(citation_check(doc).model_dump(mode="json"), json_out)


@app.command("build-input-pack")
def build_pack(matter: str, issue: str, docs_json: Path, json_out: bool = typer.Option(False, "--json")):
    docs = [Document.model_validate(x) for x in json.loads(docs_json.read_text(encoding="utf-8"))]
    pack = build_input_pack(matter, issue, docs)
    _print(pack.model_dump(mode="json"), json_out)


@app.command("draft-document")
def draft_document(title: str, body_file: Path, docs_json: Optional[Path] = None, out: Optional[Path] = None):
    docs = [Document.model_validate(x) for x in json.loads(docs_json.read_text(encoding="utf-8"))] if docs_json else []
    md = controlled_draft(title, body_file.read_text(encoding="utf-8"), docs)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
        typer.echo(str(out))
    else:
        typer.echo(md)


@app.command("export-docx")
def export_docx(markdown_file: Path, out: Path):
    typer.echo(str(markdown_to_docx(markdown_file.read_text(encoding="utf-8"), out)))


@app.command("export-bundle")
def bundle(matter: str, issue: str, docs_json: Path, out_dir: Path, json_out: bool = typer.Option(False, "--json")):
    docs = [Document.model_validate(x) for x in json.loads(docs_json.read_text(encoding="utf-8"))]
    _print(export_bundle(out_dir, matter=matter, issue=issue, docs=docs), json_out)


@app.command("smoke")
def smoke(offline: bool = True, json_out: bool = typer.Option(False, "--json")):
    result = release_smoke() | {"offline": offline, "sources": list(registry().keys())}
    _print(result, json_out)


# ── Cache subcommands ──────────────────────────────────────────────────────


@cache_app.command("stats")
def cache_stats(cache_path: Optional[Path] = typer.Option(None, help="Cache DB path")):
    """Show cache statistics (document counts, sizes, sources)."""
    cache = Cache(cache_path)
    _print(cache.cache_stats(), json_out=False)
    cache.close()


@cache_app.command("list")
def cache_list(
    source: Optional[str] = typer.Option(None, help="Filter by source"),
    limit: int = typer.Option(50, help="Max results"),
    offset: int = typer.Option(0, help="Offset"),
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
):
    """List cached documents."""
    cache = Cache(cache_path)
    docs = cache.list_cached_documents(source=source, limit=limit, offset=offset)
    _print(docs, json_out=False)
    cache.close()


@cache_app.command("search-local")
def cache_search_local(
    query: str = typer.Option("", help="Free-text search"),
    source: Optional[str] = typer.Option(None),
    court: Optional[str] = typer.Option(None),
    chamber: Optional[str] = typer.Option(None),
    date: Optional[str] = typer.Option(None),
    esas_no: Optional[str] = typer.Option(None),
    karar_no: Optional[str] = typer.Option(None),
    document_id: Optional[str] = typer.Option(None),
    content_status: Optional[str] = typer.Option(None),
    draft_usable: Optional[bool] = typer.Option(None),
    quote_usable: Optional[bool] = typer.Option(None),
    sort: str = typer.Option("relevance"),
    limit: int = typer.Option(20),
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
):
    """Search cached documents locally (no network)."""
    cache = Cache(cache_path)
    results = cache.search_local(
        query=query, source=source, court=court, chamber=chamber, date=date,
        esas_no=esas_no, karar_no=karar_no, document_id=document_id,
        content_status=content_status, draft_usable=draft_usable,
        quote_usable=quote_usable, sort=sort, limit=limit,
    )
    _print(results, json_out=False)
    cache.close()


@cache_app.command("delete")
def cache_delete(
    document_id: str = typer.Argument(..., help="Document ID to delete"),
    source: str = typer.Argument(..., help="Source to delete from"),
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
):
    """Delete a cached document (explicit, destructive)."""
    cache = Cache(cache_path)
    deleted = cache.delete_cached_document(document_id, source)
    typer.echo(f"Deleted: {deleted}")
    cache.close()


@cache_app.command("prune")
def cache_prune(
    max_age_days: int = typer.Option(30, help="Max age in days for search cache entries"),
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
):
    """Prune old search cache entries."""
    cache = Cache(cache_path)
    count = cache.prune_search_cache(max_age_days=max_age_days)
    typer.echo(f"Pruned {count} old search cache entries")
    cache.close()


@cache_app.command("backup")
def cache_backup(
    backup_path: Path = typer.Argument(..., help="Backup destination path"),
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
):
    """Backup the cache database."""
    cache = Cache(cache_path)
    result = cache.backup_cache_with_metadata(backup_path)
    typer.echo(f"Backup created: {result['backup_path']}")
    typer.echo(f"SHA256: {result['sha256']}")
    cache.close()


@cache_app.command("export")
def cache_export(
    export_path: Path = typer.Argument(..., help="Export JSON destination"),
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
):
    """Export cached documents to JSON."""
    cache = Cache(cache_path)
    result = cache.export_json(export_path)
    typer.echo(f"Exported {result['document_count']} documents to: {result['path']}")
    typer.echo(f"SHA256: {result['sha256']}")
    cache.close()


@cache_app.command("import")
def cache_import(
    import_path: Path = typer.Argument(..., help="JSON file to import"),
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
):
    """Import cached documents from JSON."""
    cache = Cache(cache_path)
    result = cache.import_json(import_path)
    typer.echo(f"Imported: {result['imported']}, Skipped: {result['skipped']}, Errors: {result['errors']}")
    cache.close()


# ── Release subcommands ────────────────────────────────────────────────────


@release_app.command("dashboard")
def release_dashboard(json_out: bool = typer.Option(False, "--json")):
    _print(readiness_dashboard(), json_out)


@release_app.command("history")
def release_history(out_dir: Path = Path("exports/release-history"), json_out: bool = typer.Option(False, "--json")):
    _print(write_history(out_dir), json_out)


@release_app.command("compare")
def release_compare(left: Path, right: Path, json_out: bool = typer.Option(False, "--json")):
    _print(compare_history(left, right), json_out)


@release_app.command("notes")
def release_notes_cmd(out: Optional[Path] = None):
    notes = release_notes()
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(notes, encoding="utf-8")
        typer.echo(str(out))
    else:
        sys.stdout.buffer.write((notes + "\n").encode("utf-8"))


@release_app.command("archive")
def release_archive(out_dir: Path = Path("exports/release-archive"), json_out: bool = typer.Option(False, "--json")):
    _print(archive_release(out_dir), json_out)


# ── UDF subcommands ────────────────────────────────────────────────────────


@udf_app.command("probe")
def udf_probe(path: Path, json_out: bool = typer.Option(False, "--json")):
    _print(probe_udf(path), json_out)


@udf_app.command("read")
def udf_read(path: Path):
    sys.stdout.buffer.write((read_udf(path) + "\n").encode("utf-8"))


@udf_app.command("to-md")
def udf_md(path: Path, out: Optional[Path] = None):
    md = udf_to_markdown(path)
    if out:
        out.write_text(md, encoding="utf-8")
        typer.echo(str(out))
    else:
        sys.stdout.buffer.write((md + "\n").encode("utf-8"))


@udf_app.command("write")
def udf_write(text_file: Path, out: Path, title_centered: bool = False):
    typer.echo(str(write_udf(text_file.read_text(encoding="utf-8"), out, title_centered=title_centered)))


# ── Research subcommands ─────────────────────────────────────────────────


@research_app.command("topic")
def research_topic_cmd(
    query: str = typer.Argument(..., help="Research query"),
    sources: Optional[str] = typer.Option(None, help="Comma-separated source_ids"),
    fetch_count: int = typer.Option(5, help="Max docs to fetch"),
    output_dir: Optional[Path] = typer.Option(None, help="Output directory"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Search sources, fetch documents, build research bundle."""
    src_list = [s.strip() for s in sources.split(",")] if sources else None
    result = research_topic(query, src_list, fetch_count=fetch_count, output_dir=output_dir)
    _print(result, json_out)


@research_app.command("refresh")
def research_refresh_cmd(
    bundle_path: Path = typer.Argument(..., help="Path to bundle.json"),
    dry_run: bool = typer.Option(False, help="Compute diff without writing"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Re-run research from an existing bundle, detect new/changed documents."""
    result = refresh_research_bundle(bundle_path, dry_run=dry_run)
    _print(result, json_out)


@research_app.command("dashboard")
def research_dashboard_cmd(
    bundle_path: Path = typer.Argument(..., help="Path to bundle.json"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Compute quality metrics for a research bundle."""
    result = research_quality_dashboard(bundle_path)
    _print(result, json_out)


# ── Citation subcommands ──────────────────────────────────────────────────


@cite_app.command("format")
def cite_format(
    document_id: str = typer.Argument(..., help="Document ID to format"),
    source: str = typer.Option("bedesten", help="Source to look up document"),
    style: str = typer.Option("petition", help="Format style: petition, parenthetical, short"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Format a legal citation from cached document metadata."""
    cache = Cache()
    try:
        # Look up from cache v2
        row = cache.db.execute(
            "SELECT * FROM documents_v2 WHERE document_id=? AND source=?",
            (document_id, source),
        ).fetchone()
        doc_dict = dict(row) if row else {"document_id": document_id, "source": source}
    finally:
        cache.close()

    result = format_legal_citation(doc_dict, style=style)  # type: ignore[arg-type]
    _print(result, json_out)


@cite_app.command("verify")
def cite_verify(
    text: str = typer.Option(None, help="Text to verify"),
    file_path: Path = typer.Option(None, help="File to verify"),
    source: str = typer.Option(None, help="Filter to specific source"),
    limit: int = typer.Option(5, help="Max candidates to extract"),
    fetch: int = typer.Option(3, help="Max docs to fetch"),
    no_live: bool = typer.Option(True, help="Skip live search"),
    min_score: float = typer.Option(1.0, help="Minimum match score"),
    strategy_debug: bool = typer.Option(False, help="Include strategy debug info"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Verify legal citations in text or file."""
    result = verify_legal_citation(
        text=text,
        file_path=file_path,
        source=source,
        limit=limit,
        fetch=fetch,
        no_live=no_live,
        min_score=min_score,
        strategy_debug=strategy_debug,
    )
    _print(result, json_out)


# ── Petition subcommands ────────────────────────────────────────────────────


@petition_app.command("pack")
def petition_pack(
    matter: str = typer.Argument(..., help="Legal matter description"),
    issue: str = typer.Argument(..., help="Legal issue description"),
    docs_json: Optional[Path] = typer.Option(None, help="JSON file with Document list"),
    research_bundle: Optional[Path] = typer.Option(None, help="Research bundle directory"),
    out_dir: Optional[Path] = typer.Option(None, help="Output directory for petition pack"),
    strict: bool = typer.Option(True, help="Strict mode: exclude hash-mismatch docs"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Prepare a petition drafting input pack."""
    docs = []
    if docs_json:
        docs = [Document.model_validate(x) for x in json.loads(docs_json.read_text(encoding="utf-8"))]
    result = prepare_drafting_input_pack(
        matter=matter,
        issue=issue,
        documents=docs,
        research_bundle_dir=str(research_bundle) if research_bundle else None,
        out_dir=str(out_dir) if out_dir else None,
        strict=strict,
    )
    _print(result, json_out)


@petition_app.command("inspect")
def petition_inspect(
    pack_dir: Path = typer.Argument(..., help="Path to petition pack directory"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Inspect and validate a petition pack directory."""
    result = inspect_petition_pack(pack_dir)
    _print(result, json_out)


@petition_app.command("outline")
def petition_outline(
    pack_dir: Path = typer.Argument(..., help="Path to petition pack directory"),
    out_dir: Optional[Path] = typer.Option(None, help="Output directory for outline"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Generate a structured petition outline from a pack."""
    result = prepare_petition_outline(
        pack_dir=pack_dir,
        out_dir=str(out_dir) if out_dir else None,
    )
    _print(result, json_out)


@petition_app.command("draft")
def petition_draft(
    pack_dir: Path = typer.Argument(..., help="Path to petition pack directory"),
    outline_path: Optional[Path] = typer.Option(None, help="Pre-computed outline.json path"),
    out_dir: Optional[Path] = typer.Option(None, help="Output directory for draft"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Generate a controlled petition draft from a pack."""
    result = prepare_controlled_petition_draft(
        pack_dir=pack_dir,
        outline_path=str(outline_path) if outline_path else None,
        out_dir=str(out_dir) if out_dir else None,
    )
    _print(result, json_out)


@petition_app.command("export-docx")
def petition_export_docx(
    draft_path: Optional[Path] = typer.Option(None, help="Path to draft.md"),
    draft_json_path: Optional[Path] = typer.Option(None, help="Path to draft.json"),
    out_path: Optional[Path] = typer.Option(None, help="Output DOCX path"),
    pack_dir: Optional[Path] = typer.Option(None, help="Pack directory for footnotes"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Create a validated DOCX export from a controlled draft."""
    draft_json = None
    if draft_json_path and draft_json_path.exists():
        draft_json = json.loads(draft_json_path.read_text(encoding="utf-8"))
    result = prepare_docx_export(
        draft_path=str(draft_path) if draft_path else None,
        draft_json=draft_json,
        out_path=str(out_path) if out_path else None,
        pack_dir=str(pack_dir) if pack_dir else None,
    )
    _print(result, json_out)


@petition_app.command("export-bundle")
def petition_export_bundle(
    pack_dir: Path = typer.Argument(..., help="Path to petition pack directory"),
    draft_dir: Optional[Path] = typer.Option(None, help="Draft output directory"),
    docx_path: Optional[Path] = typer.Option(None, help="Path to draft.docx"),
    out_dir: Optional[Path] = typer.Option(None, help="Output bundle directory"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Create a complete export package bundle with verification."""
    result = prepare_export_package_bundle(
        pack_dir=pack_dir,
        draft_dir=str(draft_dir) if draft_dir else None,
        docx_path=str(docx_path) if docx_path else None,
        out_dir=str(out_dir) if out_dir else None,
    )
    _print(result, json_out)


if __name__ == "__main__":
    app()
