from __future__ import annotations

import base64
import re
from urllib.parse import quote

from .base import SourceClient, client, html_to_text, metadata_doc, sha
from emsal_mcp.models import ContentStatus, Document, SearchResult


def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _url_id(url: str) -> str:
    return "url:" + base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")


def _decode_url_id(document_id: str) -> str:
    if not document_id.startswith("url:"):
        return document_id
    raw = document_id[4:]
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode()


class AymClient(SourceClient):
    source_id = "aym"
    name = "Anayasa Mahkemesi"
    base = "https://kararlarbilgibankasi.anayasa.gov.tr"

    async def search(self, query: str, limit: int = 10, **filters) -> list[SearchResult]:
        params = f"KelimeAra[]={quote(query)}"
        if filters.get("start_date"):
            params += f"&KararTarihiBaslangic={quote(_ymd_to_dmy(filters['start_date']))}"
        if filters.get("end_date"):
            params += f"&KararTarihiBitis={quote(_ymd_to_dmy(filters['end_date']))}"
        async with client() as c:
            r = await c.get(f"{self.base}/Ara?{params}")
            r.raise_for_status()
            html = r.text
        results: list[SearchResult] = []
        pattern = re.compile(r'href="(?:https?://kararlarbilgibankasi\.anayasa\.gov\.tr)?/BB/(\d+/\d+)"[\s\S]*?<titles[^>]*>([\s\S]*?)<a[\s\S]*?<div class="kararbilgileri">\s*([\s\S]*?)</div>\s*<div class="basvurukonualani">\s*([\s\S]*?)</div>', re.I)
        for appno, title_html, info_html, summary_html in pattern.findall(html):
            info = html_to_text(info_html)
            results.append(SearchResult(source=self.source_id, document_id=f"BB/{appno}", title=html_to_text(title_html) or f"AYM {appno}", summary=html_to_text(summary_html).replace("BAŞVURU KONUSU:", "").strip()[:1000], court="Anayasa Mahkemesi", decision_date=_first_date(info), esas_no=appno, source_url=f"{self.base}/BB/{appno}", content_status=ContentStatus.METADATA_ONLY, metadata={"info": info}))
            if len(results) >= limit:
                break
        if results:
            return results
        return [SearchResult(source=self.source_id, document_id=f"search:{quote(query)}", title=f"AYM arama: {query}", summary=html_to_text(html)[:1000], source_url=f"{self.base}/Ara?{params}", content_status=ContentStatus.METADATA_ONLY)]

    async def get_document(self, document_id: str, **kwargs) -> Document:
        url = document_id if document_id.startswith("http") else f"{self.base}/BB/{document_id}"
        async with client() as c:
            r = await c.get(url)
            r.raise_for_status()
            html = r.text
        text = html_to_text(html)
        return Document(source=self.source_id, document_id=document_id, title=f"AYM {document_id}", markdown=text, full_text=text, source_url=url, content_status=ContentStatus.HTML_MARKDOWN, content_hash=sha(text))


class DanistayClient(SourceClient):
    source_id = "danistay"
    name = "Danıştay"
    base = "https://karararama.danistay.gov.tr"

    async def search(self, query: str, limit: int = 10, **filters) -> list[SearchResult]:
        payload = {"data": {"andKelimeler": [f'"{query.strip().strip(chr(34))}"'] if query.strip() else [], "orKelimeler": [], "notAndKelimeler": [], "notOrKelimeler": [], "pageSize": limit, "pageNumber": filters.get("page", 1)}}
        async with client() as c:
            r = await c.post(f"{self.base}/aramalist", json=payload, headers={"X-Requested-With": "XMLHttpRequest"})
            r.raise_for_status()
            data = r.json()
        items = data.get("data", {}).get("data") or data.get("data") or []
        return [SearchResult(source=self.source_id, document_id=str(i.get("id") or i.get("documentId")), title=i.get("daire") or i.get("title") or "Danıştay kararı", decision_date=i.get("kararTarihi"), esas_no=i.get("esasNo"), karar_no=i.get("kararNo"), content_status=ContentStatus.METADATA_ONLY, metadata=i) for i in items[:limit]]

    async def get_document(self, document_id: str, **kwargs) -> Document:
        url = f"{self.base}/getDokuman?id={quote(document_id)}&arananKelime="
        async with client() as c:
            r = await c.get(url)
            r.raise_for_status()
            html = r.text
        text = html_to_text(html)
        return Document(source=self.source_id, document_id=document_id, title=f"Danıştay {document_id}", markdown=text, full_text=text, source_url=url, content_status=ContentStatus.HTML_MARKDOWN, content_hash=sha(text))


