"""Cross-source deduplication and merge for cached documents.

Detects duplicate documents from different sources (same court decision
appearing in multiple sources), creates canonical records, and lists
alternative sources.  Heuristic-based, deterministic, never false-merges.
"""
from __future__ import annotations

import logging
import sqlite3
import uuid

from typing import Any

from .models import ContentStatus, build_error

logger = logging.getLogger(__name__)

# Content status preference order for canonical selection (higher = better)
_CONTENT_STATUS_RANK: dict[str, int] = {
    ContentStatus.FULL_TEXT: 0,
    "full_text": 0,
    ContentStatus.HTML_MARKDOWN: 1,
    "html_markdown": 1,
    ContentStatus.PDF_LINK_ONLY: 2,
    "pdf_link_only": 2,
    ContentStatus.METADATA_ONLY: 3,
    "metadata_only": 3,
    ContentStatus.UNAVAILABLE: 4,
    "unavailable": 4,
}


def _ensure_dedup_tables(db: sqlite3.Connection) -> None:
    """Create dedup tables if they don't exist (idempotent)."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS dedup_clusters (
            cluster_id TEXT PRIMARY KEY,
            canonical_doc_id TEXT NOT NULL,
            canonical_source TEXT NOT NULL,
            member_count INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS dedup_members (
            cluster_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            source TEXT NOT NULL,
            is_canonical INTEGER DEFAULT 0,
            match_reason TEXT,
            PRIMARY KEY (document_id, source),
            FOREIGN KEY (cluster_id) REFERENCES dedup_clusters(cluster_id)
        )
    """)
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_dm_cluster ON dedup_members(cluster_id)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_dc_canonical ON dedup_clusters(canonical_doc_id, canonical_source)"
    )
    db.commit()


def _canonical_rank(content_status: str | None, text_length: int, retrieved_at: str | None) -> tuple[int, int, str]:
    """Compute a sort key for canonical selection. Lower = better.

    Priority:
    1. content_status rank (full_text best)
    2. text length (longer is better → negate for ascending sort)
    3. retrieved_at (earlier is better)
    """
    rank = _CONTENT_STATUS_RANK.get(content_status or "", 99)
    # Negate text_length so longer text sorts first in ascending order
    return (rank, -text_length, retrieved_at or "")


def find_duplicates(cache: Any = None, dry_run: bool = False) -> dict[str, Any]:
    """Find duplicate documents across sources.

    Groups documents by (court, esas_no, karar_no).  Documents must have
    non-empty esas_no AND karar_no to be considered.  Only groups with >1
    member create a dedup cluster.

    Args:
        cache: Cache instance.  If None, a new one is created.
        dry_run: If True, return plan without modifying DB.

    Returns:
        Dict with ok, clusters_found, total_duplicates, clusters list.
    """
    from .cache import Cache

    own_cache = cache is None
    if own_cache:
        cache = Cache()

    try:
        _ensure_dedup_tables(cache.db)

        # Query all documents that have both esas_no and karar_no
        rows = cache.db.execute(
            "SELECT document_id, source, court, esas_no, karar_no, "
            "content_status, full_text, markdown, retrieved_at "
            "FROM documents_v2 "
            "WHERE esas_no IS NOT NULL AND esas_no != '' "
            "AND karar_no IS NOT NULL AND karar_no != ''"
        ).fetchall()

        # Group by (court, esas_no, karar_no)
        groups: dict[tuple[str | None, str, str], list[dict[str, Any]]] = {}
        for row in rows:
            court = row["court"]
            esas = row["esas_no"].strip()
            karar = row["karar_no"].strip()
            key = (court, esas, karar)
            groups.setdefault(key, []).append({
                "document_id": row["document_id"],
                "source": row["source"],
                "content_status": row["content_status"],
                "text_length": len(row["full_text"] or row["markdown"] or ""),
                "retrieved_at": row["retrieved_at"],
            })

        clusters_plan: list[dict[str, Any]] = []
        total_duplicates = 0

        for (court, esas, karar), members in groups.items():
            if len(members) < 2:
                continue

            total_duplicates += len(members)

            # Deterministic canonical selection
            canonical = min(
                members,
                key=lambda m: _canonical_rank(
                    m["content_status"], m["text_length"], m["retrieved_at"]
                ),
            )

            cluster_id = str(uuid.uuid4())

            cluster_info = {
                "cluster_id": cluster_id,
                "canonical": {
                    "document_id": canonical["document_id"],
                    "source": canonical["source"],
                },
                "members": [
                    {"doc_id": m["document_id"], "source": m["source"]}
                    for m in members
                ],
                "match_reason": f"court={court}, esas_no={esas}, karar_no={karar}",
            }

            if not dry_run:
                # Persist cluster
                cache.db.execute(
                    "INSERT INTO dedup_clusters(cluster_id, canonical_doc_id, canonical_source, member_count) "
                    "VALUES(?, ?, ?, ?)",
                    (cluster_id, canonical["document_id"], canonical["source"], len(members)),
                )
                for m in members:
                    is_canon = 1 if m["document_id"] == canonical["document_id"] and m["source"] == canonical["source"] else 0
                    cache.db.execute(
                        "INSERT OR REPLACE INTO dedup_members(cluster_id, document_id, source, is_canonical, match_reason) "
                        "VALUES(?, ?, ?, ?, ?)",
                        (cluster_id, m["document_id"], m["source"], is_canon, cluster_info["match_reason"]),
                    )
                cache.db.commit()
                cache.log("find_duplicates_cluster", {
                    "cluster_id": cluster_id,
                    "canonical": cluster_info["canonical"],
                    "member_count": len(members),
                })

            clusters_plan.append(cluster_info)

        return {
            "ok": True,
            "clusters_found": len(clusters_plan),
            "total_duplicates": total_duplicates,
            "dry_run": dry_run,
            "clusters": clusters_plan,
        }
    except Exception as exc:
        return build_error("DEDUP_FAILED", str(exc))
    finally:
        if own_cache:
            cache.close()


