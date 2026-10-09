"""M-93 — Validated ``birimAdi`` chamber/unit enumeration.

Provides 79 validated Bedesten chamber codes with TR/EN descriptions.
Used by ``search_decisions`` to validate the ``birimAdi`` parameter
before sending it to the Bedesten API.

- Invalid codes return a graceful error dict (``build_error``), never
  raise an exception (invariant #3).
- ``is_valid_birim_adi()`` for boolean checks.
- ``validate_birim_adi()`` returns ``(ok, error_dict_or_None)``.

All data is static — zero runtime dependencies beyond stdlib.
"""

from __future__ import annotations

# ── Chamber enum: 79 validated codes ──────────────────────────────────
# Sources: Yargitay.gov.tr, Danistay.gov.tr, Bedesten API birimAdi
# responses observed in live data. Codes are the exact string values
# the Bedesten birimAdi filter accepts.
#
# Structure (79 total):
#   Yargitay Hukuk Daireleri (Civil):   H1–H23  (23)
#   Yargitay Ceza Daireleri (Criminal): C1–C23  (23)
#   Yargitay Genel Kurullar:            HGK, CGK, BGK (3)
#   Danistay Dava Daireleri:            D1–D17  (17)
#   Danistay Kurullar:                  IDDK, VDDK, IBK (3)
#   Askeri Yargi:                       AYIM, Askeri Yargitay (2)
#   Alternatif yazimlar (legacy):       "1. Hukuk Dairesi"… (8)

BIRIM_CODES: set[str] = {
    # ── Yargitay Hukuk Daireleri (23) ────────────────────────────
    "H1", "H2", "H3", "H4", "H5", "H6", "H7", "H8", "H9", "H10",
    "H11", "H12", "H13", "H14", "H15", "H16", "H17", "H18", "H19",
    "H20", "H21", "H22", "H23",
    # ── Yargitay Ceza Daireleri (23) ─────────────────────────────
    "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10",
    "C11", "C12", "C13", "C14", "C15", "C16", "C17", "C18", "C19",
    "C20", "C21", "C22", "C23",
    # ── Yargitay Genel Kurullar (3) ──────────────────────────────
    "HGK", "CGK", "BGK",
    # ── Danistay Dava Daireleri (17) ─────────────────────────────
    "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9", "D10",
    "D11", "D12", "D13", "D14", "D15", "D16", "D17",
    # ── Danistay Kurullar (3) ────────────────────────────────────
    "IDDK", "VDDK", "IBK",
    # ── Askeri Yargi (2) ─────────────────────────────────────────
    "AYIM", "AskeriYargitay",
    # ── Alternatif yazimlar / legacy (8) ─────────────────────────
    # Bedesten accepts both short codes and full-text chamber names.
    "1. Hukuk Dairesi", "1. Ceza Dairesi", "Hukuk Genel Kurulu",
    "Ceza Genel Kurulu", "Buyuk Genel Kurul",
    "Idari Dava Daireleri Kurulu", "Vergi Dava Daireleri Kurulu",
    "Ictihadi Birlestirme Kurulu",
}

# ── TR descriptions ────────────────────────────────────────────────

