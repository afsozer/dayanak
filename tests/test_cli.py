"""Tests for CLI imports."""
from __future__ import annotations


def test_cli_imports():
    """Test that CLI module can be imported."""
    from emsal_mcp.cli import app
    assert app is not None


def test_server_imports():
    """Test that server module can be imported."""
    from emsal_mcp import server
    assert hasattr(server, "main")


def test_verification_imports():
    """Test that verification module can be imported."""
    from emsal_mcp.verification import (
        check_cache_integrity,
        smoke_test_offline,
        verify_bundle_archive_integrity,
        verify_document_hash_in_cache,
    )
    assert callable(smoke_test_offline)
    assert callable(check_cache_integrity)
    assert callable(verify_bundle_archive_integrity)
    assert callable(verify_document_hash_in_cache)


def test_drafter_imports():
    """Test that drafter module can be imported."""
    from emsal_mcp.drafter import assemble_draft, validate_draft_body
    assert callable(assemble_draft)
    assert callable(validate_draft_body)


def test_smoke_test_offline():
    """Run offline smoke test."""
    from emsal_mcp.verification import smoke_test_offline
    result = smoke_test_offline()
    assert result["ok"] is True
    assert len(result["tests"]) > 0
    for test in result["tests"]:
        assert test["ok"] is True
