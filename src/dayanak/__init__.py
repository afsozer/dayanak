import os
from pathlib import Path

__version__ = "2.0.0"


# Proje 2.0.0'da emsal-mcp'den Dayanak'a yeniden adlandirildi.  Mevcut
# kurulumlar (istemci ayarlari, zamanlanmis gorevler, yerel-ayar.cmd) hala
# EMSAL_* adlarini veriyor olabilir; paket ilk import edildiginde bunlar
# DAYANAK_* karsiliklarina kopyalanir.  Ayni degisken iki adla da verilmisse
# yeni ad kazanir.
def _alias_legacy_env() -> None:
    for key, value in list(os.environ.items()):
        if key.startswith("EMSAL_"):
            os.environ.setdefault("DAYANAK_" + key[len("EMSAL_"):], value)


_alias_legacy_env()


def data_home(legacy: str = ".emsal_mcp") -> Path:
    """Varsayilan veri dizini: ``~/.dayanak``.

    Yeni dizin henuz yoksa ve eski adli dizin (``legacy``) varsa eskisi
    kullanilir; boylece 2.0.0'a gecen kurulum onbellegini ve modellerini
    kaybetmez.  Eski surum iki adi da kullaniyordu (``.emsal_mcp`` ve
    ``.emsal-mcp``), cagri yeri hangisini kullaniyorsa onu verir.
    """
    home = Path.home()
    new = home / ".dayanak"
    old = home / legacy
    if not new.exists() and old.exists():
        return old
    return new