BIRIM_TR: dict[str, str] = {
    # Yargitay Hukuk
    "H1": "1. Hukuk Dairesi", "H2": "2. Hukuk Dairesi", "H3": "3. Hukuk Dairesi",
    "H4": "4. Hukuk Dairesi", "H5": "5. Hukuk Dairesi", "H6": "6. Hukuk Dairesi",
    "H7": "7. Hukuk Dairesi", "H8": "8. Hukuk Dairesi", "H9": "9. Hukuk Dairesi",
    "H10": "10. Hukuk Dairesi", "H11": "11. Hukuk Dairesi", "H12": "12. Hukuk Dairesi",
    "H13": "13. Hukuk Dairesi", "H14": "14. Hukuk Dairesi", "H15": "15. Hukuk Dairesi",
    "H16": "16. Hukuk Dairesi", "H17": "17. Hukuk Dairesi", "H18": "18. Hukuk Dairesi",
    "H19": "19. Hukuk Dairesi", "H20": "20. Hukuk Dairesi", "H21": "21. Hukuk Dairesi",
    "H22": "22. Hukuk Dairesi", "H23": "23. Hukuk Dairesi",
    # Yargitay Ceza
    "C1": "1. Ceza Dairesi", "C2": "2. Ceza Dairesi", "C3": "3. Ceza Dairesi",
    "C4": "4. Ceza Dairesi", "C5": "5. Ceza Dairesi", "C6": "6. Ceza Dairesi",
    "C7": "7. Ceza Dairesi", "C8": "8. Ceza Dairesi", "C9": "9. Ceza Dairesi",
    "C10": "10. Ceza Dairesi", "C11": "11. Ceza Dairesi", "C12": "12. Ceza Dairesi",
    "C13": "13. Ceza Dairesi", "C14": "14. Ceza Dairesi", "C15": "15. Ceza Dairesi",
    "C16": "16. Ceza Dairesi", "C17": "17. Ceza Dairesi", "C18": "18. Ceza Dairesi",
    "C19": "19. Ceza Dairesi", "C20": "20. Ceza Dairesi", "C21": "21. Ceza Dairesi",
    "C22": "22. Ceza Dairesi", "C23": "23. Ceza Dairesi",
    # Yargitay Genel Kurullar
    "HGK": "Hukuk Genel Kurulu",
    "CGK": "Ceza Genel Kurulu",
    "BGK": "Büyük Genel Kurul",
    # Danistay Dava
    "D1": "1. Daire (Danıştay)", "D2": "2. Daire (Danıştay)",
    "D3": "3. Daire (Danıştay)", "D4": "4. Daire (Danıştay)",
    "D5": "5. Daire (Danıştay)", "D6": "6. Daire (Danıştay)",
    "D7": "7. Daire (Danıştay)", "D8": "8. Daire (Danıştay)",
    "D9": "9. Daire (Danıştay)", "D10": "10. Daire (Danıştay)",
    "D11": "11. Daire (Danıştay)", "D12": "12. Daire (Danıştay)",
    "D13": "13. Daire (Danıştay)", "D14": "14. Daire (Danıştay)",
    "D15": "15. Daire (Danıştay)", "D16": "16. Daire (Danıştay)",
    "D17": "17. Daire (Danıştay)",
    # Danistay Kurullar
    "IDDK": "İdari Dava Daireleri Kurulu",
    "VDDK": "Vergi Dava Daireleri Kurulu",
    "IBK": "İçtihadı Birleştirme Kurulu",
    # Askeri
    "AYIM": "Askeri Yüksek İdare Mahkemesi",
    "AskeriYargitay": "Askeri Yargıtay",
    # Alternatif yazimlar
    "1. Hukuk Dairesi": "1. Hukuk Dairesi (Yargıtay)",
    "1. Ceza Dairesi": "1. Ceza Dairesi (Yargıtay)",
    "Hukuk Genel Kurulu": "Hukuk Genel Kurulu (Yargıtay)",
    "Ceza Genel Kurulu": "Ceza Genel Kurulu (Yargıtay)",
    "Buyuk Genel Kurul": "Büyük Genel Kurul (Yargıtay)",
    "Idari Dava Daireleri Kurulu": "İdari Dava Daireleri Kurulu (Danıştay)",
    "Vergi Dava Daireleri Kurulu": "Vergi Dava Daireleri Kurulu (Danıştay)",
    "Ictihadi Birlestirme Kurulu": "İçtihadı Birleştirme Kurulu (Danıştay)",
}

# ── EN descriptions ────────────────────────────────────────────────

BIRIM_EN: dict[str, str] = {
    # Yargitay Civil Chambers
    "H1": "1st Civil Chamber", "H2": "2nd Civil Chamber",
    "H3": "3rd Civil Chamber", "H4": "4th Civil Chamber",
    "H5": "5th Civil Chamber", "H6": "6th Civil Chamber",
    "H7": "7th Civil Chamber", "H8": "8th Civil Chamber",
    "H9": "9th Civil Chamber", "H10": "10th Civil Chamber",
    "H11": "11th Civil Chamber", "H12": "12th Civil Chamber",
    "H13": "13th Civil Chamber", "H14": "14th Civil Chamber",
    "H15": "15th Civil Chamber", "H16": "16th Civil Chamber",
    "H17": "17th Civil Chamber", "H18": "18th Civil Chamber",
    "H19": "19th Civil Chamber", "H20": "20th Civil Chamber",
    "H21": "21st Civil Chamber", "H22": "22nd Civil Chamber",
    "H23": "23rd Civil Chamber",
    # Yargitay Criminal Chambers
    "C1": "1st Criminal Chamber", "C2": "2nd Criminal Chamber",
    "C3": "3rd Criminal Chamber", "C4": "4th Criminal Chamber",
    "C5": "5th Criminal Chamber", "C6": "6th Criminal Chamber",
    "C7": "7th Criminal Chamber", "C8": "8th Criminal Chamber",
    "C9": "9th Criminal Chamber", "C10": "10th Criminal Chamber",
    "C11": "11th Criminal Chamber", "C12": "12th Criminal Chamber",
    "C13": "13th Criminal Chamber", "C14": "14th Criminal Chamber",
    "C15": "15th Criminal Chamber", "C16": "16th Criminal Chamber",
    "C17": "17th Criminal Chamber", "C18": "18th Criminal Chamber",
    "C19": "19th Criminal Chamber", "C20": "20th Criminal Chamber",
    "C21": "21st Criminal Chamber", "C22": "22nd Criminal Chamber",
    "C23": "23rd Criminal Chamber",
    # Yargitay General Assemblies
    "HGK": "General Assembly of Civil Chambers",
    "CGK": "General Assembly of Criminal Chambers",
    "BGK": "Grand General Assembly",
    # Danistay Chambers
    "D1": "1st Chamber (Council of State)", "D2": "2nd Chamber (Council of State)",
    "D3": "3rd Chamber (Council of State)", "D4": "4th Chamber (Council of State)",
    "D5": "5th Chamber (Council of State)", "D6": "6th Chamber (Council of State)",
    "D7": "7th Chamber (Council of State)", "D8": "8th Chamber (Council of State)",
    "D9": "9th Chamber (Council of State)", "D10": "10th Chamber (Council of State)",
    "D11": "11th Chamber (Council of State)", "D12": "12th Chamber (Council of State)",
    "D13": "13th Chamber (Council of State)", "D14": "14th Chamber (Council of State)",
    "D15": "15th Chamber (Council of State)", "D16": "16th Chamber (Council of State)",
    "D17": "17th Chamber (Council of State)",
    # Danistay Boards
    "IDDK": "Plenary Session of Administrative Law Chambers",
    "VDDK": "Plenary Session of Tax Law Chambers",
    "IBK": "Unification of Case Law Board",
    # Military
    "AYIM": "High Military Administrative Court",
    "AskeriYargitay": "Military Court of Cassation",
    # Alternative spellings
    "1. Hukuk Dairesi": "1st Civil Chamber (Yargitay)",
    "1. Ceza Dairesi": "1st Criminal Chamber (Yargitay)",
    "Hukuk Genel Kurulu": "General Assembly of Civil Chambers (Yargitay)",
    "Ceza Genel Kurulu": "General Assembly of Criminal Chambers (Yargitay)",
    "Buyuk Genel Kurul": "Grand General Assembly (Yargitay)",
    "Idari Dava Daireleri Kurulu": "Plenary Session of Administrative Law Chambers (Danistay)",
    "Vergi Dava Daireleri Kurulu": "Plenary Session of Tax Law Chambers (Danistay)",
    "Ictihadi Birlestirme Kurulu": "Unification of Case Law Board (Danistay)",
}