class GibClient(SourceClient):
    source_id = "gib"
    name = "Gelir İdaresi Başkanlığı"
    base = "https://gib.gov.tr/api"

    async def search(self, query: str, limit: int = 10, **filters) -> list[SearchResult]:
        q = "KDV" if "katma değer vergisi" in query.lower() or "katma deger vergisi" in query.lower() else query
        payload = {"status": 2, "deleted": False, "ktype": 99, "title": q, "kanunNo": q, "description": q}
        if filters.get("start_date"):
            payload["ozelgeStartDate"] = filters["start_date"] + ("T00:00:00.000Z" if "T" not in filters["start_date"] else "")
        if filters.get("end_date"):
            payload["ozelgeEndDate"] = filters["end_date"] + ("T23:59:59.999Z" if "T" not in filters["end_date"] else "")
        async with client() as c:
            r = await c.post(f"{self.base}/gibportal/mevzuat/ozelge/list?page={int(filters.get('page',1))-1}&size={limit}&sortFieldName=ozelgeTarih&sortType=DESC", json=payload)
            r.raise_for_status()
            data = r.json()
        items = data.get("resultContainer", {}).get("content") or data.get("content") or data.get("data", {}).get("content") or []
        return [SearchResult(source=self.source_id, document_id=str(i.get("id")), title=i.get("title") or i.get("baslik") or "GİB özelge", summary=html_to_text(i.get("description") or "")[:1000], court="Gelir İdaresi Başkanlığı", chamber=i.get("kanunTitle"), decision_date=i.get("ozelgeTarih") or i.get("tarih"), esas_no=i.get("kanunNo"), karar_no=i.get("ozelgeNo"), source_url=i.get("siteLink"), content_status=ContentStatus.METADATA_ONLY, metadata=i) for i in items[:limit] if i.get("id")]

    async def get_document(self, document_id: str, **kwargs) -> Document:
        payload = {"status": 2, "deleted": False, "ktype": 99, "id": int(document_id)}
        async with client() as c:
            r = await c.post(f"{self.base}/gibportal/mevzuat/ozelge/list?page=0&size=1", json=payload)
            r.raise_for_status()
            data = r.json()
        item = (data.get("resultContainer", {}).get("content") or data.get("content") or [None])[0]
        if not item:
            return metadata_doc(self.source_id, document_id, "GİB belge detayı", metadata={"not_found": True})
        text = html_to_text("\n".join([str(item.get("title") or ""), str(item.get("ozelgeNo") or ""), str(item.get("ozelgeTarih") or ""), str(item.get("description") or "")]))
        return Document(source=self.source_id, document_id=document_id, title=item.get("title") or f"GİB {document_id}", summary=text[:1000], court="Gelir İdaresi Başkanlığı", chamber=item.get("kanunTitle"), decision_date=item.get("ozelgeTarih"), esas_no=item.get("kanunNo"), karar_no=item.get("ozelgeNo"), source_url=item.get("siteLink"), markdown=text, full_text=text, content_status=ContentStatus.HTML_MARKDOWN, content_hash=sha(text), raw=data, metadata=item)


class UrlSearchClient(SourceClient):
    def __init__(self, source_id: str, name: str, search_url: str):
        self.source_id = source_id
        self.name = name
        self.search_url = search_url

    async def search(self, query: str, limit: int = 10, **filters) -> list[SearchResult]:
        url = self.search_url.format(q=quote(query))
        async with client() as c:
            r = await c.get(url)
            r.raise_for_status()
            html = r.text
        return [SearchResult(source=self.source_id, document_id=url, title=f"{self.name} arama: {query}", summary=html_to_text(html)[:1000], source_url=url, content_status=ContentStatus.HTML_MARKDOWN)]

    async def get_document(self, document_id: str, **kwargs) -> Document:
        async with client() as c:
            r = await c.get(document_id)
            r.raise_for_status()
            html = r.text
        text = html_to_text(html)
        return Document(source=self.source_id, document_id=document_id, title=f"{self.name} belge", markdown=text, full_text=text, source_url=document_id, content_status=ContentStatus.HTML_MARKDOWN, content_hash=sha(text))


