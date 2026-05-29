"""v0.12 Chamber Profiling — analytics on court chambers from cached documents.

Provides analytics on court chambers (daireler) from the documents_v2 SQLite
table: overview, detailed profiles, timelines, and cross-chamber similarity.

- All functions return dict[str, Any] with ok, warnings, recommended_next_steps, version
- Zero live network — purely analytical on cached data
- Zero new dependencies — stdlib + sqlite3 only
"""
from __future__ import annotations

import re
import sqlite3
from collections import Counter
from datetime import datetime
from typing import Any

from .cache import Cache

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHAMBER_MODULE_VERSION = "0.12.0"

# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r'\b\w+\b', re.UNICODE)


def _tokenize(text: str) -> list[str]:
    """Simple word tokenizer for Turkish text."""
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


# ---------------------------------------------------------------------------
# Turkish stopwords
# ---------------------------------------------------------------------------

_TR_STOPWORDS = {
    "ve", "bir", "bu", "ile", "de", "da", "için", "olarak", "olan",
    "veya", "çok", "daha", "gibi", "her", "ne", "ise", "ama", "fakat",
    "ancak", "lakin", "çünkü", "kadar", "mı", "mi", "mu", "mü",
    "hakkında", "ilişkin", "dair", "sayılı", "kararı", "davası",
    "karar", "dava", "dosya", "no", "sayı", "tarih", "tarihli",
}

# ---------------------------------------------------------------------------
# DB Connection Helper
# ---------------------------------------------------------------------------


def _get_db(cache: Cache | None = None) -> tuple[sqlite3.Connection, bool]:
    """Get DB connection. Returns (db, own_cache).

    If a Cache instance with an active connection is provided, returns that
    connection and ``own_cache=False`` (caller must NOT close the cache).
    Otherwise creates a fresh Cache and returns ``own_cache=True``.
    """
    if cache is not None and cache.db is not None:
        return cache.db, False
    c = Cache()
    return c.db, True


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------


def _parse_year(date_str: str | None) -> int | None:
    """Parse year from ISO (YYYY-MM-DD) or Turkish (DD.MM.YYYY) date."""
    if not date_str:
        return None
    # Try ISO: YYYY-MM-DD
    m = re.match(r'^(\d{4})-\d{2}-\d{2}$', date_str.strip())
    if m:
        return int(m.group(1))
    # Try Turkish: DD.MM.YYYY
    m = re.match(r'^\d{2}\.\d{2}\.(\d{4})$', date_str.strip())
    if m:
        return int(m.group(1))
    # Try just year
    m = re.match(r'^(\d{4})$', date_str.strip())
    if m:
        return int(m.group(1))
    return None


def _compute_date_range_years(earliest: str | None, latest: str | None) -> float | None:
    """Compute approximate year span between two date strings."""
    if not earliest or not latest:
        return None
    try:
        d1 = datetime.fromisoformat(earliest.strip())
        d2 = datetime.fromisoformat(latest.strip())
        return round(abs((d2 - d1).days) / 365.25, 1)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Keyword extraction helper
# ---------------------------------------------------------------------------


