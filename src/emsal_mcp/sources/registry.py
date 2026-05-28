from __future__ import annotations

from .bedesten import BedestenClient
from .mevzuat import MevzuatClient
from .simple_public import AymClient, DanistayClient, GibClient, RekabetClient, SayistayClient, UyusmazlikClient


class YargitayClient(BedestenClient):
    source_id = "yargitay"
    name = "Yargıtay/Bedesten"


def registry():
    return {
        "bedesten": BedestenClient(),
        "yargitay": YargitayClient(),
        "mevzuat": MevzuatClient(),
        "aym": AymClient(),
        "danistay": DanistayClient(),
        "gib": GibClient(),
        "uyusmazlik": UyusmazlikClient(),
        "rekabet": RekabetClient(),
        "sayistay": SayistayClient(),
    }


def capabilities() -> list[dict]:
    out=[]
    for sid, src in registry().items():
        cap=src.capabilities()
        cap.update({"citationSafeRule":"Only documents with content_status full_text/html_markdown and non-empty text are quote/draft usable.", "noFabrication": True})
        if sid == "kik":
            cap["status"] = "unavailable"
        out.append(cap)
    return out


def get_source(source: str):
    reg = registry()
    if source not in reg:
        raise KeyError(f"Bilinmeyen kaynak: {source}. Geçerli: {', '.join(reg)}")
    return reg[source]