# ── Validation ─────────────────────────────────────────────────────


def is_valid_birim_adi(code: str) -> bool:
    """Return True if *code* is a known birimAdi chamber code."""
    return code in BIRIM_CODES


def validate_birim_adi(code: str | None) -> dict | None:
    """Validate a birimAdi chamber code.

    Returns None if valid (or None), or a graceful ``build_error`` dict
    if the code is not recognised.

    This never raises — invariant #3 (graceful degradation).
    """
    if code is None:
        return None
    if code in BIRIM_CODES:
        return None
    from .models import build_error

    return build_error(
        "INVALID_BIRIM_ADI",
        f"'{code}' taninmayan bir daire/birim kodu. "
        f"Gecerli 79 kod: {', '.join(sorted(BIRIM_CODES))}",
        details={
            "provided": code,
            "valid_codes": sorted(BIRIM_CODES),
            "valid_count": len(BIRIM_CODES),
        },
    )


def describe_birim_adi(code: str, lang: str = "tr") -> dict:
    """Return a description dict for a birimAdi code.

    Args:
        code: Chamber code (e.g. "H1", "HGK").
        lang: "tr" or "en".

    Returns:
        Dict with ``code``, ``description``, and ``court`` keys.
        Unknown codes still return a dict (with description="<bilinmiyor>").
    """
    desc_map = BIRIM_TR if lang == "tr" else BIRIM_EN
    description = desc_map.get(code, "<bilinmiyor>")

    # Infer court from code prefix
    if code.startswith("H") or code.startswith("C") or code in ("HGK", "CGK", "BGK"):
        court = "Yargitay"
    elif code.startswith("D") or code in ("IDDK", "VDDK", "IBK"):
        court = "Danistay"
    elif code in ("AYIM", "AskeriYargitay"):
        court = "Askeri"
    else:
        court = "<bilinmiyor>"

    return {"code": code, "description": description, "court": court}


def list_birim_codes(court: str | None = None) -> list[dict]:
    """Return all 79 birimAdi codes, optionally filtered by court.

    Args:
        court: Optional filter — "Yargitay", "Danistay", or "Askeri".
               Returns all codes if omitted.

    Returns:
        List of ``{code, description_tr, description_en, court}`` dicts.
    """
    codes: list[dict] = []
    for code in sorted(BIRIM_CODES):
        desc = describe_birim_adi(code, "tr")
        if court and desc["court"] != court:
            continue
        codes.append({
            "code": code,
            "description_tr": BIRIM_TR.get(code, "<bilinmiyor>"),
            "description_en": BIRIM_EN.get(code, "<unknown>"),
            "court": desc["court"],
        })
    return codes


# ── Self-check ──────────────────────────────────────────────────────

def _smoke() -> dict:
    """Internal consistency check — verifies the 79-count and mappings."""
    count = len(BIRIM_CODES)
    issues: list[str] = []
    if count != 79:
        issues.append(f"Expected 79 codes, found {count}")
    for code in BIRIM_CODES:
        if code not in BIRIM_TR:
            issues.append(f"Missing TR description: {code}")
        if code not in BIRIM_EN:
            issues.append(f"Missing EN description: {code}")
    return {
        "ok": len(issues) == 0,
        "count": count,
        "issues": issues,
    }