def _extract_keywords(texts: list[str], top_n: int = 20) -> list[dict[str, Any]]:
    """Extract top keywords from a list of texts, excluding Turkish stopwords."""
    counter: Counter = Counter()
    for text in texts:
        for token in _tokenize(text):
            if token in _TR_STOPWORDS or len(token) < 2:
                continue
            counter[token] += 1
    return [{"word": word, "count": count} for word, count in counter.most_common(top_n)]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_chamber_overview(
    court: str | None = None,
    cache: Cache | None = None,
) -> dict[str, Any]:
    """Overview of all chambers with statistics.

    Args:
        court: Optional court name filter.
        cache: Optional Cache instance for DB injection.

    Returns:
        Dict with ok, court_filter, total_chambers, total_documents, chambers list,
        warnings, recommended_next_steps, version.
    """
    own_cache = cache is None
    c = cache or Cache()
    try:
        db = c.db
        warnings: list[str] = []
        recommended: list[str] = []

        # Build query
        where_clauses: list[str] = ["chamber IS NOT NULL AND chamber != ''"]
        params: list[Any] = []
        if court:
            where_clauses.append("court = ?")
            params.append(court)

        where_sql = " WHERE " + " AND ".join(where_clauses)

        # Get total documents first (for ok check)
        total_docs = db.execute("SELECT COUNT(*) FROM documents_v2").fetchone()[0]
        if total_docs == 0:
            return {
                "ok": False,
                "court_filter": court,
                "total_chambers": 0,
                "total_documents": 0,
                "chambers": [],
                "warnings": ["No cached documents found in the database."],
                "recommended_next_steps": ["Use store_document() to add documents."],
                "version": CHAMBER_MODULE_VERSION,
            }

        # Group by court + chamber
        sql = f"""
            SELECT
                court,
                chamber,
                COUNT(*) AS document_count,
                SUM(CASE WHEN content_status IN ('full_text', 'html_markdown') THEN 1 ELSE 0 END) AS content_available_count,
                MIN(decision_date) AS earliest_date,
                MAX(decision_date) AS latest_date,
                SUM(CASE WHEN decision_date >= date('now', '-2 years') THEN 1 ELSE 0 END) AS recent_count
            FROM documents_v2
            {where_sql}
            GROUP BY court, chamber
            ORDER BY document_count DESC
        """
        rows = db.execute(sql, params).fetchall()

        if not rows:
            warnings.append(
                "No chambers found"
                + (f" for court '{court}'" if court else "")
                + ". Some documents may not have chamber metadata."
            )
            recommended.append("Ensure documents are stored with chamber metadata.")
            return {
                "ok": False,
                "court_filter": court,
                "total_chambers": 0,
                "total_documents": total_docs,
                "chambers": [],
                "warnings": warnings,
                "recommended_next_steps": recommended,
                "version": CHAMBER_MODULE_VERSION,
            }

        chambers: list[dict[str, Any]] = []
        for row in rows:
            chambers.append({
                "court": row["court"] or "",
                "chamber": row["chamber"] or "",
                "document_count": row["document_count"],
                "content_available_count": row["content_available_count"],
                "earliest_date": row["earliest_date"],
                "latest_date": row["latest_date"],
                "recent_count": row["recent_count"],
            })

        return {
            "ok": True,
            "court_filter": court,
            "total_chambers": len(chambers),
            "total_documents": total_docs,
            "chambers": chambers,
            "warnings": warnings,
            "recommended_next_steps": recommended or ["Chamber overview retrieved."],
            "version": CHAMBER_MODULE_VERSION,
        }
    except Exception as exc:
        return {
            "ok": False,
            "court_filter": court,
            "total_chambers": 0,
            "total_documents": 0,
            "chambers": [],
            "warnings": [str(exc)],
            "recommended_next_steps": ["Check database accessibility."],
            "version": CHAMBER_MODULE_VERSION,
        }
    finally:
        if own_cache:
            try:
                c.close()
            except Exception:
                pass


def profile_chamber(
    chamber: str,
    court: str | None = None,
    cache: Cache | None = None,
) -> dict[str, Any]:
    """Detailed profile of a specific chamber.

    Args:
        chamber: Chamber name to profile.
        court: Optional court name filter.
        cache: Optional Cache instance for DB injection.

    Returns:
        Dict with ok, chamber, court_filter, metrics, top_keywords, recent_documents,
        warnings, recommended_next_steps, version.
    """
    own_cache = cache is None
    c = cache or Cache()
    try:
        db = c.db
        warnings: list[str] = []
        recommended: list[str] = []

        # Build WHERE clause
        where_clauses: list[str] = ["chamber = ?"]
        params: list[Any] = [chamber]
        if court:
            where_clauses.append("court = ?")
            params.append(court)
        where_sql = " WHERE " + " AND ".join(where_clauses)

        # Fetch all matching documents
        sql = f"""
            SELECT
                document_id, title, court, chamber, decision_date,
                content_status, quote_usable, draft_usable,
                full_text, markdown
            FROM documents_v2
            {where_sql}
            ORDER BY decision_date DESC
        """
        rows = db.execute(sql, params).fetchall()

        if not rows:
            warnings.append(
                f"No documents found for chamber '{chamber}'"
                + (f" in court '{court}'" if court else "")
                + "."
            )
            return {
                "ok": False,
                "chamber": chamber,
                "court_filter": court,
                "metrics": {
                    "total_documents": 0,
                    "content_available_count": 0,
                    "content_status_distribution": {},
                    "quote_usable_count": 0,
                    "draft_usable_count": 0,
                    "earliest_date": None,
                    "latest_date": None,
                    "date_range_years": None,
                },
                "top_keywords": [],
                "recent_documents": [],
                "warnings": warnings,
                "recommended_next_steps": ["Check that documents exist with this chamber metadata."],
                "version": CHAMBER_MODULE_VERSION,
            }

        # Compute metrics
        total_docs = len(rows)
        content_available = 0
        status_dist: Counter = Counter()
        quote_usable = 0
        draft_usable = 0
        dates: list[str] = []
        titles: list[str] = []
        recent_docs: list[dict[str, Any]] = []

        for i, row in enumerate(rows):
            status = row["content_status"] or "unknown"
            status_dist[status] += 1
            if status in ("full_text", "html_markdown"):
                content_available += 1
            if row["quote_usable"]:
                quote_usable += 1
            if row["draft_usable"]:
                draft_usable += 1
            if row["decision_date"]:
                dates.append(row["decision_date"])
            if row["title"]:
                titles.append(row["title"])
            # Last 5 most recent
            if i < 5:
                recent_docs.append({
                    "document_id": row["document_id"],
                    "title": row["title"] or "",
                    "decision_date": row["decision_date"] or "",
                })

        # Sort dates
        sorted_dates = sorted(d for d in dates if d)
        earliest = sorted_dates[0] if sorted_dates else None
        latest = sorted_dates[-1] if sorted_dates else None
        date_range_years = _compute_date_range_years(earliest, latest)

        # Extract keywords from titles
        top_keywords = _extract_keywords(titles, top_n=20)

        metrics = {
            "total_documents": total_docs,
            "content_available_count": content_available,
            "content_status_distribution": dict(status_dist),
            "quote_usable_count": quote_usable,
            "draft_usable_count": draft_usable,
            "earliest_date": earliest,
            "latest_date": latest,
            "date_range_years": date_range_years,
        }

        if content_available == 0:
            warnings.append("No documents with full content available for this chamber.")
            recommended.append("Retrieve full text content for better analysis.")
        if not top_keywords:
            warnings.append("No meaningful keywords could be extracted from document titles.")

        return {
            "ok": True,
            "chamber": chamber,
            "court_filter": court,
            "metrics": metrics,
            "top_keywords": top_keywords,
            "recent_documents": recent_docs,
            "warnings": warnings,
            "recommended_next_steps": recommended or [f"Profile generated for chamber '{chamber}'."],
            "version": CHAMBER_MODULE_VERSION,
        }
    except Exception as exc:
        return {
            "ok": False,
            "chamber": chamber,
            "court_filter": court,
            "metrics": {
                "total_documents": 0,
                "content_available_count": 0,
                "content_status_distribution": {},
                "quote_usable_count": 0,
                "draft_usable_count": 0,
                "earliest_date": None,
                "latest_date": None,
                "date_range_years": None,
            },
            "top_keywords": [],
            "recent_documents": [],
            "warnings": [str(exc)],
            "recommended_next_steps": ["Check database accessibility."],
            "version": CHAMBER_MODULE_VERSION,
        }
    finally:
        if own_cache:
            try:
                c.close()
            except Exception:
                pass


