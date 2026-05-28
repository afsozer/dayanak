from __future__ import annotations

import html
import re
import zipfile
from pathlib import Path


class UdfError(ValueError):
    pass


def read_udf(path: str | Path) -> str:
    p = Path(path)
    if not p.exists():
        raise UdfError(f"UDF bulunamadı: {p}")
    if p.read_bytes()[:2] != b"PK":
        raise UdfError("Geçersiz UDF: ZIP imzası yok")
    with zipfile.ZipFile(p) as zf:
        if "content.xml" not in zf.namelist():
            raise UdfError("Geçersiz UDF: content.xml yok")
        xml = zf.read("content.xml").decode("utf-8", errors="ignore")
    m = re.search(r"<content>\s*<!\[CDATA\[([\s\S]*?)\]\]>\s*</content>", xml)
    if m:
        return m.group(1).strip()
    chunks = re.findall(r"<content[^>]*>([\s\S]*?)</content>", xml)
    text = "\n".join(chunks) if chunks else re.sub(r"<[^>]+>", " ", xml)
    return html.unescape(re.sub(r"<[^>]+>", " ", text)).strip()


def udf_to_markdown(path: str | Path) -> str:
    lines = [ln.strip() for ln in read_udf(path).splitlines()]
    paragraphs: list[str] = []
    cur: list[str] = []
    for line in lines:
        if not line:
            if cur:
                paragraphs.append(" ".join(cur))
                cur = []
        else:
            cur.append(line)
    if cur:
        paragraphs.append(" ".join(cur))
    return "\n\n".join(paragraphs)


def write_udf(text: str, out_path: str | Path, *, title_centered: bool = False) -> Path:
    """Write a simple UYAP UDF (format_id=1.8). Caller must verify in UYAP editor."""
    out = Path(out_path)
    paragraphs = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    pool = "\n".join(paragraphs)
    offset = 0
    elements: list[str] = []
    for idx, para in enumerate(paragraphs):
        length = len(para) + (1 if idx < len(paragraphs) - 1 else 0)
        align = "1" if idx == 0 and title_centered else "3"
        attrs = ' bold="true"' if idx == 0 and title_centered else ""
        elements.append(f'<paragraph Alignment="{align}" LineSpacing="0.14999998"><content startOffset="{offset}" length="{length}"{attrs} /></paragraph>')
        offset += length
    xml = f'''<?xml version="1.0" encoding="UTF-8" ?>
<template format_id="1.8">
<content><![CDATA[{pool}]]></content>
<properties><pageFormat mediaSizeName="1" leftMargin="56.69" rightMargin="56.69" topMargin="56.69" bottomMargin="56.69" paperOrientation="1" headerFOffset="20.0" footerFOffset="20.0" /></properties>
<elements resolver="hvl-default">
{''.join(elements)}
</elements>
<styles><style name="default" description="Gecerli" family="Dialog" size="12" bold="false" italic="false" /><style name="hvl-default" family="Times New Roman" size="12" description="Govde" /></styles>
</template>'''
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("content.xml", xml.encode("utf-8"))
    return out


def probe_udf(path: str | Path) -> dict:
    p=Path(path)
    info={"path": str(p), "exists": p.exists(), "zip": False, "has_content_xml": False, "format_id": None, "text_length": 0, "warnings": []}
    if not p.exists():
        return info
    try:
        with zipfile.ZipFile(p) as zf:
            info["zip"] = True
            info["has_content_xml"] = "content.xml" in zf.namelist()
            if info["has_content_xml"]:
                xml=zf.read("content.xml").decode("utf-8", errors="ignore")
                m=re.search(r'<template[^>]+format_id=["\']([^"\']+)', xml)
                info["format_id"]=m.group(1) if m else None
                info["text_length"] = len(read_udf(p))
    except Exception as e:
        info["warnings"].append(str(e))
    return info


UDF_AUTHORING_WARNING = "UDF yazımı deneysel kabul edilmeli; resmi kullanım öncesi UYAP Doküman Editörü'nde manuel round-trip doğrulama yapılmalıdır."
