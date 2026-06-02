from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import typer

from . import __version__

if TYPE_CHECKING:
    pass

# M-52: All domain imports moved to lazy (inside command functions) for
# faster startup.  Only stdlib + typer + __version__ are imported at
# module level so that `emsal-mcp --help` is fast.

app = typer.Typer(help="Emsal-mcp citation-safe hukuk araştırma CLI")
api_app = typer.Typer(help="HTTP REST API server")
udf_app = typer.Typer(help="UDF okuma/yazma araçları")
release_app = typer.Typer(help="Release smoke/dashboard/history/regression/notes/archive")
cache_app = typer.Typer(help="Cache v2: istatistik, listeleme, arama, yedekleme, import/export")
research_app = typer.Typer(help="Research workflow: topic search, refresh, quality dashboard")
cite_app = typer.Typer(help="Citation verification and formatting")
petition_app = typer.Typer(help="Petition pack: prepare drafting input, inspect packs")
argument_app = typer.Typer(help="Argument builder: build chains, score, render")
legislation_app = typer.Typer(help="Mevzuat: ara, belge al, madde ara, gerekçe çıkar")
semantic_app = typer.Typer(help="Semantic search: FTS5 + TF-IDF hybrid, index yönetimi")
chamber_app = typer.Typer(help="Chamber profiling: istatistik, timeline, benzer daire bulma")
graph_app = typer.Typer(help="Citation graph: build, show, citing, cited, stats")
analytics_app = typer.Typer(help="Search analytics: report, empty queries, top queries, source coverage")
template_app = typer.Typer(help="Petition templates: list, show, render")
draft_app = typer.Typer(help="Draft diffing, placeholder tracking, versioning")
export_app = typer.Typer(help="Export formats: plain text, DOCX, PDF, UDF")
circuit_app = typer.Typer(help="Circuit breaker: status, health, reset")
router_app = typer.Typer(help="Capability-based routing: capable sources, search routing, document routing")
pdf_app = typer.Typer(help="PDF content extraction: text layer, toolkit status")
calibrate_app = typer.Typer(help="Source calibration: measure safe request rates")
watch_app = typer.Typer(help="Research watchlist: add, list, run, remove watches")
privacy_app = typer.Typer(help="PII detection, redaction, and privacy audit")
eval_app = typer.Typer(help="Retrieval evaluation: run eval harness, recall@k, nDCG")
app.add_typer(api_app, name="api")
app.add_typer(udf_app, name="udf")
app.add_typer(release_app, name="release")
app.add_typer(cache_app, name="cache")
app.add_typer(research_app, name="research")
app.add_typer(cite_app, name="cite")
app.add_typer(petition_app, name="petition")
app.add_typer(argument_app, name="argument")
app.add_typer(legislation_app, name="legislation")
app.add_typer(semantic_app, name="semantic")
app.add_typer(chamber_app, name="chamber")
app.add_typer(graph_app, name="graph")
app.add_typer(analytics_app, name="analytics")
app.add_typer(template_app, name="template")
app.add_typer(draft_app, name="draft")
app.add_typer(export_app, name="export")
app.add_typer(circuit_app, name="circuit")
app.add_typer(router_app, name="router")
app.add_typer(pdf_app, name="pdf")
app.add_typer(calibrate_app, name="calibrate")
app.add_typer(watch_app, name="watch")
app.add_typer(privacy_app, name="privacy")
app.add_typer(eval_app, name="eval")
query_app = typer.Typer(help="Legal query understanding: norm reference, expand terms, extract filters")
app.add_typer(query_app, name="query")


def _print(obj, json_out: bool):
    """Print output as JSON or plain text to stdout.

    Args:
        obj: Object to print (string or JSON-serializable dict).
        json_out: If True, output as formatted JSON.
    """
    def emit(text: str) -> None:
        sys.stdout.buffer.write((text + "\n").encode("utf-8"))
    if json_out:
        emit(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
    else:
        emit(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=2, default=str))


@app.command()
def version() -> None:
    """Print the current emsal-mcp version."""
    typer.echo(__version__)


@app.command()
def doctor(json_out: bool = typer.Option(False, "--json")) -> None:
    """Run environment diagnostics: Python, cache, sources, UDF toolkit."""
    from .config import config as app_config
    _print(app_config.doctor(), json_out)


@app.command()
def sources(json_out: bool = typer.Option(False, "--json")) -> None:
    """List registered data sources and their capabilities."""
    from .sources.registry import capabilities
    _print(capabilities(), json_out)


