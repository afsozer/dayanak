from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from .cache import Cache
from .models import Document


def smoke_test_offline() -> dict[str, Any]:
    """Offline smoke test: basic import and model validation."""
    results: dict[str, Any] = {"ok": True, "tests": []}

    # Test imports
    try:
        from emsal_mcp import models  # noqa: F401
        from emsal_mcp import safety  # noqa: F401
        from emsal_mcp import cache  # noqa: F401
        from emsal_mcp import udf  # noqa: F401
        from emsal_mcp import drafter  # noqa: F401
        from emsal_mcp import exporter  # noqa: F401
        from emsal_mcp import verification  # noqa: F401
        results["tests"].append({"name": "imports", "ok": True})
    except ImportError as e:
        results["ok"] = False
        results["tests"].append({"name": "imports", "ok": False, "error": str(e)})

    # Test model creation
    try:
        from emsal_mcp.models import Document, ContentStatus
        doc = Document(
            source="test", document_id="123", title="Test",
            full_text="Test content", content_status=ContentStatus.FULL_TEXT,
            decision_date="2024-01-01"
        )
        assert doc.quote_usable
        assert doc.text == "Test content"
        results["tests"].append({"name": "model_create", "ok": True})
    except Exception as e:
        results["ok"] = False
        results["tests"].append({"name": "model_create", "ok": False, "error": str(e)})

    # Test citation safety and UDF round-trip without network.
    try:
        from emsal_mcp.models import ContentStatus, Document
        from emsal_mcp.safety import citation_check, exact_quote
        from emsal_mcp.udf import read_udf, write_udf

        doc = Document(
            source="smoke",
            document_id="1",
            title="Smoke",
            full_text="Resmi metin içinde aynen aranacak ibare vardır.",
            content_status=ContentStatus.FULL_TEXT,
            source_url="https://example.test/smoke",
        )
        check = citation_check(doc)
        assert check.ok and check.quoteUsable and check.draftUsable
        assert "aynen aranacak" in exact_quote(doc, "aynen aranacak")
        with tempfile.TemporaryDirectory() as td:
            udf_path = Path(td) / "smoke.udf"
            write_udf("Başlık\nGövde", udf_path)
            assert "Başlık" in read_udf(udf_path)
        results["tests"].append({"name": "safety_udf_roundtrip", "ok": True})
    except Exception as e:
        results["ok"] = False
        results["tests"].append({"name": "safety_udf_roundtrip", "ok": False, "error": str(e)})

    return results


def smoke_test_online(source: str = "bedesten") -> dict[str, Any]:
    """Online smoke test: basic source connectivity."""
    import asyncio
    from .sources.registry import get_source

    results: dict[str, Any] = {"ok": True, "tests": []}

    try:
        client = get_source(source)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            search_results = loop.run_until_complete(client.search("test", limit=1))
            results["tests"].append({
                "name": f"search_{source}",
                "ok": True,
                "count": len(search_results),
            })
        except Exception as e:
            results["tests"].append({
                "name": f"search_{source}",
                "ok": False,
                "error": str(e),
            })
        finally:
            loop.close()
    except Exception as e:
        results["ok"] = False
        results["tests"].append({"name": f"source_{source}", "ok": False, "error": str(e)})

    return results


def check_cache_integrity(cache_path: str | Path | None = None) -> dict[str, Any]:
    """Check cache database integrity."""
    cache = Cache(Path(cache_path) if cache_path else None)
    results: dict[str, Any] = {"ok": True, "tests": []}

    try:
        # Check WAL mode
        mode = cache.db.execute("PRAGMA journal_mode").fetchone()[0]
        results["tests"].append({"name": "wal_mode", "ok": mode.lower() == "wal", "value": mode})

        # Check tables exist
        tables = [row[0] for row in cache.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        required = ["cache", "history", "documents", "packs", "drafts", "documents_v2"]
        missing = [t for t in required if t not in tables]
        results["tests"].append({
            "name": "tables_exist",
            "ok": len(missing) == 0,
            "tables": tables,
            "missing": missing,
        })

        # Test CRUD
        cache.set("test_key", {"test": "value"})
        retrieved = cache.get("test_key")
        results["tests"].append({
            "name": "set_get",
            "ok": retrieved == {"test": "value"},
        })

    except Exception as e:
        results["ok"] = False
        results["tests"].append({"name": "cache_error", "ok": False, "error": str(e)})
    finally:
        cache.close()

    return results


def verify_document_hash_in_cache(doc: Document, cache_path: str | Path | None = None) -> dict[str, Any]:
    """Verify document hash matches cache."""
    cache = Cache(Path(cache_path) if cache_path else None)
    results = {"ok": True, "document_id": doc.document_id}

    try:
        cache.store_document(doc)
        retrieved = cache.get_document(doc.document_id, doc.source)

        if retrieved is None:
            results["ok"] = False
            results["error"] = "Document not found in cache"
        else:
            # Verify hash
            if doc.content_hash:
                text = retrieved.text
                if text:
                    computed = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
                    results["hash_match"] = computed == doc.content_hash
                    results["computed_hash"] = computed
                    results["stored_hash"] = doc.content_hash
                else:
                    results["hash_match"] = True
            else:
                results["hash_match"] = True
    except Exception as e:
        results["ok"] = False
        results["error"] = str(e)
    finally:
        cache.close()

    return results


def verify_bundle_archive_integrity(bundle_path: str | Path) -> dict[str, Any]:
    """Verify ZIP bundle archive integrity."""
    path = Path(bundle_path)
    if not path.exists():
        return {"valid": False, "error": "Bundle not found"}

    try:
        with ZipFile(path, "r") as zf:
            # Check for corruption by testing extraction
            bad = zf.testzip()
            if bad:
                return {"valid": False, "error": f"Corrupt file: {bad}"}

            results = {"valid": True, "files": zf.namelist()}

            # Load and verify manifest
            if "manifest.json" in zf.namelist():
                manifest = json.loads(zf.read("manifest.json"))
                results["manifest"] = manifest

            return results
    except Exception as e:
        return {"valid": False, "error": str(e)}
