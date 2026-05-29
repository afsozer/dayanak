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
from .release import (
    archive_release,
    compare_history,
    final_v1_readiness as final_v1_readiness_impl,
    generate_release_summary as generate_summary_impl,
    readiness_dashboard,
    release_command_center as cmd_center_impl,
    release_notes,
    release_smoke,
    version_bump as version_bump_impl,
    write_history,
)
from .research import refresh_research_bundle, research_quality_dashboard, research_topic
from .safety import build_input_pack, citation_check
from .sources.registry import capabilities, get_source, registry, smoke_all_sync
from .petition import (
    build_multi_issue_pack,
    inspect_multi_issue_pack,
    inspect_petition_pack,
    prepare_controlled_petition_draft,
    prepare_drafting_input_pack,
    prepare_petition_outline,
)
from .argument import (
    build_argument_chain,
    get_argument_strength_report,
    render_arguments_to_markdown,
)
from .draft_diff import (
    diff_drafts as diff_drafts_impl,
    get_fill_report as get_fill_report_impl,
    save_draft_version as save_draft_version_impl,
    track_placeholders as track_placeholders_impl,
)
from .templates import (
    get_template as get_template_impl,
    list_templates as list_templates_impl,
    render_template_to_skeleton as render_template_impl,
)
from .legislation import (
    format_legislation_citation as format_leg_citation_impl,
    get_legislation_article_tree as get_leg_article_tree_impl,
    get_legislation_document as get_leg_doc_impl,
    get_legislation_gerekce as get_leg_gerekce_impl,
    get_legislation_source_status as get_leg_status_impl,
    get_legislation_types as get_leg_types_impl,
    search_legislation as search_leg_impl,
    search_legislation_articles as search_leg_articles_impl,
)
from .semantic import (
    build_semantic_index as build_semantic_impl,
    get_index_status as index_status_impl,
    hybrid_search as hybrid_search_impl,
    rebuild_index as rebuild_impl,
    semantic_search as semantic_search_cli_impl,
    build_embedding_index as build_embedding_impl,
    embedding_search as embedding_search_impl,
    get_embedding_index_status as embedding_status_impl,
)
from .chamber import (
    chamber_timeline as chamber_timeline_impl,
    find_similar_chambers as find_similar_impl,
    get_chamber_overview as chamber_overview_impl,
    profile_chamber as profile_chamber_impl,
)
from .citation_graph import (
    build_citation_graph as build_citation_graph_impl,
    find_cited_documents as find_cited_documents_impl,
    find_citing_documents as find_citing_documents_impl,
    get_citation_graph as get_citation_graph_impl,
    get_citation_graph_stats as get_citation_graph_stats_impl,
)
from .dedup import (
    find_duplicates as find_duplicates_impl,
    get_dedup_cluster as get_dedup_cluster_impl,
    get_dedup_stats as get_dedup_stats_impl,
    merge_cluster as merge_cluster_impl,
)
from .exporter import (
    export_plain_text,
    export_to_format,
    get_export_capabilities,
    prepare_docx_export,
    prepare_export_package_bundle,
)
from .udf import (
    convert_docx_to_udf_experimental,
    convert_udf_to_docx,
    convert_udf_to_pdf,
    get_udf_authoring_instructions,
    get_udf_toolkit_status,
    probe_udf,
    read_udf,
    udf_to_markdown,
    write_udf,
)
from .circuit import (
    get_all_sources_health,
    get_source_health,
    reset_circuit,
)
from .router import (
    get_capable_sources as get_capable_sources_impl,
    route_get_document as route_get_document_impl,
    route_search as route_search_impl,
)

app = typer.Typer(help="Emsal-mcp citation-safe hukuk araştırma CLI")
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
def doctor(json_out: bool = typer.Option(False, "--json")):
    """Run environment diagnostics: Python, cache, sources, UDF toolkit."""
    from .config import config as app_config
    _print(app_config.doctor(), json_out)


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