def get_dedup_cluster(document_id: str, source: str, cache: Any = None) -> dict[str, Any]:
    """Find which dedup cluster a document belongs to.

    Args:
        document_id: Document ID to look up.
        source: Source identifier.
        cache: Cache instance.  If None, a new one is created.

    Returns:
        Dict with ok, in_cluster, cluster_id, canonical, all_members.
    """
    from .cache import Cache

    own_cache = cache is None
    if own_cache:
        cache = Cache()

    try:
        _ensure_dedup_tables(cache.db)

        row = cache.db.execute(
            "SELECT cluster_id FROM dedup_members WHERE document_id=? AND source=?",
            (document_id, source),
        ).fetchone()

        if not row:
            return {
                "ok": True,
                "in_cluster": False,
                "cluster_id": None,
                "canonical": None,
                "all_members": [],
            }

        cluster_id = row["cluster_id"]

        # Get canonical info
        cluster_row = cache.db.execute(
            "SELECT canonical_doc_id, canonical_source FROM dedup_clusters WHERE cluster_id=?",
            (cluster_id,),
        ).fetchone()

        # Get all members
        members_rows = cache.db.execute(
            "SELECT document_id, source, is_canonical, match_reason FROM dedup_members WHERE cluster_id=?",
            (cluster_id,),
        ).fetchall()

        return {
            "ok": True,
            "in_cluster": True,
            "cluster_id": cluster_id,
            "canonical": {
                "document_id": cluster_row["canonical_doc_id"],
                "source": cluster_row["canonical_source"],
            } if cluster_row else None,
            "all_members": [
                {
                    "document_id": m["document_id"],
                    "source": m["source"],
                    "is_canonical": bool(m["is_canonical"]),
                    "match_reason": m["match_reason"],
                }
                for m in members_rows
            ],
        }
    except Exception as exc:
        return build_error("DEDUP_LOOKUP_FAILED", str(exc))
    finally:
        if own_cache:
            cache.close()


