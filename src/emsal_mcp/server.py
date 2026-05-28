from __future__ import annotations

from .document import controlled_draft, export_bundle as export_bundle_impl
from .models import Document
from .safety import build_input_pack as build_input_pack_impl, citation_check
from .sources.registry import capabilities, get_source
from .udf import probe_udf, read_udf as read_udf_impl, write_udf as write_udf_impl
from .release import archive_release, readiness_dashboard, release_notes, release_smoke as release_smoke_result


def main() -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as exc:  # pragma: no cover
        raise SystemExit("MCP extra kurulu değil. Kurulum: pip install -e .[mcp]") from exc

    mcp = FastMCP("emsal-mcp")

    @mcp.tool()
    async def search_decisions(source: str, query: str, limit: int = 10, page: int = 1) -> list[dict]:
        return [r.model_dump(mode="json") for r in await get_source(source).search(query, limit=limit, page=page)]

    @mcp.tool()
    async def get_document(source: str, document_id: str) -> dict:
        return (await get_source(source).get_document(document_id)).model_dump(mode="json")

    @mcp.tool()
    def source_capabilities() -> list[dict]:
        return capabilities()

    @mcp.tool()
    def citation_safety(document: dict) -> dict:
        return citation_check(Document.model_validate(document)).model_dump(mode="json")

    @mcp.tool()
    def build_input_pack(matter: str, issue: str, documents: list[dict]) -> dict:
        docs = [Document.model_validate(d) for d in documents]
        return build_input_pack_impl(matter, issue, docs).model_dump(mode="json")

    @mcp.tool()
    def draft_document(title: str, body: str, documents: list[dict]) -> dict:
        docs = [Document.model_validate(d) for d in documents]
        return {"markdown": controlled_draft(title, body, docs)}

    @mcp.tool()
    def export_bundle(out_dir: str, matter: str, issue: str, documents: list[dict]) -> dict:
        return export_bundle_impl(out_dir, matter=matter, issue=issue, docs=[Document.model_validate(d) for d in documents])

    @mcp.tool()
    def read_udf(path: str) -> dict:
        return {"text": read_udf_impl(path), "probe": probe_udf(path)}

    @mcp.tool()
    def write_udf(text: str, out_path: str, title_centered: bool = False) -> dict:
        return {"out_path": str(write_udf_impl(text, out_path, title_centered=title_centered)), "warning": "UYAP Doküman Editörü ile manuel doğrulama gerekir."}

    @mcp.tool()
    def release_smoke() -> dict:
        return release_smoke_result()

    @mcp.tool()
    def release_dashboard() -> dict:
        return readiness_dashboard()

    @mcp.tool()
    def release_notes_tool() -> dict:
        return {"markdown": release_notes()}

    @mcp.tool()
    def release_archive(out_dir: str) -> dict:
        return archive_release(out_dir)

    mcp.run()


if __name__ == "__main__":
    main()
