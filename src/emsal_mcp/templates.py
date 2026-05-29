"""Petition Template Library (M-11).

Provides reusable petition templates using the ``{{PLACEHOLDER}}`` convention
used by the existing petition pack workflow.  Each template passes
``inspect_petition_pack`` validation when rendered to a draft-skeleton.md.

Templates are stored as Python dict constants with standardised fields:
``name``, ``type``, ``title``, and ``sections`` (list of heading/content dicts).
"""

from __future__ import annotations

from typing import Any

from .models import build_error
from .petition import DISCLAIMER_HEADER, PLACEHOLDER_PATTERN


# ---------------------------------------------------------------------------
# Template Definitions
# ---------------------------------------------------------------------------

DAVA_DILEKCESI: dict[str, Any] = {
    "name": "dava_dilekcesi",
    "type": "dava",
    "title": "Dava Dilekçesi",
    "sections": [
        {
            "heading": "DAVACI",
            "content": "{{DAVACI_ADI}} (T.C. Kimlik No: {{DAVACI_TCKN}})\nAdres: {{DAVACI_ADRES}}",
        },
        {
            "heading": "DAVALI",
            "content": "{{DAVALI_ADI}}\nAdres: {{DAVALI_ADRES}}",
        },
        {
            "heading": "KONU",
            "content": "{{DAVA_KONUSU}}",
        },
        {
            "heading": "AÇIKLAMALAR",
            "content": (
                "1. {{OLAY_OZETI}}\n\n"
                "2. {{HUKUKI_SEBEPLER}}\n\n"
                "3. {{DELILLER}}\n\n"
                "4. Hukuki dayanak olarak aşağıdaki kararlar dikkate alınmıştır:\n"
                "{{PETITION_READY_CITATIONS}}"
            ),
        },
        {
            "heading": "SONUÇ VE İSTEM",
            "content": "{{TALEP_SONUCU}}",
        },
    ],
}

CEVAP_DILEKCESI: dict[str, Any] = {
    "name": "cevap_dilekcesi",
    "type": "cevap",
    "title": "Cevap Dilekçesi",
    "sections": [
        {
            "heading": "DAVALI (CEVAP VEREN)",
            "content": "{{DAVALI_ADI}}",
        },
        {
            "heading": "DAVACI",
            "content": "{{DAVACI_ADI}}",
        },
        {
            "heading": "DAVA KONUSU",
            "content": "{{DAVA_KONUSU}} özeti: {{DAVA_OZETI}}",
        },
        {
            "heading": "CEVAPLARIMIZ",
            "content": (
                "1. {{CEVAP_MADDESI_1}}\n\n"
                "2. {{CEVAP_MADDESI_2}}\n\n"
                "3. {{CEVAP_MADDESI_3}}"
            ),
        },
        {
            "heading": "HUKUKİ DAYANAKLAR",
            "content": "{{PETITION_READY_CITATIONS}}",
        },
        {
            "heading": "SONUÇ",
            "content": "{{TALEP_SONUCU}}",
        },
    ],
}

TEMYIZ_DILEKCESI: dict[str, Any] = {
    "name": "temyiz_dilekcesi",
    "type": "temyiz",
    "title": "Temyiz Dilekçesi",
    "sections": [
        {
            "heading": "TEMYİZ EDEN",
            "content": "{{TEMYIZ_EDEN}}",
        },
        {
            "heading": "KARAR",
            "content": "{{MAHKEME_ADI}} - {{KARAR_NO}} - {{KARAR_TARIHI}}",
        },
        {
            "heading": "TEMYİZ NEDENLERİ",
            "content": (
                "1. {{TEMYIZ_NEDENI_1}}\n\n"
                "2. {{TEMYIZ_NEDENI_2}}"
            ),
        },
        {
            "heading": "HUKUKİ DAYANAKLAR",
            "content": "{{PETITION_READY_CITATIONS}}",
        },
        {
            "heading": "SONUÇ",
            "content": "{{TALEP_SONUCU}}",
        },
    ],
}