@cache_app.command("compact")
def cache_compact(
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Run VACUUM to reclaim space and defragment the cache database."""
    cache = Cache(cache_path)
    result = cache.vacuum_cache()
    _print(result, json_out)
    cache.close()


@cache_app.command("cleanup-orphans")
def cache_cleanup_orphans(
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Remove orphan rows from search_vectors and documents_v2_fts."""
    cache = Cache(cache_path)
    result = cache.cleanup_orphans()
    _print(result, json_out)
    cache.close()


@cache_app.command("integrity-check")
def cache_integrity_check(
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Run comprehensive integrity checks on the cache database."""
    cache = Cache(cache_path)
    result = cache.check_integrity_full()
    _print(result, json_out)
    cache.close()


# ── Dedup subcommands ──────────────────────────────────────────────────────


@cache_app.command("find-duplicates")
def cache_find_duplicates(
    dry_run: bool = typer.Option(False, help="Compute plan without modifying DB"),
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Find duplicate documents across sources (same court+esas_no+karar_no)."""
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
):
    """Find which dedup cluster a document belongs to."""
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
):
    """Show deduplication statistics."""
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
):
    """Merge a dedup cluster: enrich canonical record with alternative source URLs."""
    cache = Cache(cache_path)
    try:
        result = merge_cluster_impl(cluster_id=cluster_id, cache=cache)
        _print(result, json_out)
    finally:
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


@release_app.command("command-center")
def release_cmd_center(
    json_out: bool = typer.Option(False, "--json"),
):
    """Comprehensive release verification - all checks."""
    _print(cmd_center_impl(), json_out)