class UyusmazlikClient(SourceClient):
    source_id = "uyusmazlik"
    name = "Uyuşmazlık Mahkemesi"
    base = "https://kararlar.uyusmazlik.gov.tr"

    async def search(self, query: str, limit: int = 10, **filters) -> list[SearchResult]:
        async with client() as c:
            r = await c.get(f"{self.base}/")
            r.raise_for_status()
            initial = r.text
            form = {"txtSearch": query, "btnSearch": "Ara", "rblSearchScope": "All"}
            for key in ["__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"]:
                m = re.search(rf'name=["\']{key}["\'][^>]*value=["\']([^"\']*)', initial, re.I)
                if m:
                    form[key] = m.group(1)
            r = await c.post(f"{self.base}/", data=form, headers={"Content-Type": "application/x-www-form-urlencoded"})
            r.raise_for_status()
            html = r.text
        out: list[SearchResult] = []
        for row in re.findall(r"<tr[\s\S]*?</tr>", html, re.I):
            href = re.search(r'<a[^>]+href=["\']([^"\']+)["\']', row, re.I)
            cols = [html_to_text(x) for x in re.findall(r"<td[^>]*>([\s\S]*?)</td>", row, re.I)]
            if not href or len(cols) < 2:
                continue
            url = href.group(1) if href.group(1).startswith("http") else f"{self.base}/{href.group(1).lstrip('/')}"
            out.append(SearchResult(source=self.source_id, document_id=_url_id(url), title="Uyuşmazlık Mahkemesi | " + " | ".join(cols[:2]), summary=" | ".join(cols[2:5])[:1000], court="Uyuşmazlık Mahkemesi", decision_date=_first_date(" ".join(cols)), source_url=url, content_status=ContentStatus.PDF_LINK_ONLY if url.lower().endswith(".pdf") else ContentStatus.METADATA_ONLY, metadata={"columns": cols}))
            if len(out) >= limit:
                break
        return out

    async def get_document(self, document_id: str, **kwargs) -> Document:
        url = _decode_url_id(document_id)
        if url.lower().endswith(".pdf"):
            return Document(source=self.source_id, document_id=document_id, title="Uyuşmazlık Mahkemesi PDF", source_url=url, markdown=f"PDF karar bağlantısı: {url}", content_status=ContentStatus.PDF_LINK_ONLY, metadata={"pdfUrl": url})
        async with client() as c:
            r = await c.get(url)
            r.raise_for_status()
            html = r.text
        text = html_to_text(html)
        return Document(source=self.source_id, document_id=document_id, title="Uyuşmazlık Mahkemesi Kararı", court="Uyuşmazlık Mahkemesi", decision_date=_first_date(text), source_url=url, markdown=text, full_text=text, content_status=ContentStatus.HTML_MARKDOWN, content_hash=sha(text), raw=html)


class RekabetClient(SourceClient):
    source_id = "rekabet"
    name = "Rekabet Kurumu"
    base = "https://www.rekabet.gov.tr"

    async def search(self, query: str, limit: int = 10, **filters) -> list[SearchResult]:
        async with client() as c:
            r = await c.get(f"{self.base}/tr/Kararlar?PdfText={quote(query)}")
            r.raise_for_status()
            html = r.text
        out = []
        for table in re.findall(r"<table[^>]*equalDivide[\s\S]*?</table>", html, re.I):
            kid = (re.search(r"kararId=([^\"'\s&]+)", table, re.I) or [None, None])[1]
            if not kid:
                continue
            title = html_to_text((re.search(r"<a[^>]+href=[\"'][^\"']*Karar\?kararId=[^\"']+[\"'][^>]*>([\s\S]*?)</a>", table, re.I) or [None, ""])[1])
            txt = html_to_text(table)
            out.append(SearchResult(source=self.source_id, document_id=kid, title=title or f"Rekabet Kurumu Kararı {kid}", summary=txt[:1000], court="Rekabet Kurumu", decision_date=_first_date(txt), source_url=f"{self.base}/Karar?kararId={quote(kid)}", content_status=ContentStatus.METADATA_ONLY, metadata={"htmlText": txt}))
            if len(out) >= limit:
                break
        return out

    async def get_document(self, document_id: str, **kwargs) -> Document:
        url = f"{self.base}/Karar?kararId={quote(document_id)}"
        async with client() as c:
            r = await c.get(url)
            r.raise_for_status()
            html = r.text
        text = html_to_text(html)
        pdf = (re.search(r'href=["\']([^"\']+\.pdf[^"\']*)', html, re.I) or [None, None])[1]
        return Document(source=self.source_id, document_id=document_id, title=f"Rekabet Kurumu Kararı {document_id}", court="Rekabet Kurumu", decision_date=_first_date(text), source_url=url, markdown=text, full_text=text, content_status=ContentStatus.HTML_MARKDOWN if text else ContentStatus.PDF_LINK_ONLY, content_hash=sha(text) if text else None, raw=html, metadata={"pdfUrl": pdf})