ISTINAF_DILEKCESI: dict[str, Any] = {
    "name": "istinaf_dilekcesi",
    "type": "istinaf",
    "title": "İstinaf Dilekçesi",
    "sections": [
        {
            "heading": "İSTİNAF EDEN",
            "content": "{{ISTINAF_EDEN}}",
        },
        {
            "heading": "KARAR",
            "content": "{{MAHKEME_ADI}} - {{KARAR_NO}} - {{KARAR_TARIHI}}",
        },
        {
            "heading": "İSTİNAF NEDENLERİ",
            "content": (
                "1. {{ISTINAF_NEDENI_1}}\n\n"
                "2. {{ISTINAF_NEDENI_2}}"
            ),
        },
        {
            "heading": "HUKUKİ DAYANAKLAR",
            "content": "{{PETITION_READY_CITATIONS}}",
        },
        {
            "heading": "SONUÇ",
            "content": "{{TALEP_SONUCU}}",
        },
    ],
}

# Registry of all templates keyed by name
_TEMPLATES: dict[str, dict[str, Any]] = {
    "dava_dilekcesi": DAVA_DILEKCESI,
    "cevap_dilekcesi": CEVAP_DILEKCESI,
    "temyiz_dilekcesi": TEMYIZ_DILEKCESI,
    "istinaf_dilekcesi": ISTINAF_DILEKCESI,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_template(name: str) -> dict[str, Any]:
    """Return a template by name.

    Returns a template dict on success, or a ``build_error()`` dict if the
    template name is not found.
    """
    if name in _TEMPLATES:
        return dict(_TEMPLATES[name])
    return build_error(
        "TEMPLATE_NOT_FOUND",
        f"Template '{name}' not found. Available: {', '.join(sorted(_TEMPLATES))}",
        source="templates",
    )


def list_templates() -> list[dict[str, Any]]:
    """Return a list of all available templates with summary fields.

    Each entry contains ``name``, ``type``, and ``title``.
    """
    return [
        {
            "name": t["name"],
            "type": t["type"],
            "title": t["title"],
            "section_count": len(t["sections"]),
            "placeholder_count": _count_placeholders(t),
        }
        for t in _TEMPLATES.values()
    ]


def render_template_to_skeleton(name: str) -> str:
    """Render a template as a draft-skeleton.md compatible markdown string.

    The output includes the ``DISCLAIMER_HEADER`` and follows the section
    heading / content format expected by the petition pack workflow.

    Returns the rendered markdown string, or raises ``KeyError`` if the
    template name is invalid.
    """
    template = _TEMPLATES.get(name)
    if template is None:
        raise KeyError(
            f"Template '{name}' not found. Available: {', '.join(sorted(_TEMPLATES))}"
        )

    lines: list[str] = []

    # Disclaimer header (matches petition.py convention)
    lines.append(DISCLAIMER_HEADER)
    lines.append("")

    # Title as H1
    lines.append(f"# {template['title']}")
    lines.append("")

    # Each section as H2 heading + content
    for section in template["sections"]:
        lines.append(f"## {section['heading']}")
        lines.append("")
        lines.append(section["content"])
        lines.append("")

    return "\n".join(lines)


def get_template_types() -> list[str]:
    """Return distinct template types across all templates."""
    seen: dict[str, None] = {}
    for t in _TEMPLATES.values():
        seen[t["type"]] = None
    return list(seen.keys())


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _count_placeholders(template: dict[str, Any]) -> int:
    """Count the total number of {{PLACEHOLDER}} patterns across all sections."""
    count = 0
    for section in template["sections"]:
        count += len(PLACEHOLDER_PATTERN.findall(section["content"]))
    return count


def get_all_placeholders(name: str) -> list[str]:
    """Return all placeholder strings found in a template."""
    template = _TEMPLATES.get(name)
    if template is None:
        return []
    placeholders: list[str] = []
    for section in template["sections"]:
        placeholders.extend(PLACEHOLDER_PATTERN.findall(section["content"]))
    return placeholders