@release_app.command("version-bump")
def release_version_bump(
    major: bool = typer.Option(False, "--major"),
    minor: bool = typer.Option(False, "--minor"),
    patch: bool = typer.Option(True, "--patch"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Compute next version (does NOT modify files)."""
    _print(version_bump_impl(major=major, minor=minor, patch=patch), json_out)


@release_app.command("v1-readiness")
def release_v1_readiness(
    json_out: bool = typer.Option(False, "--json"),
):
    """Final v1.0.0 readiness gate."""
    _print(final_v1_readiness_impl(), json_out)


@release_app.command("summary")
def release_summary(
    json_out: bool = typer.Option(False, "--json"),
):
    """Human-readable release summary."""
    _print(generate_summary_impl(), json_out)


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


@udf_app.command("status")
def udf_status(json_out: bool = typer.Option(False, "--json")):
    """Show UDF toolkit availability status."""
    _print(get_udf_toolkit_status(), json_out)


@udf_app.command("authoring-instructions")
def udf_authoring_instructions(
    format: str = typer.Option("json", help="Output format: json or markdown"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Show UDF authoring instructions and warnings."""
    _print(get_udf_authoring_instructions(format=format), json_out)


@udf_app.command("to-docx")
def udf_to_docx_cmd(
    path: Path = typer.Argument(..., help="UDF file to convert"),
    out_path: Optional[Path] = typer.Option(None, help="Output DOCX path"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Convert UDF to DOCX (requires toolkit)."""
    _print(convert_udf_to_docx(path, out_path), json_out)


@udf_app.command("to-pdf")
def udf_to_pdf_cmd(
    path: Path = typer.Argument(..., help="UDF file to convert"),
    out_path: Optional[Path] = typer.Option(None, help="Output PDF path"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Convert UDF to PDF (requires toolkit)."""
    _print(convert_udf_to_pdf(path, out_path), json_out)


@udf_app.command("docx-to-udf-experimental")
def udf_docx_to_udf_cmd(
    path: Path = typer.Argument(..., help="DOCX file to convert"),
    out_path: Optional[Path] = typer.Option(None, help="Output UDF path"),
    experimental: bool = typer.Option(False, "--experimental", help="Must be True to proceed"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Convert DOCX to UDF (experimental, requires toolkit)."""
    _print(convert_docx_to_udf_experimental(path, out_path, experimental=experimental), json_out)


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
    template: Optional[str] = typer.Option(None, help="Template name (e.g. dava_dilekcesi)"),
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
        template_name=template,
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


@petition_app.command("multi-pack")
def petition_multi_pack(
    matter: str = typer.Argument(..., help="Legal matter description"),
    issues_json: Path = typer.Option(..., help="JSON file with issues list"),
    docs_json: Optional[Path] = typer.Option(None, help="JSON file with shared Document list"),
    out_dir: Optional[Path] = typer.Option(None, help="Output directory for multi-issue pack"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Build a multi-issue petition pack with isolated citation banks."""
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
):
    """Inspect and validate a multi-issue petition pack directory."""
    result = inspect_multi_issue_pack(pack_dir)
    _print(result, json_out)


# ── Argument subcommands ────────────────────────────────────────────────


@argument_app.command("build")
def argument_build(
    pack_dir: Path = typer.Argument(..., help="Path to petition pack directory"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Build structured argument chains from a petition pack."""
    result = build_argument_chain(pack_dir=pack_dir)
    _print(result, json_out)


@argument_app.command("score")
def argument_score(
    pack_dir: Path = typer.Argument(..., help="Path to petition pack directory"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Score argument strength for a petition pack."""
    result = get_argument_strength_report(pack_dir=pack_dir)
    _print(result, json_out)


@argument_app.command("render")
def argument_render(
    pack_dir: Path = typer.Argument(..., help="Path to petition pack directory"),
    out_path: Optional[Path] = typer.Option(None, help="Output markdown file path"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Render argument chains as markdown."""
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
):
    """Mevzuat ara."""
    result = search_leg_impl(query=query, legislation_type=legislation_type, limit=limit)
    _print(result, json_out)


@legislation_app.command("get")
def legislation_get(
    document_id: str = typer.Argument(..., help="Mevzuat belge ID"),
    source: Optional[str] = typer.Option(None, help="Kaynak (varsayılan: mevzuat)"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Mevzuat belgesi getir."""
    result = get_leg_doc_impl(document_id=document_id, source=source)
    _print(result, json_out)


@legislation_app.command("articles")
def legislation_articles(
    document_id: str = typer.Argument(..., help="Mevzuat belge ID"),
    article_number: Optional[str] = typer.Option(None, help="Belirli bir madde numarası"),
    article_query: Optional[str] = typer.Option(None, help="Madde metninde anahtar kelime"),
    source: Optional[str] = typer.Option(None, help="Kaynak (varsayılan: mevzuat)"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Belge içinde madde ara."""
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
):
    """Belgenin kısım/bölüm/madde ağacını çıkar."""
    result = get_leg_article_tree_impl(document_id=document_id, source=source)
    _print(result, json_out)


@legislation_app.command("gerekce")
def legislation_gerekce(
    document_id: str = typer.Argument(..., help="Mevzuat belge ID"),
    source: Optional[str] = typer.Option(None, help="Kaynak (varsayılan: mevzuat)"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Genel gerekçe ve madde gerekçelerini çıkar."""
    result = get_leg_gerekce_impl(document_id=document_id, source=source)
    _print(result, json_out)


@legislation_app.command("status")
def legislation_status(
    json_out: bool = typer.Option(False, "--json"),
):
    """Mevzuat kaynak sağlık durumu."""
    result = get_leg_status_impl()
    _print(result, json_out)


@legislation_app.command("types")
def legislation_types(
    json_out: bool = typer.Option(False, "--json"),
):
    """Bilinen mevzuat türlerini listele."""
    result = get_leg_types_impl()
    _print(result, json_out)


@legislation_app.command("format")
def legislation_format(
    title: str = typer.Option("", help="Mevzuat başlığı"),
    legislation_no: str = typer.Option("", help="Mevzuat numarası"),
    gazette_date: str = typer.Option("", help="Resmi Gazete tarihi"),
    style: str = typer.Option("full", help="Stil: full, short, article"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Mevzuat atıf formatla."""
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
):
    """Build FTS5 + TF-IDF search indices."""
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
):
    """TF-IDF cosine similarity search. Supports --source, --court, --chamber filters."""
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
    w_dense: float = typer.Option(0.0, "--w-dense", help="Dense embedding ağırlık (0.0=devre dışı)"),
    source: Optional[str] = typer.Option(None, help="Kaynak filtresi (örn: yargitay)"),
    court: Optional[str] = typer.Option(None, help="Mahkeme filtresi"),
    chamber: Optional[str] = typer.Option(None, help="Daire filtresi"),
    json_out: bool = typer.Option(False, "--json"),
):
    """FTS5 BM25 + TF-IDF cosine hybrid search with optional dense embeddings."""
    filters = {}
    if source:
        filters["source"] = source
    if court:
        filters["court"] = court
    if chamber:
        filters["chamber"] = chamber
    result = hybrid_search_impl(
        query=query, limit=limit, hybrid_weight=weight,
        dense_weight=w_dense if w_dense > 0 else None,
        filters=filters or None,
    )
    _print(result, json_out)


@semantic_app.command("status")
def semantic_status(
    json_out: bool = typer.Option(False, "--json"),
):
    """Check index health and statistics."""
    result = index_status_impl()
    _print(result, json_out)


@semantic_app.command("rebuild")
def semantic_rebuild(
    json_out: bool = typer.Option(False, "--json"),
):
    """Force rebuild all search indices."""
    result = rebuild_impl()
    _print(result, json_out)


@semantic_app.command("embed-index")
def semantic_embed_index(
    provider: Optional[str] = typer.Option(None, help="Provider: local-hash-v1 or fastembed-minilm-l6-v2"),
    force_rebuild: bool = typer.Option(False, "--force-rebuild"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Build dense embedding index."""
    result = build_embedding_impl(provider=provider, force_rebuild=force_rebuild)
    _print(result, json_out)


@semantic_app.command("embed-search")
def semantic_embed_search(
    query: str = typer.Argument(..., help="Arama sorgusu"),
    provider: Optional[str] = typer.Option(None),
    limit: int = typer.Option(10),
    json_out: bool = typer.Option(False, "--json"),
):
    """Dense embedding similarity search."""
    result = embedding_search_impl(query=query, limit=limit, provider=provider)
    _print(result, json_out)


@semantic_app.command("providers")
def semantic_providers(
    json_out: bool = typer.Option(False, "--json"),
):
    """List available embedding providers."""
    from .embeddings import list_embedding_providers

    _print(list_embedding_providers(), json_out)


@semantic_app.command("embedding-status")
def semantic_embedding_status(
    json_out: bool = typer.Option(False, "--json"),
):
    """Check dense embedding index status."""
    result = embedding_status_impl()
    _print(result, json_out)


# ── Chamber profiling subcommands ────────────────────────────────────────────


@chamber_app.command("overview")
def chamber_overview(
    court: Optional[str] = typer.Option(None, help="Mahkeme filtresi (örn: Yargitay)"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Chamber overview with document counts and date ranges."""
    result = chamber_overview_impl(court=court)
    _print(result, json_out)


@chamber_app.command("profile")
def chamber_profile(
    chamber: str = typer.Argument(..., help="Daire adı (örn: '3. Hukuk Dairesi')"),
    court: Optional[str] = typer.Option(None, help="Mahkeme filtresi"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Detailed profile of a specific chamber."""
    result = profile_chamber_impl(chamber=chamber, court=court)
    _print(result, json_out)


@chamber_app.command("timeline")
def chamber_timeline_cmd(
    chamber: Optional[str] = typer.Option(None, help="Daire adı"),
    court: Optional[str] = typer.Option(None, help="Mahkeme filtresi"),
    start_year: Optional[int] = typer.Option(None, help="Başlangıç yılı"),
    end_year: Optional[int] = typer.Option(None, help="Bitiş yılı"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Decision timeline grouped by year."""
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
):
    """Find chambers with similar topic profiles."""
    result = find_similar_impl(chamber=chamber, court=court, limit=limit)
    _print(result, json_out)


# ── Citation graph subcommands ──────────────────────────────────────────────


@graph_app.command("build")
def graph_build(
    limit_docs: int = typer.Option(100, help="Maksimum işlenecek belge sayısı"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Build citation graph from cached documents."""
    result = build_citation_graph_impl(limit_docs=limit_docs)
    _print(result, json_out)


@graph_app.command("show")
def graph_show(
    document_id: str = typer.Argument(..., help="Belge ID"),
    source: str = typer.Option("bedesten", help="Kaynak"),
    direction: str = typer.Option("both", help="Yön: both, citing, cited"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Show citation relationships for a document."""
    result = get_citation_graph_impl(document_id=document_id, source=source, direction=direction)
    _print(result, json_out)


@graph_app.command("citing")
def graph_citing(
    document_id: str = typer.Argument(..., help="Atıf alan belge ID"),
    source: str = typer.Option("bedesten", help="Kaynak"),
    limit: int = typer.Option(20, help="Maksimum sonuç"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Find documents that cite the given document."""
    result = find_citing_documents_impl(document_id=document_id, source=source, limit=limit)
    _print(result, json_out)


@graph_app.command("cited")
def graph_cited(
    document_id: str = typer.Argument(..., help="Atıf yapan belge ID"),
    source: str = typer.Option("bedesten", help="Kaynak"),
    limit: int = typer.Option(20, help="Maksimum sonuç"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Find documents that the given document cites."""
    result = find_cited_documents_impl(document_id=document_id, source=source, limit=limit)
    _print(result, json_out)


@graph_app.command("stats")
def graph_stats(
    json_out: bool = typer.Option(False, "--json"),
):
    """Citation graph istatistikleri."""
    result = get_citation_graph_stats_impl()
    _print(result, json_out)


# ── Analytics subcommands ────────────────────────────────────────────────


@analytics_app.command("report")
def analytics_report(
    days: int = typer.Option(30, help="Number of days to include"),
    cache_path: Optional[Path] = typer.Option(None, help="Cache DB path"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Comprehensive search analytics report."""
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
):
    """List queries that returned 0 results."""
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
):
    """Most frequent queries."""
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
):
    """Source coverage: doc counts and full_text percentage."""
    from .search_analytics import get_source_coverage

    cache = Cache(cache_path)
    try:
        result = get_source_coverage(cache=cache)
        _print(result, json_out)
    finally:
        cache.close()


# ── Template subcommands ────────────────────────────────────────────────────


@template_app.command("list")
def template_list(json_out: bool = typer.Option(False, "--json")):
    """List all available petition templates."""
    _print(list_templates_impl(), json_out)


@template_app.command("show")
def template_show(
    name: str = typer.Argument(..., help="Template name (e.g. dava_dilekcesi)"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Show details of a specific petition template."""
    _print(get_template_impl(name), json_out)


@template_app.command("render")
def template_render(
    name: str = typer.Argument(..., help="Template name (e.g. dava_dilekcesi)"),
    out_path: Optional[Path] = typer.Option(None, help="Output file path (default: stdout)"),
):
    """Render a template as a draft-skeleton.md compatible markdown."""
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
):
    """Compare two draft files and show changes."""
    result = diff_drafts_impl(draft_a, draft_b)
    _print(result, json_out)


@draft_app.command("placeholders")
def draft_placeholders(
    draft_path: Path = typer.Argument(..., help="Path to draft file"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Analyze placeholder fill status in a draft."""
    result = track_placeholders_impl(draft_path)
    _print(result, json_out)


@draft_app.command("fill-report")
def draft_fill_report(
    draft_path: Path = typer.Argument(..., help="Path to draft file"),
    pack_dir: Optional[Path] = typer.Option(None, help="Petition pack directory for source suggestions"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Generate a fill report: what still needs attention."""
    result = get_fill_report_impl(draft_path, pack_dir=str(pack_dir) if pack_dir else None)
    _print(result, json_out)


@draft_app.command("save-version")
def draft_save_version(
    draft_dir: Path = typer.Argument(..., help="Directory containing draft files"),
    label: Optional[str] = typer.Option(None, help="Human-readable version label"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Save a snapshot of current draft state for later diff."""
    result = save_draft_version_impl(draft_dir, version_label=label)
    _print(result, json_out)


# ── Export format subcommands (M-15) ────────────────────────────────────────


@export_app.command("txt")
def export_txt(
    draft_path: Path = typer.Argument(..., help="Path to draft.md"),
    out_path: Optional[Path] = typer.Option(None, help="Output .txt path"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Export a draft to plain-text format (always available, no toolkit)."""
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
):
    """Unified export dispatcher: docx, txt, pdf, udf."""
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
):
    """Show which export formats are currently available."""
    _print(get_export_capabilities(), json_out)


# ── Circuit breaker subcommands ──────────────────────────────────────────────


@circuit_app.command("status")
def circuit_status_cmd(
    source: Optional[str] = typer.Option(None, help="Filter by source_id"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Show circuit breaker status for one or all sources."""
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
):
    """Show source health metrics (uptime, failure counts, circuit state)."""
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
):
    """Manually reset a circuit breaker to CLOSED state."""
    result = reset_circuit(source)
    _print(result, json_out)


# ── Router subcommands (M-19) ────────────────────────────────────────────────


@router_app.command("capable-sources")
def router_capable_sources(
    capability: str = typer.Argument(..., help="Capability name (e.g. full_text, search, pdf_link)"),
    json_out: bool = typer.Option(False, "--json"),
):
    """List source_ids that support a given capability."""
    _print(get_capable_sources_impl(capability), json_out)


@router_app.command("search")
def router_search_cmd(
    query: str = typer.Argument(..., help="Search query"),
    require: Optional[str] = typer.Option(None, help="Comma-separated required capabilities"),
    prefer: Optional[str] = typer.Option(None, help="Comma-separated preferred sources"),
    exclude: Optional[str] = typer.Option(None, help="Comma-separated sources to exclude"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Route a search request to capable sources."""
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
):
    """Route a get_document request to capable sources."""
    required = [c.strip() for c in require.split(",")] if require else None
    _print(route_get_document_impl(document_id, required_capabilities=required, preferred_source=preferred_source), json_out)


if __name__ == "__main__":
    app()