class SayistayClient(SourceClient):
    source_id = "sayistay"
    name = "Sayıştay"
    base = "https://www.sayistay.gov.tr"
    endpoints = {
        "daire": ("/KararlarDaire", "/KararlarDaire/DataTablesList", "/KararlarDaire/Detay"),
        "temyiz_kurulu": ("/KararlarTemyiz", "/KararlarTemyiz/DataTablesList", "/KararlarTemyiz/Detay"),
        "genel_kurul": ("/KararlarGenelKurul", "/KararlarGenelKurul/DataTablesList", "/KararlarGenelKurul/Detay"),
    }

    async def search(self, query: str, limit: int = 10, **filters) -> list[SearchResult]:
        kind = filters.get("kind") or filters.get("chamber") or "daire"
        if kind not in self.endpoints:
            kind = "daire"
        page, list_ep, detail = self.endpoints[kind]
        form = {"draw": "1", "start": "0", "length": str(limit), "search[value]": "", "search[regex]": "false", "order[0][column]": "2", "order[0][dir]": "desc"}
        for idx, name in enumerate(["YARGILAMADAIRESI", "KARARTRH", "KARARNO", "YARGILAMADAIRESI", "WEBKARARMETNI", ""]):
            form[f"columns[{idx}][data]"] = name
            form[f"columns[{idx}][name]"] = ""
            form[f"columns[{idx}][searchable]"] = "true"
            form[f"columns[{idx}][orderable]"] = "false" if idx == 5 else "true"
            form[f"columns[{idx}][search][value]"] = ""
            form[f"columns[{idx}][search][regex]"] = "false"
        if kind == "daire":
            form["KararlarDaireAra.WEBKARARMETNI"] = query
            form["KararlarDaireAra.YARGILAMADAIRESI"] = "Tüm Daireler"
        elif kind == "temyiz_kurulu":
            form["KararlarTemyizAra.TEMYIZKARAR"] = query
        else:
            form["KararlarGenelKurulAra.KARARTAMAMI"] = query
        async with client() as c:
            r = await c.get(self.base + page)
            r.raise_for_status()
            first = r.text
            tok = (re.search(r'name=["\']__RequestVerificationToken["\'][^>]*value=["\']([^"\']+)', first, re.I) or [None, None])[1]
            if tok:
                form["__RequestVerificationToken"] = tok
            r = await c.post(self.base + list_ep, data=form, headers={"X-Requested-With": "XMLHttpRequest"})
            r.raise_for_status()
            data = r.json()
        out = []
        for row in (data.get("data") or [])[:limit]:
            rid = str(row.get("Id") or row.get("id") or "")
            if not rid:
                continue
            text = _clean(row.get("WEBKARARMETNI") or row.get("KARAROZETI") or row.get("TEMYIZKARAR"))
            out.append(SearchResult(source=self.source_id, document_id=f"{kind}:{rid}", title=f"Sayıştay {kind} {row.get('KARARNO') or rid}", summary=text[:1000], court="Sayıştay", chamber=row.get("YARGILAMADAIRESI") or row.get("ILAMDAIRESI"), decision_date=row.get("KARARTRH") or row.get("KARARTARIH") or row.get("TEMYIZTUTANAKTARIHI"), esas_no=row.get("ILAMNO") or row.get("DOSYANO"), karar_no=row.get("KARARNO") or row.get("TEMYIZTUTANAKNO"), source_url=self.base + detail + "/" + rid + "/", content_status=ContentStatus.METADATA_ONLY, metadata=row))
        return out

    async def get_document(self, document_id: str, **kwargs) -> Document:
        kind, rid = (document_id.split(":", 1) + [""])[:2] if ":" in document_id else ("daire", document_id)
        if kind not in self.endpoints:
            kind = "daire"
        url = self.base + self.endpoints[kind][2] + f"/{quote(rid)}/"
        async with client() as c:
            r = await c.get(url)
            r.raise_for_status()
            html = r.text
        text = html_to_text(html)
        return Document(source=self.source_id, document_id=document_id, title=f"Sayıştay {kind} {rid}", court="Sayıştay", decision_date=_first_date(text), source_url=url, markdown=text, full_text=text, content_status=ContentStatus.HTML_MARKDOWN, content_hash=sha(text), raw=html)


def _first_date(text: str):
    m = re.search(r"\d{1,2}[./]\d{1,2}[./]\d{4}", text or "")
    return m.group(0) if m else None


def _ymd_to_dmy(value: str) -> str:
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", value or "")
    return f"{m.group(3).zfill(2)}/{m.group(2).zfill(2)}/{m.group(1)}" if m else value
