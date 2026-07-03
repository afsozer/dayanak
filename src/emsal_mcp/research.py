"""v0.5 Research workflow: search, fetch, bundle, refresh, quality dashboard.

No fabricated metadata; all data sourced from real source clients or injected
fake clients. Tests inject ``sources_override`` to avoid live network calls.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cache import Cache
from .models import ContentStatus, Document, SearchResult, merge_search_metadata


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def _hash_bundle(data: dict[str, Any]) -> str:
    blob = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _safe_filename(name: str) -> str:
    return re.sub(r'[^\w\-.]', '_', name)[:120]


# ---------------------------------------------------------------------------
# research_topic
# ---------------------------------------------------------------------------

INDEX_MANUAL_START = "<!-- MANUAL_NOTES_START -->"
INDEX_MANUAL_END = "<!-- MANUAL_NOTES_END -->"


def research_topic(
    query: str,
    sources: list[str] | None = None,
    *,
    fetch_count: int = 5,
    filters: dict[str, Any] | None = None,
    output_dir: str | Path | None = None,
    sources_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Search sources, fetch documents, build output directory bundle.

    Args:
        query: Research query string.
        sources: List of source_ids to query.  Defaults to all registered
            sources with ``supports_search=True``.
        fetch_count: Max documents to fetch per search result.
        filters: Optional search filters forwarded to source.search().
        output_dir: Directory to write the bundle into.  If None a temp-like
            dir is derived from the query hash.
        sources_override: Optional dict mapping source_id to a source client
            instance.  When provided these are used *instead* of the real
            registry, enabling tests to inject fakes.

    Returns:
        Bundle metadata dict (also written as bundle.json).
    """
    from .sources.registry import get_source, registry

    filters = filters or {}
    now = datetime.now(timezone.utc).isoformat()

    # Resolve sources
    reg = registry()
    effective_override = sources_override or {}
    if sources is not None:
        active_sources = [s for s in sources if s in reg or s in effective_override]
    else:
        active_sources = [sid for sid, cli in reg.items() if getattr(cli, '_supports_search', True)]
        # Also include any override sources not in real registry
        for sid in effective_override:
            if sid not in active_sources:
                active_sources.append(sid)

    # Resolve source clients (allow injection)
    source_clients: dict[str, Any] = {}
    for sid in active_sources:
        if sid in effective_override:
            source_clients[sid] = effective_override[sid]
        else:
            source_clients[sid] = get_source(sid)

    # --- Phase 1: Search ---
    all_results: list[SearchResult] = []
    search_errors: list[str] = []
    for sid, client in source_clients.items():
        try:
            from .concurrency import run_sync
            results = run_sync(client.search(query, limit=fetch_count, **filters))
            all_results.extend(results)
        except Exception as exc:
            search_errors.append(f"{sid}: {exc}")

    result_count = len(all_results)

    # --- Phase 2: Fetch documents ---
    fetched_documents: list[Document] = []
    fetch_warnings: list[str] = []
    for sr in all_results[:fetch_count]:
        client = source_clients.get(sr.source)
        if client is None:
            continue
        try:
            from .concurrency import run_sync
            doc = run_sync(client.get_document(sr.document_id))
            # Carry structured search metadata (esas/karar/date/court) into the
            # fetched document; getDocumentContent returns content-only for some
            # sources, which otherwise blocks citation_check despite full text.
            merge_search_metadata(doc, sr)
            fetched_documents.append(doc)
        except Exception as exc:
            fetch_warnings.append(f"fetch {sr.source}:{sr.document_id}: {exc}")

    fetched_count = len(fetched_documents)

    # --- Phase 3: Content status summary ---
    status_counter: Counter[str] = Counter()
    citation_safe_count = 0
    metadata_only_count = 0
    for doc in fetched_documents:
        status_counter[doc.content_status.value] += 1
        text = doc.full_text or doc.markdown or ""
        if doc.content_status in {ContentStatus.FULL_TEXT, ContentStatus.HTML_MARKDOWN} and text.strip():
            citation_safe_count += 1
        else:
            metadata_only_count += 1

    content_status_summary = dict(status_counter)

    # --- Phase 4: Store in cache ---
    cache = Cache()
    for doc in fetched_documents:
        try:
            cache.store_document(doc)
        except Exception as exc:
            fetch_warnings.append(f"cache store {doc.source}:{doc.document_id}: {exc}")
    cache.close()

    # --- Phase 5: Build output directory ---
    out = Path(output_dir) if output_dir else Path(".emsal_research") / _hash_text(query)[:12]
    out.mkdir(parents=True, exist_ok=True)
    (out / "documents").mkdir(exist_ok=True)

    generated_files: list[str] = []

    # Write each document as markdown
    for doc in fetched_documents:
        fname = _safe_filename(f"{doc.source}_{doc.document_id}") + ".md"
        doc_path = out / "documents" / fname
        parts = [
            f"# {doc.title or doc.document_id}",
            "",
            f"- **Source**: {doc.source}",
            f"- **Document ID**: {doc.document_id}",
        ]
        if doc.court:
            parts.append(f"- **Court**: {doc.court}")
        if doc.chamber:
            parts.append(f"- **Chamber**: {doc.chamber}")
        if doc.decision_date:
            parts.append(f"- **Decision Date**: {doc.decision_date}")
        if doc.esas_no:
            parts.append(f"- **Esas No**: {doc.esas_no}")
        if doc.karar_no:
            parts.append(f"- **Karar No**: {doc.karar_no}")
        if doc.source_url:
            parts.append(f"- **Source URL**: {doc.source_url}")
        parts.append(f"- **Content Status**: {doc.content_status.value}")
        parts.append(f"- **Citation Safe**: {'Yes' if doc.quote_usable else 'No'}")
        parts.append("")
        if doc.text:
            parts.append("## Content")
            parts.append("")
            parts.append(doc.text)
        doc_path.write_text("\n".join(parts), encoding="utf-8")
        generated_files.append(f"documents/{fname}")

    # results.json
    results_data = [sr.model_dump(mode="json") for sr in all_results]
    (out / "results.json").write_text(
        json.dumps(results_data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    generated_files.append("results.json")

    # hash-manifest.json
    manifest: dict[str, str] = {}
    for doc in fetched_documents:
        text = doc.full_text or doc.markdown or ""
        if text.strip():
            manifest[f"{doc.source}:{doc.document_id}"] = _hash_text(text)
    (out / "manifests").mkdir(exist_ok=True)
    (out / "manifests" / "hash-manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    generated_files.append("manifests/hash-manifest.json")

    # warnings.json
    warnings = list(search_errors) + list(fetch_warnings)
    (out / "warnings.json").write_text(
        json.dumps(warnings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    generated_files.append("warnings.json")

    # bundle.json
    bundle_data: dict[str, Any] = {
        "version": "0.5.0",
        "query": query,
        "sources": active_sources,
        "filters": filters,
        "fetch_count": fetch_count,
        "result_count": result_count,
        "fetched_count": fetched_count,
        "content_status_summary": content_status_summary,
        "citation_safe_count": citation_safe_count,
        "metadata_only_count": metadata_only_count,
        "generated_files": generated_files,
        "warnings": warnings,
        "hash": "",
        "created_at": now,
    }
    bundle_data["hash"] = _hash_bundle(bundle_data)
    (out / "bundle.json").write_text(
        json.dumps(bundle_data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    generated_files.append("bundle.json")

    # index.md
    index_lines = [
        f"# Research: {query}",
        "",
        f"- **Created**: {now}",
        f"- **Sources**: {', '.join(active_sources)}",
        f"- **Results**: {result_count}",
        f"- **Fetched**: {fetched_count}",
        f"- **Citation Safe**: {citation_safe_count}",
        f"- **Metadata Only**: {metadata_only_count}",
        "",
        "## Documents",
        "",
    ]
    for doc in fetched_documents:
        fname = _safe_filename(f"{doc.source}_{doc.document_id}") + ".md"
        label = doc.citation_label()
        index_lines.append(f"- [{label}](documents/{fname})")
    index_lines.extend(["", "## Warnings", ""])
    for w in warnings:
        index_lines.append(f"- {w}")
    if not warnings:
        index_lines.append("- None")
    index_lines.extend([
        "",
        "## Recommended Next Steps",
        "",
    ])
    if metadata_only_count > 0:
        index_lines.append("- Some documents are metadata-only; verify from official sources before quoting.")
    if citation_safe_count == 0 and fetched_count > 0:
        index_lines.append("- No citation-safe documents found; consider broadening the search.")
    if not warnings:
        index_lines.append("- Research bundle is clean with no warnings.")
    (out / "index.md").write_text("\n".join(index_lines), encoding="utf-8")
    generated_files.append("index.md")

    # --- Phase 6: recommended next steps ---
    recommended_next_steps: list[str] = []
    if metadata_only_count > 0:
        recommended_next_steps.append("Verify metadata-only documents from official sources.")
    if citation_safe_count == 0 and fetched_count > 0:
        recommended_next_steps.append("Broaden search query to find citation-safe documents.")
    if warnings:
        recommended_next_steps.append("Review warnings.json for fetch/search issues.")
    if not recommended_next_steps:
        recommended_next_steps.append("Bundle is complete with citation-safe documents.")

    bundle_data["recommended_next_steps"] = recommended_next_steps
    # Rewrite bundle.json with recommendations included
    bundle_data["hash"] = _hash_bundle(bundle_data)
    (out / "bundle.json").write_text(
        json.dumps(bundle_data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    return bundle_data


# ---------------------------------------------------------------------------
# refresh_research_bundle
# ---------------------------------------------------------------------------

def refresh_research_bundle(
    bundle_path: str | Path,
    *,
    dry_run: bool = False,
    sources_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Re-run research from an existing bundle.json, detecting new/changed docs.

    Reads bundle.json, re-executes research_topic with same query/sources,
    compares hashes, and reports new_documents, changed_documents, hash_changed.
    Preserves manual notes between markers in index.md.

    Args:
        bundle_path: Path to the bundle.json to refresh.
        dry_run: If True, compute diff without writing files.
        sources_override: Optional fake source clients for testing.

    Returns:
        Refresh report dict.
    """
    bundle_path = Path(bundle_path)
    if not bundle_path.exists():
        raise FileNotFoundError(f"Bundle not found: {bundle_path}")

    old_bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    old_query = old_bundle["query"]
    old_sources = old_bundle.get("sources", [])
    old_fetch_count = old_bundle.get("fetch_count", 5)
    old_filters = old_bundle.get("filters", {})
    out_dir = bundle_path.parent

    # Read existing manifest
    manifest_path = out_dir / "manifests" / "hash-manifest.json"
    old_manifest: dict[str, str] = {}
    if manifest_path.exists():
        old_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Preserve manual notes from index.md
    old_index = out_dir / "index.md"
    manual_notes = ""
    if old_index.exists():
        index_text = old_index.read_text(encoding="utf-8")
        m = re.search(
            rf"{re.escape(INDEX_MANUAL_START)}(.*?){re.escape(INDEX_MANUAL_END)}",
            index_text,
            re.DOTALL,
        )
        if m:
            manual_notes = m.group(1)

    if dry_run:
        # Simulate: return old bundle info without writing
        return {
            "dry_run": True,
            "query": old_query,
            "sources": old_sources,
            "bundle_path": str(bundle_path),
            "old_hash": old_bundle.get("hash"),
            "message": "Dry run: no files changed.",
        }

    # Re-run research
    new_bundle = research_topic(
        query=old_query,
        sources=old_sources,
        fetch_count=old_fetch_count,
        filters=old_filters,
        output_dir=out_dir,
        sources_override=sources_override,
    )

    # Read new manifest
    new_manifest: dict[str, str] = {}
    if manifest_path.exists():
        new_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Compute diff
    new_doc_keys = set(new_manifest.keys()) - set(old_manifest.keys())
    changed_doc_keys = set()
    for key in set(new_manifest.keys()) & set(old_manifest.keys()):
        if new_manifest[key] != old_manifest[key]:
            changed_doc_keys.add(key)

    hash_changed = old_bundle.get("hash") != new_bundle.get("hash")

    # Re-inject manual notes into index.md
    if manual_notes and old_index.exists():
        index_text = old_index.read_text(encoding="utf-8")
        if INDEX_MANUAL_START not in index_text:
            # Append manual notes section
            index_text += f"\n\n{INDEX_MANUAL_START}\n{manual_notes}\n{INDEX_MANUAL_END}\n"
            old_index.write_text(index_text, encoding="utf-8")

    return {
        "dry_run": False,
        "query": old_query,
        "bundle_path": str(bundle_path),
        "old_hash": old_bundle.get("hash"),
        "new_hash": new_bundle.get("hash"),
        "hash_changed": hash_changed,
        "new_documents": sorted(new_doc_keys),
        "changed_documents": sorted(changed_doc_keys),
        "new_count": len(new_doc_keys),
        "changed_count": len(changed_doc_keys),
        "fetched_count": new_bundle.get("fetched_count", 0),
        "warnings": new_bundle.get("warnings", []),
    }


# ---------------------------------------------------------------------------
# research_quality_dashboard
# ---------------------------------------------------------------------------

def research_quality_dashboard(
    bundle_path: str | Path,
) -> dict[str, Any]:
    """Read a research bundle and compute quality metrics.

    Returns:
        Dict with full_text_ratio, citation_safe_ratio, metadata_only_count,
        pdf_only_count, unavailable_count, source_distribution,
        missing_metadata_count, duplicate_citation_count, draft_readiness_score,
        recommendations.
    """
    bundle_path = Path(bundle_path)
    if not bundle_path.exists():
        raise FileNotFoundError(f"Bundle not found: {bundle_path}")

    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    results_path = bundle_path.parent / "results.json"
    if not results_path.exists():
        raise FileNotFoundError(f"results.json not found: {bundle_path.parent}")

    results = json.loads(results_path.read_text(encoding="utf-8"))
    total = len(results)
    if total == 0:
        return {
            "total_results": 0,
            "full_text_ratio": 0.0,
            "citation_safe_ratio": 0.0,
            "metadata_only_count": 0,
            "pdf_only_count": 0,
            "unavailable_count": 0,
            "source_distribution": {},
            "missing_metadata_count": 0,
            "duplicate_citation_count": 0,
            "draft_readiness_score": 0.0,
            "recommendations": ["No results to analyze."],
        }

    # Compute metrics from results.json (search results with content_status)
    status_counter: Counter[str] = Counter()
    source_counter: Counter[str] = Counter()
    missing_metadata = 0
    citation_labels: list[str] = []

    for r in results:
        cs = r.get("content_status", "metadata_only")
        status_counter[cs] += 1
        source_counter[r.get("source", "unknown")] += 1

        # Missing metadata: no court, esas_no, karar_no, decision_date
        has_meta = any(r.get(f) for f in ("court", "esas_no", "karar_no", "decision_date"))
        if not has_meta:
            missing_metadata += 1

        # Citation label for dedup
        parts = [r.get("court"), r.get("chamber"), r.get("decision_date"),
                 r.get("esas_no"), r.get("karar_no")]
        label = " | ".join(str(p) for p in parts if p) or r.get("document_id", "")
        citation_labels.append(label)

    # Counts
    full_text_count = status_counter.get("full_text", 0) + status_counter.get("html_markdown", 0)
    metadata_only_count = status_counter.get("metadata_only", 0)
    pdf_only_count = status_counter.get("pdf_link_only", 0)
    unavailable_count = status_counter.get("unavailable", 0)

    # Duplicate citations
    label_counter = Counter(citation_labels)
    duplicate_citation_count = sum(c for c in label_counter.values() if c > 1)

    # Ratios
    full_text_ratio = round(full_text_count / total, 4) if total else 0.0
    citation_safe_count = bundle.get("citation_safe_count", full_text_count)
    citation_safe_ratio = round(citation_safe_count / total, 4) if total else 0.0

    # Draft readiness score (0.0 - 1.0)
    # Weighted: full_text_ratio * 0.5 + citation_safe_ratio * 0.3 + (1 - missing_ratio) * 0.2
    missing_ratio = missing_metadata / total if total else 0.0
    draft_readiness_score = round(
        full_text_ratio * 0.5 + citation_safe_ratio * 0.3 + (1.0 - missing_ratio) * 0.2,
        4,
    )

    # Recommendations
    recommendations: list[str] = []
    if full_text_ratio < 0.3:
        recommendations.append("Low full-text ratio; fetch more documents with content.")
    if missing_metadata > total * 0.5:
        recommendations.append("Over half of results missing metadata; narrow search.")
    if duplicate_citation_count > 0:
        recommendations.append(f"{duplicate_citation_count} duplicate citation(s) detected; deduplicate.")
    if pdf_only_count > 0:
        recommendations.append(f"{pdf_only_count} PDF-only document(s); verify content before quoting.")
    if unavailable_count > 0:
        recommendations.append(f"{unavailable_count} unavailable document(s); try alternative sources.")
    if not recommendations:
        recommendations.append("Bundle quality is good.")

    return {
        "total_results": total,
        "full_text_ratio": full_text_ratio,
        "citation_safe_ratio": citation_safe_ratio,
        "metadata_only_count": metadata_only_count,
        "pdf_only_count": pdf_only_count,
        "unavailable_count": unavailable_count,
        "source_distribution": dict(source_counter),
        "missing_metadata_count": missing_metadata,
        "duplicate_citation_count": duplicate_citation_count,
        "draft_readiness_score": draft_readiness_score,
        "recommendations": recommendations,
    }