def chamber_timeline(
    chamber: str | None = None,
    court: str | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    cache: Cache | None = None,
) -> dict[str, Any]:
    """Decision timeline grouped by year.

    Args:
        chamber: Optional chamber filter.
        court: Optional court filter.
        start_year: Optional start year (inclusive).
        end_year: Optional end year (inclusive).
        cache: Optional Cache instance for DB injection.

    Returns:
        Dict with ok, chamber_filter, court_filter, year_range, total_documents,
        timeline, warnings, version.
    """
    own_cache = cache is None
    c = cache or Cache()
    try:
        db = c.db
        warnings: list[str] = []

        # Build WHERE clauses
        where_clauses: list[str] = []
        params: list[Any] = []
        if chamber:
            where_clauses.append("chamber = ?")
            params.append(chamber)
        if court:
            where_clauses.append("court = ?")
            params.append(court)

        where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        sql = f"SELECT decision_date FROM documents_v2{where_sql}"
        rows = db.execute(sql, params).fetchall()

        if not rows:
            return {
                "ok": False,
                "chamber_filter": chamber,
                "court_filter": court,
                "year_range": {"start": 0, "end": 0},
                "total_documents": 0,
                "timeline": [],
                "warnings": ["No documents found for the given filters."],
                "version": CHAMBER_MODULE_VERSION,
            }

        # Extract years
        year_counter: Counter = Counter()
        for row in rows:
            year = _parse_year(row["decision_date"])
            if year is not None:
                year_counter[year] += 1

        if not year_counter:
            warnings.append("Could not parse any years from decision_date fields.")
            return {
                "ok": False,
                "chamber_filter": chamber,
                "court_filter": court,
                "year_range": {"start": 0, "end": 0},
                "total_documents": len(rows),
                "timeline": [],
                "warnings": warnings,
                "version": CHAMBER_MODULE_VERSION,
            }

        # Build timeline
        all_years = sorted(year_counter.keys())
        start = start_year or all_years[0]
        end = end_year or all_years[-1]

        timeline: list[dict[str, Any]] = []
        for year in range(start, end + 1):
            count = year_counter.get(year, 0)
            timeline.append({"year": year, "count": count})

        # Filter out zero-count years for compactness
        timeline = [t for t in timeline if t["count"] > 0]

        total_with_year = sum(t["count"] for t in timeline)
        total_all = len(rows)
        if total_all != total_with_year:
            warnings.append(
                f"{total_all - total_with_year} documents could not be assigned a year."
            )

        return {
            "ok": True,
            "chamber_filter": chamber,
            "court_filter": court,
            "year_range": {"start": start, "end": end},
            "total_documents": total_all,
            "timeline": timeline,
            "warnings": warnings,
            "version": CHAMBER_MODULE_VERSION,
        }
    except Exception as exc:
        return {
            "ok": False,
            "chamber_filter": chamber,
            "court_filter": court,
            "year_range": {"start": 0, "end": 0},
            "total_documents": 0,
            "timeline": [],
            "warnings": [str(exc)],
            "version": CHAMBER_MODULE_VERSION,
        }
    finally:
        if own_cache:
            try:
                c.close()
            except Exception:
                pass