def get_dedup_stats(cache: Any = None) -> dict[str, Any]:
    """Compute deduplication statistics.

    Args:
        cache: Cache instance.  If None, a new one is created.

    Returns:
        Dict with ok, total_clusters, total_duplicate_docs,
        space_saved_estimate, sources_most_duplicates.
    """
    from .cache import Cache

    own_cache = cache is None
    if own_cache:
        cache = Cache()

    try:
        _ensure_dedup_tables(cache.db)

        total_clusters = cache.db.execute(
            "SELECT COUNT(*) FROM dedup_clusters"
        ).fetchone()[0]

        total_duplicate_docs = cache.db.execute(
            "SELECT COUNT(*) FROM dedup_members"
        ).fetchone()[0]

        # Space saved estimate: (total_duplicate_docs - total_clusters) * avg_doc_size
        avg_row = cache.db.execute(
            "SELECT AVG(LENGTH(COALESCE(full_text, markdown, ''))) FROM documents_v2"
        ).fetchone()
        avg_doc_size = avg_row[0] or 0
        docs_redundant = max(0, total_duplicate_docs - total_clusters)
        space_saved_estimate = int(docs_redundant * avg_doc_size)

        # Sources with most duplicates
        source_rows = cache.db.execute(
            "SELECT source, COUNT(*) as cnt FROM dedup_members "
            "WHERE is_canonical = 0 GROUP BY source ORDER BY cnt DESC LIMIT 10"
        ).fetchall()

        return {
            "ok": True,
            "total_clusters": total_clusters,
            "total_duplicate_docs": total_duplicate_docs,
            "space_saved_estimate": space_saved_estimate,
            "sources_most_duplicates": [
                {"source": r["source"], "duplicate_count": r["cnt"]}
                for r in source_rows
            ],
        }
    except Exception as exc:
        return build_error("DEDUP_STATS_FAILED", str(exc))
    finally:
        if own_cache:
            cache.close()


def merge_cluster(cluster_id: str, cache: Any = None) -> dict[str, Any]:
    """Merge a cluster by enriching the canonical record.

    Adds alternative source URLs to the canonical record's metadata
    without overwriting existing fields.  Logs merge in history.

    Args:
        cluster_id: The dedup cluster ID to merge.
        cache: Cache instance.  If None, a new one is created.

    Returns:
        Dict with ok, cluster_id, canonical, enriched_fields, members_merged.
    """
    from .cache import Cache

    own_cache = cache is None
    if own_cache:
        cache = Cache()

    try:
        _ensure_dedup_tables(cache.db)

        # Get cluster info
        cluster_row = cache.db.execute(
            "SELECT canonical_doc_id, canonical_source, member_count "
            "FROM dedup_clusters WHERE cluster_id=?",
            (cluster_id,),
        ).fetchone()

        if not cluster_row:
            return build_error("CLUSTER_NOT_FOUND", f"Cluster {cluster_id} not found")

        canonical_doc_id = cluster_row["canonical_doc_id"]
        canonical_source = cluster_row["canonical_source"]

        # Get all members
        members_rows = cache.db.execute(
            "SELECT document_id, source, is_canonical FROM dedup_members WHERE cluster_id=?",
            (cluster_id,),
        ).fetchall()

        # Get canonical document metadata
        doc_row = cache.db.execute(
            "SELECT metadata_json, source_url FROM documents_v2 "
            "WHERE document_id=? AND source=?",
            (canonical_doc_id, canonical_source),
        ).fetchone()

        enriched_fields: list[str] = []
        members_merged = 0

        if doc_row:
            import json

            existing_meta = json.loads(doc_row["metadata_json"]) if doc_row["metadata_json"] else {}
            existing_alt_urls = existing_meta.get("alternative_source_urls", [])

            # Collect alternative source URLs from non-canonical members
            for m in members_rows:
                if m["is_canonical"]:
                    continue
                # Get source_url for this member
                m_doc = cache.db.execute(
                    "SELECT source_url FROM documents_v2 WHERE document_id=? AND source=?",
                    (m["document_id"], m["source"]),
                ).fetchone()
                if m_doc and m_doc["source_url"]:
                    alt_entry = {
                        "source": m["source"],
                        "document_id": m["document_id"],
                        "url": m_doc["source_url"],
                    }
                    # Avoid duplicates
                    if alt_entry not in existing_alt_urls:
                        existing_alt_urls.append(alt_entry)
                        members_merged += 1

            if existing_alt_urls:
                existing_meta["alternative_source_urls"] = existing_alt_urls
                if "alternative_source_urls" not in existing_meta or "alternative_source_urls" != existing_meta.get("alternative_source_urls"):
                    enriched_fields.append("alternative_source_urls")

                # Update the canonical document metadata
                cache.db.execute(
                    "UPDATE documents_v2 SET metadata_json=? WHERE document_id=? AND source=?",
                    (json.dumps(existing_meta, ensure_ascii=False), canonical_doc_id, canonical_source),
                )
                cache.db.commit()

        # Log merge
        cache.log("merge_cluster", {
            "cluster_id": cluster_id,
            "canonical": {"document_id": canonical_doc_id, "source": canonical_source},
            "members_merged": members_merged,
            "enriched_fields": enriched_fields,
        })

        return {
            "ok": True,
            "cluster_id": cluster_id,
            "canonical": {
                "document_id": canonical_doc_id,
                "source": canonical_source,
            },
            "enriched_fields": enriched_fields,
            "members_merged": members_merged,
        }
    except Exception as exc:
        return build_error("MERGE_FAILED", str(exc))
    finally:
        if own_cache:
            cache.close()