@app.command("sources-smoke")
def sources_smoke(
    offline: bool = typer.Option(True, help="Run offline smoke checks"),
    online: bool = typer.Option(False, help="Run online connectivity checks"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Run per-source smoke tests (offline by default, online opt-in)."""
    from .sources.registry import smoke_all_sync
    results = smoke_all_sync(online=online)
    summary = {
        "ok": all(r.get("offline_ok", False) for r in results),
        "online_requested": online,
        "source_count": len(results),
        "sources": results,
    }
    _print(summary, json_out)


@app.command()
def search(source: str, query: str, limit: int = 10, page: int = 1, json_out: bool = typer.Option(False, "--json")) -> None:
    """Search court decisions from a given source."""
    from .cache import Cache
    from .sources.registry import get_source
    import asyncio
    src = get_source(source)
    results = asyncio.run(src.search(query, limit=limit, page=page))
    cache = Cache()
    Cache().set(f"search:{source}:{query}:{limit}:{page}", [r.model_dump(mode="json") for r in results])
    _print([r.model_dump(mode="json") for r in results], json_out)
    cache.close()


@app.command()
def get(source: str, document_id: str, json_out: bool = typer.Option(False, "--json")) -> None:
    """Fetch a single document by ID from the given source."""
    from .cache import Cache
    from .sources.registry import get_source
    from .models import merge_search_metadata
    import asyncio
    doc = asyncio.run(get_source(source).get_document(document_id))
    cache = Cache()
    # M-65: merge cached provenance so standalone get has metadata
    _cached = cache.get_document(document_id, source)
    if _cached and _cached.esas_no:
        merge_search_metadata(doc, _cached)
    cache.set(f"doc:{source}:{document_id}", doc.model_dump(mode="json"))
    cache.store_document(doc)
    cache.log("get", {"source": source, "document_id": document_id})
    _print(doc.model_dump(mode="json"), json_out)
    cache.close()


@app.command("citation-check")
def citation_check_cmd(source: str, document_id: str, json_out: bool = typer.Option(False, "--json")) -> None:
    """Check citation safety of a document from the given source."""
    from .safety import citation_check
    from .sources.registry import get_source
    from .cache import Cache
    from .models import merge_search_metadata
    import asyncio
    doc = asyncio.run(get_source(source).get_document(document_id))
    # M-65: merge cached provenance so standalone citation-check sees metadata
    cache = Cache()
    try:
        _cached = cache.get_document(document_id, source)
        if _cached and _cached.esas_no:
            merge_search_metadata(doc, _cached)
    finally:
        cache.close()
    _print(citation_check(doc).model_dump(mode="json"), json_out)


@app.command("build-input-pack")
def build_pack(matter: str, issue: str, docs_json: Path, json_out: bool = typer.Option(False, "--json")) -> None:
    """Build a citation-safe input pack from a JSON document list."""
    from .models import Document
    from .safety import build_input_pack
    docs = [Document.model_validate(x) for x in json.loads(docs_json.read_text(encoding="utf-8"))]
    pack = build_input_pack(matter, issue, docs)
    _print(pack.model_dump(mode="json"), json_out)


@app.command("draft-document")
def draft_document(title: str, body_file: Path, docs_json: Optional[Path] = None, out: Optional[Path] = None) -> None:
    """Generate a citation-safe markdown draft document."""
    from .document import controlled_draft
    from .models import Document
    docs = [Document.model_validate(x) for x in json.loads(docs_json.read_text(encoding="utf-8"))] if docs_json else []
    md = controlled_draft(title, body_file.read_text(encoding="utf-8"), docs)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
        typer.echo(str(out))
    else:
        typer.echo(md)


@app.command("export-docx")
def export_docx(markdown_file: Path, out: Path) -> None:
    """Export a markdown file to DOCX format."""
    from .document import markdown_to_docx
    typer.echo(str(markdown_to_docx(markdown_file.read_text(encoding="utf-8"), out)))


@app.command("export-bundle")
def bundle(matter: str, issue: str, docs_json: Path, out_dir: Path, json_out: bool = typer.Option(False, "--json")) -> None:
    """Export a citation-safe bundle with input pack and source documents."""
    from .document import export_bundle
    from .models import Document
    docs = [Document.model_validate(x) for x in json.loads(docs_json.read_text(encoding="utf-8"))]
    _print(export_bundle(out_dir, matter=matter, issue=issue, docs=docs), json_out)


@app.command("smoke")
def smoke(offline: bool = True, json_out: bool = typer.Option(False, "--json")) -> None:
    """Run release smoke tests (offline by default)."""
    from .release import release_smoke
    from .sources.registry import registry
    result = release_smoke() | {"offline": offline, "sources": list(registry().keys())}
    _print(result, json_out)


# ── Cache subcommands ──────────────────────────────────────────────────────


@cache_app.command("stats")
def cache_stats(cache_path: Optional[Path] = typer.Option(None, help="Cache DB path")) -> None:
    """Show cache statistics (document counts, sizes, sources)."""
    from .cache import Cache
    cache = Cache(cache_path)
    _print(cache.cache_stats(), json_out=False)
    cache.close()


@cache_app.command("list")
def cache_list(
    source: Optional[str] = typer.Option(None, help="Filter by source"),
    limit: int = typer.Option(50, help="Max results"),
    offset: int = typer.Option(0, help="Offset"),
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
) -> None:
    """List cached documents."""
    from .cache import Cache
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
) -> None:
    """Search cached documents locally (no network)."""
    from .cache import Cache
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
) -> None:
    """Delete a cached document (explicit, destructive)."""
    from .cache import Cache
    cache = Cache(cache_path)
    deleted = cache.delete_cached_document(document_id, source)
    typer.echo(f"Deleted: {deleted}")
    cache.close()


@cache_app.command("prune")
def cache_prune(
    max_age_days: int = typer.Option(30, help="Max age in days for search cache entries"),
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
) -> None:
    """Prune old search cache entries."""
    from .cache import Cache
    cache = Cache(cache_path)
    count = cache.prune_search_cache(max_age_days=max_age_days)
    typer.echo(f"Pruned {count} old search cache entries")
    cache.close()


@cache_app.command("backup")
def cache_backup(
    backup_path: Path = typer.Argument(..., help="Backup destination path"),
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
) -> None:
    """Backup the cache database."""
    from .cache import Cache
    cache = Cache(cache_path)
    result = cache.backup_cache_with_metadata(backup_path)
    typer.echo(f"Backup created: {result['backup_path']}")
    typer.echo(f"SHA256: {result['sha256']}")
    cache.close()


@cache_app.command("export")
def cache_export(
    export_path: Path = typer.Argument(..., help="Export JSON destination"),
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
) -> None:
    """Export cached documents to JSON."""
    from .cache import Cache
    cache = Cache(cache_path)
    result = cache.export_json(export_path)
    typer.echo(f"Exported {result['document_count']} documents to: {result['path']}")
    typer.echo(f"SHA256: {result['sha256']}")
    cache.close()


@cache_app.command("import")
def cache_import(
    import_path: Path = typer.Argument(..., help="JSON file to import"),
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
) -> None:
    """Import cached documents from JSON."""
    from .cache import Cache
    cache = Cache(cache_path)
    result = cache.import_json(import_path)
    typer.echo(f"Imported: {result['imported']}, Skipped: {result['skipped']}, Errors: {result['errors']}")
    cache.close()


@cache_app.command("compact")
def cache_compact(
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Run VACUUM to reclaim space and defragment the cache database."""
    from .cache import Cache
    cache = Cache(cache_path)
    result = cache.vacuum_cache()
    _print(result, json_out)
    cache.close()


@cache_app.command("cleanup-orphans")
def cache_cleanup_orphans(
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Remove orphan rows from search_vectors and documents_v2_fts."""
    from .cache import Cache
    cache = Cache(cache_path)
    result = cache.cleanup_orphans()
    _print(result, json_out)
    cache.close()


@cache_app.command("integrity-check")
def cache_integrity_check(
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Run comprehensive integrity checks on the cache database."""
    from .cache import Cache
    cache = Cache(cache_path)
    result = cache.check_integrity_full()
    _print(result, json_out)
    cache.close()


@cache_app.command("sync")
def cache_sync(
    other_db: Path = typer.Argument(..., help="Path to other cache DB"),
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Sync documents from another cache database (multi-machine merge)."""
    from .cache import Cache
    cache = Cache(cache_path)
    try:
        result = cache.sync_cache(other_db)
        _print(result, json_out)
    finally:
        cache.close()


# ── Dedup subcommands ──────────────────────────────────────────────────────


@cache_app.command("find-duplicates")
def cache_find_duplicates(
    dry_run: bool = typer.Option(False, help="Compute plan without modifying DB"),
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Find duplicate documents across sources (same court+esas_no+karar_no)."""
    from .cache import Cache
    from .dedup import find_duplicates as find_duplicates_impl
    cache = Cache(cache_path)
    try:
        result = find_duplicates_impl(cache=cache, dry_run=dry_run)
        _print(result, json_out)
    finally:
        cache.close()


@cache_app.command("dedup-cluster")
def cache_dedup_cluster(
    document_id: str = typer.Argument(..., help="Document ID to look up"),
    source: str = typer.Option(None, help="Source filter"),
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Find which dedup cluster a document belongs to."""
    from .cache import Cache
    from .dedup import get_dedup_cluster as get_dedup_cluster_impl
    cache = Cache(cache_path)
    try:
        result = get_dedup_cluster_impl(document_id=document_id, source=source or "", cache=cache)
        _print(result, json_out)
    finally:
        cache.close()


@cache_app.command("dedup-stats")
def cache_dedup_stats(
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show deduplication statistics."""
    from .cache import Cache
    from .dedup import get_dedup_stats as get_dedup_stats_impl
    cache = Cache(cache_path)
    try:
        result = get_dedup_stats_impl(cache=cache)
        _print(result, json_out)
    finally:
        cache.close()


@cache_app.command("merge-cluster")
def cache_merge_cluster(
    cluster_id: str = typer.Argument(..., help="Cluster ID to merge"),
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Merge a dedup cluster: enrich canonical record with alternative source URLs."""
    from .cache import Cache
    from .dedup import merge_cluster as merge_cluster_impl
    cache = Cache(cache_path)
    try:
        result = merge_cluster_impl(cluster_id=cluster_id, cache=cache)
        _print(result, json_out)
    finally:
        cache.close()


@cache_app.command("fuzzy-duplicates")
def cache_fuzzy_duplicates(
    provider: Optional[str] = typer.Option(None, help="Embedding provider (default: from config)"),
    threshold: float = typer.Option(0.85, help="Cosine similarity threshold (0.0–1.0)"),
    max_date_diff_days: int = typer.Option(365, help="Max date difference in days"),
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Find fuzzy duplicate candidates using dense embeddings.

    Reports suspected_duplicate pairs — NEVER auto-merges.
    Uses embedding vectors (M-24). Requires build_embedding_index() first.
    """
    from .cache import Cache
    from .dedup import find_fuzzy_duplicates as find_fuzzy_duplicates_impl
    cache = Cache(cache_path)
    try:
        result = find_fuzzy_duplicates_impl(
            cache=cache, provider=provider,
            cosine_threshold=threshold, max_date_diff_days=max_date_diff_days,
        )
        _print(result, json_out)
    finally:
        cache.close()


@cache_app.command("fuzzy-dedup-stats")
def cache_fuzzy_dedup_stats(
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Report fuzzy dedup readiness and embedding availability."""
    from .cache import Cache
    from .dedup import get_fuzzy_dedup_stats as get_fuzzy_dedup_stats_impl
    cache = Cache(cache_path)
    try:
        result = get_fuzzy_dedup_stats_impl(cache=cache)
        _print(result, json_out)
    finally:
        cache.close()


# ── Release subcommands ────────────────────────────────────────────────────


@release_app.command("dashboard")
def release_dashboard(json_out: bool = typer.Option(False, "--json")) -> None:
    """Show release readiness dashboard."""
    from .release import readiness_dashboard
    _print(readiness_dashboard(), json_out)


@release_app.command("history")
def release_history(out_dir: Path = Path("exports/release-history"), json_out: bool = typer.Option(False, "--json")) -> None:
    """Write release history record to output directory."""
    from .release import write_history
    _print(write_history(out_dir), json_out)


@release_app.command("compare")
def release_compare(left: Path, right: Path, json_out: bool = typer.Option(False, "--json")) -> None:
    """Compare two release history records and report score delta."""
    from .release import compare_history
    _print(compare_history(left, right), json_out)


@release_app.command("notes")
def release_notes_cmd(out: Optional[Path] = None) -> None:
    """Generate markdown release notes."""
    from .release import release_notes
    notes = release_notes()
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(notes, encoding="utf-8")
        typer.echo(str(out))
    else:
        sys.stdout.buffer.write((notes + "\n").encode("utf-8"))


@release_app.command("archive")
def release_archive(out_dir: Path = Path("exports/release-archive"), json_out: bool = typer.Option(False, "--json")) -> None:
    """Create a release archive with dashboard, notes, and history."""
    from .release import archive_release
    _print(archive_release(out_dir), json_out)


@release_app.command("command-center")
def release_cmd_center(
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Comprehensive release verification - all checks."""
    from .release import release_command_center as cmd_center_impl
    _print(cmd_center_impl(), json_out)


@release_app.command("version-bump")
def release_version_bump(
    major: bool = typer.Option(False, "--major"),
    minor: bool = typer.Option(False, "--minor"),
    patch: bool = typer.Option(True, "--patch"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Compute next version (does NOT modify files)."""
    from .release import version_bump as version_bump_impl
    _print(version_bump_impl(major=major, minor=minor, patch=patch), json_out)


@release_app.command("v1-readiness")
def release_v1_readiness(
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Final v1.0.0 readiness gate."""
    from .release import final_v1_readiness as final_v1_readiness_impl
    _print(final_v1_readiness_impl(), json_out)


@release_app.command("summary")
def release_summary(
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Human-readable release summary."""
    from .release import generate_release_summary as generate_summary_impl
    _print(generate_summary_impl(), json_out)


# ── UDF subcommands ────────────────────────────────────────────────────────


@udf_app.command("probe")
def udf_probe(path: Path, json_out: bool = typer.Option(False, "--json")) -> None:
    """Probe a UDF file for structure and content metadata."""
    from .udf import probe_udf
    _print(probe_udf(path), json_out)


@udf_app.command("read")
def udf_read(path: Path) -> None:
    """Read and print text content from a UDF file."""
    from .udf import read_udf
    sys.stdout.buffer.write((read_udf(path) + "\n").encode("utf-8"))


@udf_app.command("to-md")
def udf_md(path: Path, out: Optional[Path] = None) -> None:
    """Convert a UDF file to markdown format."""
    from .udf import udf_to_markdown
    md = udf_to_markdown(path)
    if out:
        out.write_text(md, encoding="utf-8")
        typer.echo(str(out))
    else:
        sys.stdout.buffer.write((md + "\n").encode("utf-8"))


@udf_app.command("write")
def udf_write(text_file: Path, out: Path, title_centered: bool = False) -> None:
    """Write a UYAP UDF file from a text file."""
    from .udf import write_udf
    typer.echo(str(write_udf(text_file.read_text(encoding="utf-8"), out, title_centered=title_centered)))


@udf_app.command("status")
def udf_status(json_out: bool = typer.Option(False, "--json")) -> None:
    """Show UDF toolkit availability status."""
    from .udf import get_udf_toolkit_status
    _print(get_udf_toolkit_status(), json_out)


@udf_app.command("authoring-instructions")
def udf_authoring_instructions(
    format: str = typer.Option("json", help="Output format: json or markdown"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show UDF authoring instructions and warnings."""
    from .udf import get_udf_authoring_instructions
    _print(get_udf_authoring_instructions(format=format), json_out)


@udf_app.command("to-docx")
def udf_to_docx_cmd(
    path: Path = typer.Argument(..., help="UDF file to convert"),
    out_path: Optional[Path] = typer.Option(None, help="Output DOCX path"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Convert UDF to DOCX (requires toolkit)."""
    from .udf import convert_udf_to_docx
    _print(convert_udf_to_docx(path, out_path), json_out)


@udf_app.command("to-pdf")
def udf_to_pdf_cmd(
    path: Path = typer.Argument(..., help="UDF file to convert"),
    out_path: Optional[Path] = typer.Option(None, help="Output PDF path"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Convert UDF to PDF (requires toolkit)."""
    from .udf import convert_udf_to_pdf
    _print(convert_udf_to_pdf(path, out_path), json_out)


@udf_app.command("docx-to-udf-experimental")
def udf_docx_to_udf_cmd(
    path: Path = typer.Argument(..., help="DOCX file to convert"),
    out_path: Optional[Path] = typer.Option(None, help="Output UDF path"),
    experimental: bool = typer.Option(False, "--experimental", help="Must be True to proceed"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Convert DOCX to UDF (experimental, requires toolkit)."""
    from .udf import convert_docx_to_udf_experimental
    _print(convert_docx_to_udf_experimental(path, out_path, experimental=experimental), json_out)


# ── Research subcommands ─────────────────────────────────────────────────


@research_app.command("topic")
def research_topic_cmd(
    query: str = typer.Argument(..., help="Research query"),
    sources: Optional[str] = typer.Option(None, help="Comma-separated source_ids"),
    fetch_count: int = typer.Option(5, help="Max docs to fetch"),
    output_dir: Optional[Path] = typer.Option(None, help="Output directory"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Search sources, fetch documents, build research bundle."""
    from .research import research_topic
    src_list = [s.strip() for s in sources.split(",")] if sources else None
    result = research_topic(query, src_list, fetch_count=fetch_count, output_dir=output_dir)
    _print(result, json_out)


@research_app.command("refresh")
def research_refresh_cmd(
    bundle_path: Path = typer.Argument(..., help="Path to bundle.json"),
    dry_run: bool = typer.Option(False, help="Compute diff without writing"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Re-run research from an existing bundle, detect new/changed documents."""
    from .research import refresh_research_bundle
    result = refresh_research_bundle(bundle_path, dry_run=dry_run)
    _print(result, json_out)


@research_app.command("dashboard")
def research_dashboard_cmd(
    bundle_path: Path = typer.Argument(..., help="Path to bundle.json"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Compute quality metrics for a research bundle."""
    from .research import research_quality_dashboard
    result = research_quality_dashboard(bundle_path)
    _print(result, json_out)


# ── Citation subcommands ──────────────────────────────────────────────────


@cite_app.command("format")
def cite_format(
    document_id: str = typer.Argument(..., help="Document ID to format"),
    source: str = typer.Option("bedesten", help="Source to look up document"),
    style: str = typer.Option("petition", help="Format style: petition, parenthetical, short"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Format a legal citation from cached document metadata."""
    from .cache import Cache
    from .citation import format_legal_citation
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
) -> None:
    """Verify legal citations in text or file."""
    from .citation import verify_legal_citation
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
    template: Optional[str] = typer.Option(None, help="Template name (e.g. dava_dilekcesi)"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Prepare a petition drafting input pack."""
    from .models import Document
    from .petition import prepare_drafting_input_pack
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
        template_name=template,
    )
    _print(result, json_out)


@petition_app.command("inspect")
def petition_inspect(
    pack_dir: Path = typer.Argument(..., help="Path to petition pack directory"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Inspect and validate a petition pack directory."""
    from .petition import inspect_petition_pack
    result = inspect_petition_pack(pack_dir)
    _print(result, json_out)


@petition_app.command("outline")
def petition_outline(
    pack_dir: Path = typer.Argument(..., help="Path to petition pack directory"),
    out_dir: Optional[Path] = typer.Option(None, help="Output directory for outline"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Generate a structured petition outline from a pack."""
    from .petition import prepare_petition_outline
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
) -> None:
    """Generate a controlled petition draft from a pack."""
    from .petition import prepare_controlled_petition_draft
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
) -> None:
    """Create a validated DOCX export from a controlled draft."""
    from .exporter import prepare_docx_export
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
) -> None:
    """Create a complete export package bundle with verification."""
    from .exporter import prepare_export_package_bundle
    result = prepare_export_package_bundle(
        pack_dir=pack_dir,
        draft_dir=str(draft_dir) if draft_dir else None,
        docx_path=str(docx_path) if docx_path else None,
        out_dir=str(out_dir) if out_dir else None,
    )
    _print(result, json_out)


@petition_app.command("multi-pack")
def petition_multi_pack(
    matter: str = typer.Argument(..., help="Legal matter description"),
    issues_json: Path = typer.Option(..., help="JSON file with issues list"),
    docs_json: Optional[Path] = typer.Option(None, help="JSON file with shared Document list"),
    out_dir: Optional[Path] = typer.Option(None, help="Output directory for multi-issue pack"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Build a multi-issue petition pack with isolated citation banks."""
    from .models import Document
    from .petition import build_multi_issue_pack
    issues = json.loads(issues_json.read_text(encoding="utf-8"))
    docs = []
    if docs_json:
        docs = [Document.model_validate(x) for x in json.loads(docs_json.read_text(encoding="utf-8"))]
    result = build_multi_issue_pack(
        matter=matter,
        issues=issues,
        documents=docs,
        out_dir=str(out_dir) if out_dir else None,
    )
    _print(result, json_out)


@petition_app.command("multi-inspect")
def petition_multi_inspect(
    pack_dir: Path = typer.Argument(..., help="Path to multi-issue petition pack directory"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Inspect and validate a multi-issue petition pack directory."""
    from .petition import inspect_multi_issue_pack
    result = inspect_multi_issue_pack(pack_dir)
    _print(result, json_out)


# ── Argument subcommands ────────────────────────────────────────────────


@argument_app.command("build")
def argument_build(
    pack_dir: Path = typer.Argument(..., help="Path to petition pack directory"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Build structured argument chains from a petition pack."""
    from .argument import build_argument_chain
    result = build_argument_chain(pack_dir=pack_dir)
    _print(result, json_out)


@argument_app.command("score")
def argument_score(
    pack_dir: Path = typer.Argument(..., help="Path to petition pack directory"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Score argument strength for a petition pack."""
    from .argument import get_argument_strength_report
    result = get_argument_strength_report(pack_dir=pack_dir)
    _print(result, json_out)


@argument_app.command("render")
def argument_render(
    pack_dir: Path = typer.Argument(..., help="Path to petition pack directory"),
    out_path: Optional[Path] = typer.Option(None, help="Output markdown file path"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Render argument chains as markdown."""
    from .argument import render_arguments_to_markdown
    md = render_arguments_to_markdown(pack_dir=pack_dir, out_path=out_path)
    if out_path:
        _print({"ok": True, "out_path": str(out_path), "length": len(md)}, json_out)
    else:
        sys.stdout.buffer.write((md + "\n").encode("utf-8"))


# ── Legislation subcommands ──────────────────────────────────────────


@legislation_app.command("search")
def legislation_search(
    query: str = typer.Argument(..., help="Arama sorgusu"),
    legislation_type: Optional[str] = typer.Option(None, help="Mevzuat türü (Kanun, Yönetmelik, ...)"),
    limit: int = typer.Option(10, help="Maksimum sonuç"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Mevzuat ara."""
    from .legislation import search_legislation as search_leg_impl
    result = search_leg_impl(query=query, legislation_type=legislation_type, limit=limit)
    _print(result, json_out)


@legislation_app.command("get")
def legislation_get(
    document_id: str = typer.Argument(..., help="Mevzuat belge ID"),
    source: Optional[str] = typer.Option(None, help="Kaynak (varsayılan: mevzuat)"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Mevzuat belgesi getir."""
    from .legislation import get_legislation_document as get_leg_doc_impl
    result = get_leg_doc_impl(document_id=document_id, source=source)
    _print(result, json_out)


@legislation_app.command("articles")
def legislation_articles(
    document_id: str = typer.Argument(..., help="Mevzuat belge ID"),
    article_number: Optional[str] = typer.Option(None, help="Belirli bir madde numarası"),
    article_query: Optional[str] = typer.Option(None, help="Madde metninde anahtar kelime"),
    source: Optional[str] = typer.Option(None, help="Kaynak (varsayılan: mevzuat)"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Belge içinde madde ara."""
    from .legislation import search_legislation_articles as search_leg_articles_impl
    result = search_leg_articles_impl(
        document_id=document_id,
        article_number=article_number,
        article_query=article_query,
        source=source,
    )
    _print(result, json_out)


@legislation_app.command("tree")
def legislation_tree(
    document_id: str = typer.Argument(..., help="Mevzuat belge ID"),
    source: Optional[str] = typer.Option(None, help="Kaynak (varsayılan: mevzuat)"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Belgenin kısım/bölüm/madde ağacını çıkar."""
    from .legislation import get_legislation_article_tree as get_leg_article_tree_impl
    result = get_leg_article_tree_impl(document_id=document_id, source=source)
    _print(result, json_out)


@legislation_app.command("gerekce")
def legislation_gerekce(
    document_id: str = typer.Argument(..., help="Mevzuat belge ID"),
    source: Optional[str] = typer.Option(None, help="Kaynak (varsayılan: mevzuat)"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Genel gerekçe ve madde gerekçelerini çıkar."""
    from .legislation import get_legislation_gerekce as get_leg_gerekce_impl
    result = get_leg_gerekce_impl(document_id=document_id, source=source)
    _print(result, json_out)


@legislation_app.command("status")
def legislation_status(
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Mevzuat kaynak sağlık durumu."""
    from .legislation import get_legislation_source_status as get_leg_status_impl
    result = get_leg_status_impl()
    _print(result, json_out)


@legislation_app.command("types")
def legislation_types(
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Bilinen mevzuat türlerini listele."""
    from .legislation import get_legislation_types as get_leg_types_impl
    result = get_leg_types_impl()
    _print(result, json_out)


@legislation_app.command("format")
def legislation_format(
    title: str = typer.Option("", help="Mevzuat başlığı"),
    legislation_no: str = typer.Option("", help="Mevzuat numarası"),
    gazette_date: str = typer.Option("", help="Resmi Gazete tarihi"),
    style: str = typer.Option("full", help="Stil: full, short, article"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Mevzuat atıf formatla."""
    from .legislation import format_legislation_citation as format_leg_citation_impl
    doc = {
        "title": title,
        "legislation_no": legislation_no,
        "gazette_date": gazette_date,
    }
    result = format_leg_citation_impl(doc, style=style)  # type: ignore[arg-type]
    _print(result, json_out)


# ── Semantic search subcommands ──────────────────────────────────────────────


@semantic_app.command("index")
def semantic_index(
    force_rebuild: bool = typer.Option(False, "--force-rebuild", help="Drop and recreate indices"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Build FTS5 + TF-IDF search indices."""
    from .semantic import build_semantic_index as build_semantic_impl
    result = build_semantic_impl(force_rebuild=force_rebuild)
    _print(result, json_out)


@semantic_app.command("search")
def semantic_search_cmd(
    query: str = typer.Argument(..., help="Arama sorgusu"),
    limit: int = typer.Option(10, help="Maksimum sonuç"),
    source: Optional[str] = typer.Option(None, help="Kaynak filtresi (örn: yargitay)"),
    court: Optional[str] = typer.Option(None, help="Mahkeme filtresi"),
    chamber: Optional[str] = typer.Option(None, help="Daire filtresi"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """TF-IDF cosine similarity search. Supports --source, --court, --chamber filters."""
    from .semantic import semantic_search as semantic_search_cli_impl
    filters = {}
    if source:
        filters["source"] = source
    if court:
        filters["court"] = court
    if chamber:
        filters["chamber"] = chamber
    result = semantic_search_cli_impl(query=query, limit=limit, filters=filters or None)
    _print(result, json_out)


@semantic_app.command("hybrid")
def semantic_hybrid(
    query: str = typer.Argument(..., help="Arama sorgusu"),
    limit: int = typer.Option(10, help="Maksimum sonuç"),
    weight: float = typer.Option(0.6, help="Hybrid ağırlık (0.0=sadece semantic, 1.0=sadece BM25)"),
    w_dense: float = typer.Option(0.0, help="Dense embedding ağırlığı"),
    rerank: bool = typer.Option(False, "--rerank", help="Cross-encoder rerank uygula"),
    rrf: bool = typer.Option(False, "--rrf", help="RRF (Reciprocal Rank Fusion) kullan"),
    dense: bool = typer.Option(False, "--dense", help="Dense embeddings'i RRF'e dahil et"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """FTS5 BM25 + TF-IDF cosine hybrid search (RRF opsiyonuyla)."""
    if rrf:
        from .semantic import hybrid_search_rrf
        result = hybrid_search_rrf(query=query, limit=limit, include_dense=dense)
    else:
        from .semantic import hybrid_search as _hybrid_search
        result = _hybrid_search(query=query, limit=limit, hybrid_weight=weight, dense_weight=w_dense, rerank=rerank)
    _print(result, json_out)


@semantic_app.command("status")
def semantic_status(
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Check index health and statistics."""
    from .semantic import get_index_status as index_status_impl
    result = index_status_impl()
    _print(result, json_out)


@semantic_app.command("rebuild")
def semantic_rebuild(
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Force rebuild all search indices."""
    from .semantic import rebuild_index as rebuild_impl
    result = rebuild_impl()
    _print(result, json_out)


@semantic_app.command("embed-index")
def semantic_embed_index(
    provider: Optional[str] = typer.Option(None, help="Provider: local-hash-v1 or fastembed-minilm-l6-v2"),
    force_rebuild: bool = typer.Option(False, "--force-rebuild"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Build dense embedding index."""
    from .semantic import build_embedding_index as build_embedding_impl
    result = build_embedding_impl(provider=provider, force_rebuild=force_rebuild)
    _print(result, json_out)


@semantic_app.command("embed-search")
def semantic_embed_search(
    query: str = typer.Argument(..., help="Arama sorgusu"),
    provider: Optional[str] = typer.Option(None),
    limit: int = typer.Option(10),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Dense embedding similarity search."""
    from .semantic import embedding_search as embedding_search_impl
    result = embedding_search_impl(query=query, limit=limit, provider=provider)
    _print(result, json_out)


@semantic_app.command("providers")
def semantic_providers(
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """List available embedding providers."""
    from .embeddings import list_embedding_providers

    _print(list_embedding_providers(), json_out)


@semantic_app.command("embedding-status")
def semantic_embedding_status(
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Check dense embedding index status."""
    from .semantic import get_embedding_index_status as embedding_status_impl
    result = embedding_status_impl()
    _print(result, json_out)


@semantic_app.command("update-indexes")
def semantic_update_indexes(
    provider: Optional[str] = typer.Option(None, help="Embedding provider for dense index"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Incrementally update indexes (new/changed docs only)."""
    from .semantic import update_indexes as update_indexes_impl
    result = update_indexes_impl(provider=provider)
    _print(result, json_out)


@semantic_app.command("sync-status")
def semantic_sync_status(
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Check index sync status."""
    from .semantic import get_index_sync_status as sync_status_impl
    result = sync_status_impl()
    _print(result, json_out)


# ── Chamber profiling subcommands ────────────────────────────────────────────


@chamber_app.command("overview")
def chamber_overview(
    court: Optional[str] = typer.Option(None, help="Mahkeme filtresi (örn: Yargitay)"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Chamber overview with document counts and date ranges."""
    from .chamber import get_chamber_overview as chamber_overview_impl
    result = chamber_overview_impl(court=court)
    _print(result, json_out)


@chamber_app.command("profile")
def chamber_profile(
    chamber: str = typer.Argument(..., help="Daire adı (örn: '3. Hukuk Dairesi')"),
    court: Optional[str] = typer.Option(None, help="Mahkeme filtresi"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Detailed profile of a specific chamber."""
    from .chamber import profile_chamber as profile_chamber_impl
    result = profile_chamber_impl(chamber=chamber, court=court)
    _print(result, json_out)


@chamber_app.command("timeline")
def chamber_timeline_cmd(
    chamber: Optional[str] = typer.Option(None, help="Daire adı"),
    court: Optional[str] = typer.Option(None, help="Mahkeme filtresi"),
    start_year: Optional[int] = typer.Option(None, help="Başlangıç yılı"),
    end_year: Optional[int] = typer.Option(None, help="Bitiş yılı"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Decision timeline grouped by year."""
    from .chamber import chamber_timeline as chamber_timeline_impl
    result = chamber_timeline_impl(
        chamber=chamber, court=court,
        start_year=start_year, end_year=end_year,
    )
    _print(result, json_out)


@chamber_app.command("similar")
def chamber_similar(
    chamber: str = typer.Argument(..., help="Hedef daire adı"),
    court: Optional[str] = typer.Option(None, help="Mahkeme filtresi"),
    limit: int = typer.Option(5, help="Maksimum benzer daire sayısı"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Find chambers with similar topic profiles."""
    from .chamber import find_similar_chambers as find_similar_impl
    result = find_similar_impl(chamber=chamber, court=court, limit=limit)
    _print(result, json_out)


# ── Citation graph subcommands ──────────────────────────────────────────────


@graph_app.command("build")
def graph_build(
    limit_docs: int = typer.Option(100, help="Maksimum işlenecek belge sayısı"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Build citation graph from cached documents."""
    from .citation_graph import build_citation_graph as build_citation_graph_impl
    result = build_citation_graph_impl(limit_docs=limit_docs)
    _print(result, json_out)


@graph_app.command("show")
def graph_show(
    document_id: str = typer.Argument(..., help="Belge ID"),
    source: str = typer.Option("bedesten", help="Kaynak"),
    direction: str = typer.Option("both", help="Yön: both, citing, cited"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show citation relationships for a document."""
    from .citation_graph import get_citation_graph as get_citation_graph_impl
    result = get_citation_graph_impl(document_id=document_id, source=source, direction=direction)
    _print(result, json_out)


@graph_app.command("citing")
def graph_citing(
    document_id: str = typer.Argument(..., help="Atıf alan belge ID"),
    source: str = typer.Option("bedesten", help="Kaynak"),
    limit: int = typer.Option(20, help="Maksimum sonuç"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Find documents that cite the given document."""
    from .citation_graph import find_citing_documents as find_citing_documents_impl
    result = find_citing_documents_impl(document_id=document_id, source=source, limit=limit)
    _print(result, json_out)


@graph_app.command("cited")
def graph_cited(
    document_id: str = typer.Argument(..., help="Atıf yapan belge ID"),
    source: str = typer.Option("bedesten", help="Kaynak"),
    limit: int = typer.Option(20, help="Maksimum sonuç"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Find documents that the given document cites."""
    from .citation_graph import find_cited_documents as find_cited_documents_impl
    result = find_cited_documents_impl(document_id=document_id, source=source, limit=limit)
    _print(result, json_out)


@graph_app.command("stats")
def graph_stats(
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Citation graph istatistikleri."""
    from .citation_graph import get_citation_graph_stats as get_citation_graph_stats_impl
    result = get_citation_graph_stats_impl()
    _print(result, json_out)


@graph_app.command("export")
def graph_export(
    format: str = typer.Option("json", help="Export format: json, dot, mermaid"),
    document_id: Optional[str] = typer.Option(None, help="Optional document_id for sub-graph export"),
    source: Optional[str] = typer.Option(None, help="Source filter for sub-graph"),
    max_depth: int = typer.Option(2, help="Max traversal depth for sub-graph"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Export citation graph in various formats (json, dot, mermaid)."""
    from .citation_graph import export_graph as export_graph_impl
    result = export_graph_impl(
        format=format,
        document_id=document_id,
        source=source,
        max_depth=max_depth,
    )
    _print(result, json_out)


# ── Analytics subcommands ────────────────────────────────────────────────


@analytics_app.command("report")
def analytics_report(
    days: int = typer.Option(30, help="Number of days to include"),
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Comprehensive search analytics report."""
    from .cache import Cache
    from .search_analytics import get_search_analytics

    cache = Cache(cache_path)
    try:
        result = get_search_analytics(cache=cache, days=days)
        _print(result, json_out)
    finally:
        cache.close()


@analytics_app.command("empty-queries")
def analytics_empty_queries(
    limit: int = typer.Option(20, help="Max results"),
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """List queries that returned 0 results."""
    from .cache import Cache
    from .search_analytics import get_empty_queries

    cache = Cache(cache_path)
    try:
        result = get_empty_queries(cache=cache, limit=limit)
        _print(result, json_out)
    finally:
        cache.close()


@analytics_app.command("top-queries")
def analytics_top_queries(
    limit: int = typer.Option(20, help="Max results"),
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Most frequent queries."""
    from .cache import Cache
    from .search_analytics import get_top_queries

    cache = Cache(cache_path)
    try:
        result = get_top_queries(cache=cache, limit=limit)
        _print(result, json_out)
    finally:
        cache.close()


@analytics_app.command("source-coverage")
def analytics_source_coverage(
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Source coverage: doc counts and full_text percentage."""
    from .cache import Cache
    from .search_analytics import get_source_coverage

    cache = Cache(cache_path)
    try:
        result = get_source_coverage(cache=cache)
        _print(result, json_out)
    finally:
        cache.close()


# ── Template subcommands ────────────────────────────────────────────────────


@template_app.command("list")
def template_list(json_out: bool = typer.Option(False, "--json")) -> None:
    """List all available petition templates."""
    from .templates import list_templates as list_templates_impl
    _print(list_templates_impl(), json_out)


@template_app.command("show")
def template_show(
    name: str = typer.Argument(..., help="Template name (e.g. dava_dilekcesi)"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show details of a specific petition template."""
    from .templates import get_template as get_template_impl
    _print(get_template_impl(name), json_out)


@template_app.command("render")
def template_render(
    name: str = typer.Argument(..., help="Template name (e.g. dava_dilekcesi)"),
    out_path: Optional[Path] = typer.Option(None, help="Output file path (default: stdout)"),
) -> None:
    """Render a template as a draft-skeleton.md compatible markdown."""
    from .templates import render_template_to_skeleton as render_template_impl
    try:
        md = render_template_impl(name)
    except KeyError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
        typer.echo(str(out_path))
    else:
        sys.stdout.buffer.write((md + "\n").encode("utf-8"))


# ── Draft diff / versioning subcommands (M-14) ──────────────────────────────


@draft_app.command("diff")
def draft_diff(
    draft_a: Path = typer.Argument(..., help="Path to first (older) draft"),
    draft_b: Path = typer.Argument(..., help="Path to second (newer) draft"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Compare two draft files and show changes."""
    from .draft_diff import diff_drafts as diff_drafts_impl
    result = diff_drafts_impl(draft_a, draft_b)
    _print(result, json_out)


@draft_app.command("placeholders")
def draft_placeholders(
    draft_path: Path = typer.Argument(..., help="Path to draft file"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Analyze placeholder fill status in a draft."""
    from .draft_diff import track_placeholders as track_placeholders_impl
    result = track_placeholders_impl(draft_path)
    _print(result, json_out)


@draft_app.command("fill-report")
def draft_fill_report(
    draft_path: Path = typer.Argument(..., help="Path to draft file"),
    pack_dir: Optional[Path] = typer.Option(None, help="Petition pack directory for source suggestions"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Generate a fill report: what still needs attention."""
    from .draft_diff import get_fill_report as get_fill_report_impl
    result = get_fill_report_impl(draft_path, pack_dir=str(pack_dir) if pack_dir else None)
    _print(result, json_out)


@draft_app.command("save-version")
def draft_save_version(
    draft_dir: Path = typer.Argument(..., help="Directory containing draft files"),
    label: Optional[str] = typer.Option(None, help="Human-readable version label"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Save a snapshot of current draft state for later diff."""
    from .draft_diff import save_draft_version as save_draft_version_impl
    result = save_draft_version_impl(draft_dir, version_label=label)
    _print(result, json_out)


# ── Export format subcommands (M-15) ────────────────────────────────────────


@export_app.command("txt")
def export_txt(
    draft_path: Path = typer.Argument(..., help="Path to draft.md"),
    out_path: Optional[Path] = typer.Option(None, help="Output .txt path"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Export a draft to plain-text format (always available, no toolkit)."""
    from .exporter import export_plain_text
    result = export_plain_text(
        draft_path=str(draft_path),
        out_path=str(out_path) if out_path else None,
    )
    _print(result, json_out)


@export_app.command("format")
def export_format_cmd(
    draft_path: Path = typer.Argument(..., help="Path to draft.md"),
    format: str = typer.Option("docx", help="Export format: docx, txt, pdf, udf"),
    out_path: Optional[Path] = typer.Option(None, help="Output file path"),
    pack_dir: Optional[Path] = typer.Option(None, help="Pack directory for footnotes"),
    experimental: bool = typer.Option(False, "--experimental", help="Required for UDF format"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Unified export dispatcher: docx, txt, pdf, udf."""
    from .exporter import export_to_format
    result = export_to_format(
        draft_path=str(draft_path),
        format=format,
        out_path=str(out_path) if out_path else None,
        pack_dir=str(pack_dir) if pack_dir else None,
        experimental=experimental,
    )
    _print(result, json_out)


@export_app.command("capabilities")
def export_capabilities_cmd(
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show which export formats are currently available."""
    from .exporter import get_export_capabilities
    _print(get_export_capabilities(), json_out)


# ── Circuit breaker subcommands ──────────────────────────────────────────────


@circuit_app.command("status")
def circuit_status_cmd(
    source: Optional[str] = typer.Option(None, help="Filter by source_id"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show circuit breaker status for one or all sources."""
    from .circuit import get_source_health, get_all_sources_health
    if source:
        health = get_source_health(source)
        _print(health, json_out)
    else:
        all_health = get_all_sources_health()
        _print(all_health, json_out)


@circuit_app.command("health")
def circuit_health_cmd(
    source: Optional[str] = typer.Option(None, help="Filter by source_id"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show source health metrics (uptime, failure counts, circuit state)."""
    from .circuit import get_source_health, get_all_sources_health
    if source:
        health = get_source_health(source)
        _print(health, json_out)
    else:
        all_health = get_all_sources_health()
        _print(all_health, json_out)


@circuit_app.command("reset")
def circuit_reset_cmd(
    source: str = typer.Argument(..., help="Source ID to reset"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Manually reset a circuit breaker to CLOSED state."""
    from .circuit import reset_circuit
    result = reset_circuit(source)
    _print(result, json_out)


# ── Router subcommands (M-19) ────────────────────────────────────────────────


@router_app.command("capable-sources")
def router_capable_sources(
    capability: str = typer.Argument(..., help="Capability name (e.g. full_text, search, pdf_link)"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """List source_ids that support a given capability."""
    from .router import get_capable_sources as get_capable_sources_impl
    _print(get_capable_sources_impl(capability), json_out)


@router_app.command("search")
def router_search_cmd(
    query: str = typer.Argument(..., help="Search query"),
    require: Optional[str] = typer.Option(None, help="Comma-separated required capabilities"),
    prefer: Optional[str] = typer.Option(None, help="Comma-separated preferred sources"),
    exclude: Optional[str] = typer.Option(None, help="Comma-separated sources to exclude"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Route a search request to capable sources."""
    from .router import route_search as route_search_impl
    required = [c.strip() for c in require.split(",")] if require else None
    preferred = [s.strip() for s in prefer.split(",")] if prefer else None
    excluded = [s.strip() for s in exclude.split(",")] if exclude else None
    _print(route_search_impl(query, required_capabilities=required, preferred_sources=preferred, exclude_sources=excluded), json_out)


@router_app.command("get-document")
def router_get_document_cmd(
    document_id: str = typer.Argument(..., help="Document ID"),
    require: Optional[str] = typer.Option(None, help="Comma-separated required capabilities"),
    preferred_source: Optional[str] = typer.Option(None, help="Preferred source"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Route a get_document request to capable sources."""
    from .router import route_get_document as route_get_document_impl
    required = [c.strip() for c in require.split(",")] if require else None
    _print(route_get_document_impl(document_id, required_capabilities=required, preferred_source=preferred_source), json_out)


# ── PDF extraction subcommands (M-27) ──────────────────────────────────────


@pdf_app.command("extract")
def pdf_extract(
    path: Path = typer.Argument(..., help="Path to PDF file"),
    ocr: bool = typer.Option(False, "--ocr", help="Enable OCR (opt-in, low confidence)"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Extract text layer from a PDF file."""
    from .pdf_extractor import extract_pdf_text_from_file
    _print(extract_pdf_text_from_file(str(path), ocr_enabled=ocr), json_out)


@pdf_app.command("toolkit-status")
def pdf_toolkit(
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Check PDF extraction toolkit availability."""
    from .pdf_extractor import get_pdf_toolkit_status
    _print(get_pdf_toolkit_status(), json_out)


@pdf_app.command("promote")
def pdf_promote(
    document_json: str = typer.Argument(..., help="Document JSON string"),
    ocr: bool = typer.Option(False, "--ocr", help="Enable OCR"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Try to promote a pdf_only Document to full_text."""
    from .pdf_extractor import promote_pdf_to_full_text as promote_pdf_impl
    import json as json_mod
    doc = json_mod.loads(document_json)
    _print(promote_pdf_impl(doc, ocr_enabled=ocr), json_out)


# ── Calibrate subcommands (M-30) ──────────────────────────────────────────


@calibrate_app.command("source")
def calibrate_source_cmd(
    source_id: str = typer.Argument(..., help="Source ID to calibrate"),
    online: bool = typer.Option(False, "--online", help="Make actual HTTP calls"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Measure safe request rate for a source."""
    from .calibrate import calibrate_source as calibrate_source_impl
    _print(calibrate_source_impl(source_id, online=online), json_out)


@calibrate_app.command("all")
def calibrate_all_cmd(
    online: bool = typer.Option(False, "--online", help="Make actual HTTP calls"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Calibrate all registered sources."""
    from .calibrate import calibrate_all as calibrate_all_impl
    _print(calibrate_all_impl(online=online), json_out)


# ── API server subcommands (M-33) ─────────────────────────────────────────


@api_app.command("serve")
def api_serve(
    host: str = typer.Option("127.0.0.1", help="Bind address"),
    port: int = typer.Option(8765, help="Bind port"),
    token: Optional[str] = typer.Option(None, help="Auth token (overrides EMSAL_API_TOKEN env)"),
) -> None:
    """Start HTTP REST API server (read-only, stdlib only)."""
    from .api_server import run_api_server

    run_api_server(host=host, port=port, token=token)


# ── Benchmark (M-31) ───────────────────────────────────────────────────────


@app.command("benchmark")
def benchmark_cmd(
    corpus_size: int = typer.Option(50, help="Synthetic corpus size"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Run micro-benchmark suite (deterministic corpus)."""
    from .benchmark import run_benchmarks as run_benchmarks_impl
    _print(run_benchmarks_impl(corpus_size=corpus_size), json_out)


@app.command("error-catalog")
def error_catalog(
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """List all known error codes used in the codebase."""
    from .server_utils import get_error_codes

    _print(get_error_codes(), json_out)


# ── Research Watchlist subcommands (M-36) ─────────────────────────────────


@watch_app.command("add")
def watch_add(
    name: str = typer.Argument(..., help="Unique watch name"),
    query: str = typer.Argument(..., help="Research query"),
    sources: Optional[str] = typer.Option(None, help="Comma-separated source_ids"),
    fetch_count: int = typer.Option(5, help="Max docs to fetch per run"),
    interval_hours: int = typer.Option(24, help="Suggested interval in hours"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Register a watch for periodic research."""
    from .research_watch import add_watch as add_watch_impl
    src_list = [s.strip() for s in sources.split(",")] if sources else None
    result = add_watch_impl(
        name=name, query=query, sources=src_list,
        fetch_count=fetch_count, interval_hours=interval_hours,
    )
    _print(result, json_out)


@watch_app.command("list")
def watch_list(
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """List all registered watches."""
    from .research_watch import list_watches as list_watches_impl
    _print(list_watches_impl(), json_out)


@watch_app.command("run")
def watch_run(
    name: str = typer.Argument(..., help="Watch name to execute"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Execute a watch: re-search, detect new/changed docs."""
    from .research_watch import run_watch as run_watch_impl
    _print(run_watch_impl(name), json_out)


@watch_app.command("remove")
def watch_remove(
    name: str = typer.Argument(..., help="Watch name to remove"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Remove a watch."""
    from .research_watch import remove_watch as remove_watch_impl
    _print(remove_watch_impl(name), json_out)


# ── Privacy / PII subcommands (M-37) ────────────────────────────────────


@privacy_app.command("scan")
def privacy_scan(
    text: str = typer.Argument(..., help="Text to scan for PII"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Scan text for potential PII (TCKN, phone, email)."""
    from .privacy import scan_pii as scan_pii_impl
    _print(scan_pii_impl(text), json_out)


@privacy_app.command("redact")
def privacy_redact(
    text: str = typer.Argument(..., help="Text to redact PII from"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Redact PII from text. Returns copy — original unchanged."""
    from .privacy import redact_pii as redact_pii_impl
    _print(redact_pii_impl(text), json_out)


@privacy_app.command("audit")
def privacy_audit(
    path: Path = typer.Argument(..., help="File or directory to audit for PII"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Audit a file or directory for PII presence."""
    from .privacy import audit_privacy as audit_privacy_impl
    _print(audit_privacy_impl(path), json_out)


# ── Eval commands ────────────────────────────────────────────────────────────


@eval_app.command("run")
def eval_run(
    golden_path: str | None = typer.Option(None, help="Path to golden_queries.json"),
    k: int = typer.Option(5, help="Cutoff rank for recall@k / nDCG@k"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Run evaluation harness against golden query set."""
    from .eval_metrics import evaluate_search
    from .semantic import hybrid_search
    result = evaluate_search(search_fn=hybrid_search, golden_path=golden_path, k_default=k)
    _print(result, json_out)


# ── Query understanding commands (M-70) ──────────────────────────────────────


@query_app.command("norm")
def query_norm(
    query: str = typer.Argument(..., help="Sorgu metni"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Normalize law references in query (İYUK 11 → 2577 s.K. m.11)."""
    from .query_understanding import normalize_law_ref
    _print(normalize_law_ref(query), json_out)


@query_app.command("expand")
def query_expand(
    query: str = typer.Argument(..., help="Sorgu metni"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Expand query with legal synonyms."""
    from .query_understanding import expand_query_terms
    _print(expand_query_terms(query), json_out)


@query_app.command("extract-filters")
def query_extract(
    query: str = typer.Argument(..., help="Sorgu metni"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Extract court/chamber filters from query text."""
    from .query_understanding import extract_query_filters
    _print(extract_query_filters(query), json_out)


if __name__ == "__main__":
    app()
