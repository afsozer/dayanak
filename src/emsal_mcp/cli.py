from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer

from . import __version__
from .cache import Cache
from .document import controlled_draft, export_bundle, markdown_to_docx
from .models import Document
from .release import archive_release, compare_history, readiness_dashboard, release_notes, release_smoke, write_history
from .safety import build_input_pack, citation_check
from .sources.registry import capabilities, get_source, registry
from .udf import probe_udf, read_udf, udf_to_markdown, write_udf

app = typer.Typer(help="Emsal-mcp citation-safe hukuk araştırma CLI")
udf_app = typer.Typer(help="UDF okuma/yazma araçları")
release_app = typer.Typer(help="Release smoke/dashboard/history/regression/notes/archive")
app.add_typer(udf_app, name="udf")
app.add_typer(release_app, name="release")


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


@app.command()
def search(source: str, query: str, limit: int = 10, page: int = 1, json_out: bool = typer.Option(False, "--json")):
    import asyncio
    src = get_source(source)
    results = asyncio.run(src.search(query, limit=limit, page=page))
    Cache().set(f"search:{source}:{query}:{limit}:{page}", [r.model_dump(mode="json") for r in results])
    _print([r.model_dump(mode="json") for r in results], json_out)


@app.command()
def get(source: str, document_id: str, json_out: bool = typer.Option(False, "--json")):
    import asyncio
    doc = asyncio.run(get_source(source).get_document(document_id))
    Cache().set(f"doc:{source}:{document_id}", doc.model_dump(mode="json"))
    _print(doc.model_dump(mode="json"), json_out)


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


if __name__ == "__main__":
    app()