# ---------------------------------------------------------------------------
# Fuzzy Dedup v2 (M-28) — embedding-based near-duplicate detection
# ---------------------------------------------------------------------------


def _cosine_similarity_dense(vec_a: list[float], vec_b: list[float]) -> float:
    """Cosine similarity between two dense float vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = (sum(a * a for a in vec_a)) ** 0.5
    norm_b = (sum(b * b for b in vec_b)) ** 0.5
    denom = norm_a * norm_b
    return dot / denom if denom > 0 else 0.0


def find_fuzzy_duplicates(
    cache: Any = None,
    *,
    provider: str | None = None,
    cosine_threshold: float = 0.85,
    max_date_diff_days: int = 365,
) -> dict[str, Any]:
    """Find suspected fuzzy duplicates using dense embeddings.

    Only uses embedding_vectors table (requires M-24 dense index).
    Compares document pairs within same court.

    CRITICAL INVARIANT: This function ONLY reports candidate pairs. It NEVER
    auto-merges.  All merges require explicit user confirmation.

    Args:
        cache: Cache instance. If None, a new one is created.
        provider: Embedding provider to use. Default: from config/env.
        cosine_threshold: Cosine similarity threshold (0.0–1.0). Default 0.85.
        max_date_diff_days: Maximum date difference in days to consider. Default 365.

    Returns:
        Dict with ok, suspected_duplicates, total_suspected, warnings.
        Each suspected pair includes doc_a, doc_b, cosine_score, date_diff_days,
        confidence, recommendation.
    """
    from .cache import Cache
    from .embeddings import get_embedding_provider, unpack_vector

    own_cache = cache is None
    c = cache or Cache()
    try:
        db = c.db

        # Check if embedding_vectors table exists
        ev_exists = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='embedding_vectors'"
        ).fetchone()
        if not ev_exists:
            return {
                "ok": True,
                "suspected_duplicates": [],
                "total_suspected": 0,
                "warnings": [
                    "No embedding vectors found. Run build_embedding_index() first."
                ],
            }

        prov = get_embedding_provider(provider)
        if prov is None:
            return {
                "ok": False,
                "suspected_duplicates": [],
                "total_suspected": 0,
                "warnings": [
                    "No embedding provider available. "
                    "Build dense index first with build_embedding_index()."
                ],
            }

        # Get all dense vectors joined with document metadata
        rows = db.execute(
            """
            SELECT ev.document_id, ev.source, ev.vector, ev.norm, ev.dim,
                   dv.court, dv.decision_date, dv.title, dv.esas_no, dv.karar_no
            FROM embedding_vectors ev
            JOIN documents_v2 dv ON ev.document_id = dv.document_id AND ev.source = dv.source
            WHERE ev.provider_id = ?
            """,
            (prov.id,),
        ).fetchall()

        if len(rows) < 2:
            return {
                "ok": True,
                "suspected_duplicates": [],
                "total_suspected": 0,
                "warnings": [
                    "Need at least 2 indexed documents for fuzzy comparison."
                ],
            }

        # Group by court
        by_court: dict[str, list] = {}
        for r in rows:
            court = r["court"] or "unknown"
            by_court.setdefault(court, []).append(r)

        # M-53: Pre-fetch all dedup cluster memberships for O(1) lookup
        # instead of issuing an SQL query per pair (O(n²) queries → O(1) set lookup).
        cluster_pairs: set[tuple[str, str, str, str]] = set()
        try:
            dm_rows = db.execute(
                "SELECT dm1.document_id AS d1, dm1.source AS s1, "
                "dm2.document_id AS d2, dm2.source AS s2 "
                "FROM dedup_members dm1 "
                "JOIN dedup_members dm2 ON dm1.cluster_id = dm2.cluster_id"
            ).fetchall()
            for r in dm_rows:
                cluster_pairs.add((r["d1"], r["s1"], r["d2"], r["s2"]))
                cluster_pairs.add((r["d2"], r["s2"], r["d1"], r["s1"]))
        except Exception:
            pass  # table may not exist yet

        suspected: list[dict[str, Any]] = []

        for court, docs in by_court.items():
            for i in range(len(docs)):
                for j in range(i + 1, len(docs)):
                    a, b = docs[i], docs[j]

                    # Skip same document (identical id + source)
                    if a["document_id"] == b["document_id"] and a["source"] == b["source"]:
                        continue

                    # M-53: O(1) cluster membership check via pre-fetched set
                    if (a["document_id"], a["source"], b["document_id"], b["source"]) in cluster_pairs:
                        continue

                    # Compute cosine similarity from stored vectors
                    va = unpack_vector(a["vector"], a["dim"])
                    vb = unpack_vector(b["vector"], b["dim"])
                    dot = sum(va[k] * vb[k] for k in range(min(len(va), len(vb))))
                    denom = a["norm"] * b["norm"]
                    cosine = dot / denom if denom > 0 else 0.0

                    if cosine < cosine_threshold:
                        continue

                    # Check date proximity
                    date_diff: int | None = None
                    try:
                        da = a["decision_date"]
                        db_date = b["decision_date"]
                        if da and db_date:
                            from datetime import datetime
                            for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
                                try:
                                    pa = datetime.strptime(da, fmt)
                                    pb = datetime.strptime(db_date, fmt)
                                    date_diff = abs((pa - pb).days)
                                    break
                                except ValueError:
                                    continue
                    except Exception:
                        pass

                    if date_diff is not None and date_diff > max_date_diff_days:
                        continue

                    # Confidence based on cosine score
                    if cosine > 0.95:
                        confidence = "high"
                    elif cosine > 0.90:
                        confidence = "medium"
                    else:
                        confidence = "low"

                    suspected.append({
                        "doc_a": {
                            "document_id": a["document_id"],
                            "source": a["source"],
                            "title": a["title"],
                        },
                        "doc_b": {
                            "document_id": b["document_id"],
                            "source": b["source"],
                            "title": b["title"],
                        },
                        "cosine_score": round(cosine, 6),
                        "date_diff_days": date_diff,
                        "confidence": confidence,
                        "recommendation": "MANUAL_REVIEW_REQUIRED — do not auto-merge",
                    })

        # Sort by cosine score descending
        suspected.sort(key=lambda x: x["cosine_score"], reverse=True)

        return {
            "ok": True,
            "suspected_duplicates": suspected,
            "total_suspected": len(suspected),
            "warnings": [
                "EMBEDDING-BASED SUGGESTIONS ONLY — merge requires explicit user confirmation."
            ],
        }
    except Exception as exc:
        return build_error("FUZZY_DEDUP_FAILED", str(exc))
    finally:
        if own_cache:
            try:
                c.close()
            except Exception:
                pass


def _extract_year(date_str: str | None) -> int | None:
    """Extract year from a datetime or date string."""
    if not date_str:
        return None
    # Try ISO format: "2024-05-15" or "2024-05-15T..."
    try:
        return int(date_str[:4])
    except (ValueError, TypeError):
        pass
    # Try other formats with regex
    import re
    m = re.search(r'(19|20)\d{2}', str(date_str))
    return int(m.group()) if m else None


def get_fuzzy_dedup_stats(cache: Any = None) -> dict[str, Any]:
    """Report fuzzy dedup statistics.

    Checks availability of embedding vectors required for fuzzy matching.

    Returns:
        Dict with ok, embedded_document_count, provider, threshold_default.
    """
    from .cache import Cache

    own_cache = cache is None
    c = cache or Cache()
    try:
        db = c.db

        ev_exists = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='embedding_vectors'"
        ).fetchone()

        if ev_exists:
            embedded_count = db.execute(
                "SELECT COUNT(DISTINCT document_id || '|' || source) FROM embedding_vectors"
            ).fetchone()[0]
            providers = db.execute(
                "SELECT provider_id, COUNT(*) as cnt FROM embedding_vectors "
                "GROUP BY provider_id"
            ).fetchall()
        else:
            embedded_count = 0
            providers = []

        total_docs = db.execute(
            "SELECT COUNT(*) FROM documents_v2 "
            "WHERE (full_text IS NOT NULL AND full_text != '') "
            "OR (markdown IS NOT NULL AND markdown != '')"
        ).fetchone()[0]

        return {
            "ok": True,
            "total_documents": total_docs,
            "embedded_documents": embedded_count,
            "unembedded_documents": max(0, total_docs - embedded_count),
            "providers": [dict(r) for r in providers],
            "default_threshold": 0.85,
            "requires_embeddings": embedded_count < 2,
            "ready": embedded_count >= 2,
        }
    finally:
        if own_cache:
            try:
                c.close()
            except Exception:
                pass