def find_similar_chambers(
    chamber: str,
    court: str | None = None,
    limit: int = 5,
    cache: Cache | None = None,
) -> dict[str, Any]:
    """Find chambers with similar topic profiles based on keyword overlap.

    Uses Jaccard similarity on top keyword sets extracted from document titles.

    Args:
        chamber: Target chamber name.
        court: Optional court filter (applied to target chamber lookup).
        limit: Maximum similar chambers to return.
        cache: Optional Cache instance for DB injection.

    Returns:
        Dict with ok, target_chamber, similar_chambers, warnings,
        recommended_next_steps, version.
    """
    own_cache = cache is None
    c = cache or Cache()
    try:
        warnings: list[str] = []
        recommended: list[str] = []

        # Get target chamber keywords via profile_chamber
        target_profile = profile_chamber(chamber, court=court, cache=c)
        if not target_profile["ok"]:
            return {
                "ok": False,
                "target_chamber": chamber,
                "similar_chambers": [],
                "warnings": target_profile.get("warnings", []),
                "recommended_next_steps": ["Ensure the target chamber exists in cached documents."],
                "version": CHAMBER_MODULE_VERSION,
            }

        target_keywords = {kw["word"] for kw in target_profile.get("top_keywords", [])}

        if not target_keywords:
            warnings.append("Target chamber has no extractable keywords for comparison.")
            return {
                "ok": False,
                "target_chamber": chamber,
                "similar_chambers": [],
                "warnings": warnings,
                "recommended_next_steps": ["Ensure the target chamber has documents with title text."],
                "version": CHAMBER_MODULE_VERSION,
            }

        # Get all other chambers
        overview = get_chamber_overview(cache=c)
        if not overview["ok"]:
            return {
                "ok": False,
                "target_chamber": chamber,
                "similar_chambers": [],
                "warnings": overview.get("warnings", []),
                "recommended_next_steps": ["No chambers available for comparison."],
                "version": CHAMBER_MODULE_VERSION,
            }

        # Get keywords for each candidate chamber
        similar: list[dict[str, Any]] = []
        for ch in overview.get("chambers", []):
            ch_name = ch["chamber"]
            ch_court = ch["court"]

            # Skip the target chamber itself
            if ch_name == chamber:
                if not court or ch_court == court:
                    continue

            ch_profile = profile_chamber(ch_name, court=ch_court, cache=c)
            if not ch_profile["ok"]:
                continue

            candidate_keywords = {kw["word"] for kw in ch_profile.get("top_keywords", [])}
            if not candidate_keywords:
                continue

            # Jaccard similarity
            intersection = target_keywords & candidate_keywords
            union = target_keywords | candidate_keywords
            similarity = len(intersection) / len(union) if union else 0.0

            if similarity > 0:
                similar.append({
                    "chamber": ch_name,
                    "court": ch_court,
                    "similarity_score": round(similarity, 4),
                    "shared_keywords": sorted(intersection),
                    "document_count": ch_profile["metrics"]["total_documents"],
                })

        # Sort by similarity descending, take top `limit`
        similar.sort(key=lambda x: x["similarity_score"], reverse=True)
        top_similar = similar[:limit]

        if not top_similar:
            warnings.append("No similar chambers found based on keyword overlap.")
            recommended.append("Try a chamber with more documents for richer keyword profiles.")

        return {
            "ok": True,
            "target_chamber": chamber,
            "similar_chambers": top_similar,
            "warnings": warnings,
            "recommended_next_steps": recommended or [
                f"Found {len(top_similar)} chambers with similar topic profiles."
            ],
            "version": CHAMBER_MODULE_VERSION,
        }
    except Exception as exc:
        return {
            "ok": False,
            "target_chamber": chamber,
            "similar_chambers": [],
            "warnings": [str(exc)],
            "recommended_next_steps": ["Check database accessibility."],
            "version": CHAMBER_MODULE_VERSION,
        }
    finally:
        if own_cache:
            try:
                c.close()
            except Exception:
                pass
