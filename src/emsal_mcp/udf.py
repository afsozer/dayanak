from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Optional

from .models import build_error


class UdfError(ValueError):
    pass


UDF_TOOLKIT_VERSION = "0.9.0"
COMMAND_TIMEOUT_SECONDS = 30
DEFAULT_UDF_TOOLKIT_REPO = "https://github.com/saidsurucu/UDF-Toolkit.git"
BUNDLED_UDF_TOOLKIT_DIR = Path(__file__).resolve().parents[2] / "vendor" / "UDF-Toolkit"

UDF_AUTHORING_WARNING = (
    "UDF authoring must be verified manually in UYAP Dokuman Editor before official use."
)

DOCX_TO_UDF_EXPERIMENTAL_WARNING = (
    "The old pure-Python DOCX -> UDF writer has been disabled. DOCX -> UDF now uses "
    "the external UDF-Toolkit docx_to_udf.py script and still requires manual UYAP "
    "Dokuman Editor verification."
)


def _resolve_toolkit_dir() -> Optional[Path]:
    """Resolve UDF-Toolkit directory using local-yargi's candidate order."""
    candidates: list[str] = []
    for env_var in ("EMSAL_UDF_TOOLKIT_DIR", "UDF_TOOLKIT_PATH", "UDF_TOOLKIT_DIR"):
        val = os.environ.get(env_var, "").strip()
        if val:
            candidates.append(val)

    candidates.extend(
        [
            str(BUNDLED_UDF_TOOLKIT_DIR),
            str(Path.cwd() / "tools" / "UDF-Toolkit"),
            str(Path.home() / "tools" / "UDF-Toolkit"),
            str(Path.home() / "UDF-Toolkit"),
            r"C:\Users\Sozer\tools\UDF-Toolkit",
            r"C:\Users\Sozer\UDF-Toolkit",
        ]
    )

    for raw in candidates:
        p = Path(raw).expanduser().resolve()
        if p.is_dir() and (p / "udf_to_docx.py").exists():
            return p
    return None


def _looks_like_udf_toolkit(path: Path) -> bool:
    return path.is_dir() and (path / "udf_to_docx.py").exists()


def install_udf_toolkit(
    target_dir: str | Path | None = None,
    repo_url: str = DEFAULT_UDF_TOOLKIT_REPO,
    *,
    update: bool = False,
) -> dict:
    """Install or update the managed UDF-Toolkit clone."""
    target = Path(target_dir) if target_dir else BUNDLED_UDF_TOOLKIT_DIR
    target = target.expanduser().resolve()

    if _looks_like_udf_toolkit(target) and not update:
        return {
            "ok": True,
            "action": "install_udf_toolkit",
            "installed": False,
            "updated": False,
            "toolkit_dir": str(target),
            "message": "UDF-Toolkit is already installed.",
            "status": get_udf_toolkit_status(),
        }

    git_cmd = shutil.which("git")
    if not git_cmd:
        return build_error(
            "GIT_UNAVAILABLE",
            "git is required to install UDF-Toolkit automatically.",
            action="install_udf_toolkit",
            target_dir=str(target),
            repo_url=repo_url,
        )

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if update and (target / ".git").exists():
                result = subprocess.run(
                    [git_cmd, "-C", str(target), "pull", "--ff-only"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False,
                )
                if result.returncode != 0:
                    return build_error(
                        "GIT_PULL_FAILED",
                        result.stderr.strip() or result.stdout.strip(),
                        action="install_udf_toolkit",
                        stdout=result.stdout.strip(),
                        stderr=result.stderr.strip(),
                        target_dir=str(target),
                    )
                return {
                    "ok": True,
                    "action": "install_udf_toolkit",
                    "installed": False,
                    "updated": True,
                    "toolkit_dir": str(target),
                    "stdout": result.stdout.strip(),
                    "status": get_udf_toolkit_status(),
                }
            return build_error(
                "TARGET_EXISTS_NOT_TOOLKIT",
                f"Target exists but does not look like UDF-Toolkit: {target}",
                action="install_udf_toolkit",
                target_dir=str(target),
            )

        result = subprocess.run(
            [git_cmd, "clone", "--depth", "1", repo_url, str(target)],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if result.returncode != 0:
            return build_error(
                "GIT_CLONE_FAILED",
                result.stderr.strip() or result.stdout.strip(),
                action="install_udf_toolkit",
                stdout=result.stdout.strip(),
                stderr=result.stderr.strip(),
                target_dir=str(target),
                repo_url=repo_url,
            )
        if not _looks_like_udf_toolkit(target):
            return build_error(
                "INVALID_TOOLKIT_REPO",
                f"Cloned repository does not contain udf_to_docx.py: {target}",
                action="install_udf_toolkit",
                target_dir=str(target),
                repo_url=repo_url,
            )
        return {
            "ok": True,
            "action": "install_udf_toolkit",
            "installed": True,
            "updated": False,
            "toolkit_dir": str(target),
            "stdout": result.stdout.strip(),
            "status": get_udf_toolkit_status(),
        }
    except subprocess.TimeoutExpired:
        return build_error(
            "INSTALL_TIMEOUT",
            "Timed out while installing UDF-Toolkit.",
            action="install_udf_toolkit",
            target_dir=str(target),
            repo_url=repo_url,
        )
    except Exception as exc:
        return build_error(
            "INSTALL_FAILED",
            str(exc),
            action="install_udf_toolkit",
            target_dir=str(target),
            repo_url=repo_url,
        )


_discover_libreoffice = staticmethod(
    lambda: shutil.which("soffice") or shutil.which("libreoffice") or shutil.which("soffice.exe")
)
_discover_unoconv = staticmethod(lambda: shutil.which("unoconv"))
_discover_python = staticmethod(lambda: shutil.which("python") or shutil.which("python3") or shutil.which("py"))


def _run_text_command(args: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def get_udf_toolkit_status() -> dict:
    """Check whether external UDF-Toolkit scripts are available."""
    toolkit_dir = _resolve_toolkit_dir()
    env_enabled = os.environ.get("LOCAL_YARGI_UDF_TOOLS") == "1" or os.environ.get("EMSAL_UDF_TOOLS") == "1"
    disabled = os.environ.get("EMSAL_UDF_TOOLS") == "0" or os.environ.get("LOCAL_YARGI_UDF_TOOLS") == "0"
    managed = bool(toolkit_dir and toolkit_dir == BUNDLED_UDF_TOOLKIT_DIR.resolve())
    enabled = bool((env_enabled or managed) and not disabled)
    python_cmd = _discover_python()
    warnings: list[str] = []

    scripts_found = {
        "udf_to_docx": bool(toolkit_dir and (toolkit_dir / "udf_to_docx.py").exists()),
        "udf_to_pdf": bool(toolkit_dir and (toolkit_dir / "udf_to_pdf.py").exists()),
        "docx_to_udf": bool(toolkit_dir and (toolkit_dir / "docx_to_udf.py").exists()),
    }
    dependencies = {
        "python-docx": False,
        "PyMuPDF": False,
        "Pillow": False,
        "reportlab": False,
    }

    python_version: str | None = None
    if python_cmd:
        try:
            version_result = _run_text_command([python_cmd, "--version"], timeout=5)
            python_version = (version_result.stdout or version_result.stderr).strip() or None
        except Exception as exc:
            warnings.append(f"Python version check failed: {exc}")

        dep_code = (
            "deps = ['docx', 'fitz', 'PIL', 'reportlab']; out = []\n"
            "for dep in deps:\n"
            "    try:\n"
            "        __import__(dep); out.append(dep + ':1')\n"
            "    except ImportError:\n"
            "        out.append(dep + ':0')\n"
            "print(','.join(out))"
        )
        try:
            dep_result = _run_text_command([python_cmd, "-c", dep_code], timeout=10)
            for part in dep_result.stdout.strip().split(","):
                name, _, val = part.partition(":")
                ok = val == "1"
                if name == "docx":
                    dependencies["python-docx"] = ok
                elif name == "fitz":
                    dependencies["PyMuPDF"] = ok
                elif name == "PIL":
                    dependencies["Pillow"] = ok
                elif name == "reportlab":
                    dependencies["reportlab"] = ok
        except Exception as exc:
            warnings.append(f"Python dependency check failed: {exc}")
    else:
        warnings.append("Python ('python', 'python3' or 'py') was not found on PATH.")

    if not toolkit_dir:
        warnings.append("UDF-Toolkit was not found or toolkit path is not configured.")
    elif not enabled:
        warnings.append(
            f"UDF-Toolkit detected at {toolkit_dir}, but integration is disabled. "
            "Set LOCAL_YARGI_UDF_TOOLS=1 or EMSAL_UDF_TOOLS=1, or remove EMSAL_UDF_TOOLS=0."
        )
    else:
        if not scripts_found["udf_to_docx"]:
            warnings.append("udf_to_docx.py was not found under UDF-Toolkit.")
        if not scripts_found["udf_to_pdf"]:
            warnings.append("udf_to_pdf.py was not found under UDF-Toolkit.")
        if not scripts_found["docx_to_udf"]:
            warnings.append("docx_to_udf.py was not found under UDF-Toolkit.")

    if python_cmd:
        missing = [name for name, ok in dependencies.items() if not ok]
        if missing:
            warnings.append(f"Missing Python packages: {', '.join(missing)}.")

    configured = bool(enabled and toolkit_dir)
    ok = bool(configured and python_cmd and all(scripts_found.values()))

    return {
        "ok": ok,
        "enabled": enabled,
        "configured": configured,
        "pythonAvailable": python_cmd is not None,
        "pythonVersion": python_version,
        "pythonCmd": python_cmd,
        "toolkitPath": str(toolkit_dir) if toolkit_dir else None,
        "toolkit_dir": str(toolkit_dir) if toolkit_dir else None,
        "managedToolkitPath": str(BUNDLED_UDF_TOOLKIT_DIR.resolve()),
        "managed": managed,
        "scriptsFound": scripts_found,
        "dependencies": dependencies,
        "libreoffice_path": _discover_libreoffice(),
        "unoconv_path": _discover_unoconv(),
        "version": UDF_TOOLKIT_VERSION,
        "warnings": warnings,
    }


def get_udf_authoring_instructions(format: str = "json") -> dict:
    steps = [
        "Use UDF-Toolkit scripts for DOCX/UDF conversion.",
        "Open generated UDF files in UYAP Dokuman Editor and verify manually.",
        "Do not treat generated UDF files as officially valid until round-trip verification passes.",
        "Keep placeholders in {{...}} format.",
    ]
    warnings = [
        UDF_AUTHORING_WARNING,
        "Direct UDF generation does not guarantee full UYAP compatibility.",
    ]

    if format == "markdown":
        lines = ["# UDF Authoring Instructions", "", "## Steps"]
        lines.extend(f"{idx}. {step}" for idx, step in enumerate(steps, 1))
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in warnings)
        return {
            "format": "markdown",
            "instructions": "\n".join(lines),
            "warnings": warnings,
            "version": UDF_TOOLKIT_VERSION,
        }

    return {
        "format": "json",
        "steps": steps,
        "warnings": warnings,
        "version": UDF_TOOLKIT_VERSION,
        "toolkit_status": get_udf_toolkit_status(),
    }


def read_udf(path: str | Path) -> str:
    """Read and extract text content from a UYAP UDF file."""
    p = Path(path)
    if not p.exists():
        raise UdfError(f"UDF bulunamadi: {p}")
    if p.read_bytes()[:2] != b"PK":
        raise UdfError("Gecersiz UDF: ZIP imzasi yok")

    try:
        with zipfile.ZipFile(p) as zf:
            if "content.xml" not in zf.namelist():
                raise UdfError("Invalid UDF: content.xml missing")
            xml = zf.read("content.xml").decode("utf-8", errors="ignore")
    except UdfError:
        raise
    except Exception as exc:
        raise UdfError(f"Failed to parse UDF ZIP structure: {exc}") from exc

    cdata = re.findall(r"<content>\s*<!\[CDATA\[([\s\S]*?)\]\]>\s*</content>", xml)
    if cdata:
        raw_text = "\n".join(cdata)
    else:
        contents = re.findall(r"<content>([\s\S]*?)</content>", xml)
        if contents:
            raw_text = "\n".join(contents)
        else:
            paragraphs = re.findall(r"<paragraph[^>]*>([\s\S]*?)</paragraph>", xml)
            raw_text = "\n".join(paragraphs) if paragraphs else xml

    return html.unescape(re.sub(r"<[^>]*>", "", raw_text)).strip()


def udf_to_markdown(path: str | Path) -> str:
    """Convert a UDF file content to basic markdown paragraphs."""
    lines = [ln.strip() for ln in read_udf(path).splitlines()]
    paragraphs: list[str] = []
    cur: list[str] = []
    for line in lines:
        if line:
            cur.append(line)
        elif cur:
            paragraphs.append(" ".join(cur))
            cur = []
    if cur:
        paragraphs.append(" ".join(cur))
    return "\n\n".join(paragraphs)


def write_udf(text: str, out_path: str | Path, *, title_centered: bool = False) -> Path:
    """Write a simple UDF package. Caller must verify in UYAP Dokuman Editor."""
    out = Path(out_path)
    paragraphs = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    pool = "\n".join(paragraphs)
    offset = 0
    elements: list[str] = []
    for idx, para in enumerate(paragraphs):
        length = len(para) + (1 if idx < len(paragraphs) - 1 else 0)
        align = "1" if idx == 0 and title_centered else "3"
        attrs = ' bold="true"' if idx == 0 and title_centered else ""
        elements.append(
            f'<paragraph Alignment="{align}" LineSpacing="0.14999998">'
            f'<content startOffset="{offset}" length="{length}"{attrs} /></paragraph>'
        )
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
    """Probe a UDF file using the local-yargi-style status shape."""
    p = Path(path)
    absolute = p.resolve()
    info: dict = {
        "filePath": str(absolute),
        "path": str(p),
        "exists": p.exists(),
        "isUdfLike": p.suffix.lower() == ".udf",
        "isZipLike": False,
        "zip": False,
        "hasContentXml": False,
        "has_content_xml": False,
        "contentXmlSize": 0,
        "parseableXml": False,
        "textCharCount": 0,
        "text_length": 0,
        "format_id": None,
        "content_xml_preview": None,
        "warnings": [],
        "recommendedNextStep": "",
    }

    if not p.exists():
        info["warnings"].append("File does not exist on the local filesystem.")
        info["recommendedNextStep"] = "Check the file path and try again."
        return info

    data = p.read_bytes()
    if not data:
        info["warnings"].append("File is empty (0 bytes).")
        info["recommendedNextStep"] = "Ensure the file contains valid UDF data."
        return info

    info["isZipLike"] = len(data) >= 4 and data[:4] == b"PK\x03\x04"
    info["zip"] = info["isZipLike"]
    if not info["isZipLike"]:
        info["warnings"].append("File lacks standard ZIP local header signature (PK\\x03\\x04).")

    try:
        with zipfile.ZipFile(p) as zf:
            names = zf.namelist()
            info["hasContentXml"] = "content.xml" in names
            info["has_content_xml"] = info["hasContentXml"]
            if not info["hasContentXml"]:
                info["warnings"].append("content.xml was not found inside the ZIP package.")
                info["recommendedNextStep"] = "Make sure this is a genuine UYAP UDF document."
                return info

            zinfo = zf.getinfo("content.xml")
            info["contentXmlSize"] = zinfo.file_size
            xml = zf.read("content.xml").decode("utf-8", errors="ignore")
            info["content_xml_preview"] = xml[:500]
            m = re.search(r'<template[^>]+format_id=["\']([^"\']+)', xml)
            info["format_id"] = m.group(1) if m else None

        text = read_udf(p)
        info["parseableXml"] = True
        info["textCharCount"] = len(text)
        info["text_length"] = len(text)
        if text:
            info["recommendedNextStep"] = "Use 'emsal-mcp udf read' or 'emsal-mcp udf to-md' to read document content."
        else:
            info["warnings"].append("UDF content extracted successfully but contains no readable text.")
    except Exception as exc:
        info["warnings"].append(str(exc))
        info["recommendedNextStep"] = "Verify file integrity or check with UYAP Dokuman Editor."

    return info


def _toolkit_unavailable(action: str) -> dict:
    status = get_udf_toolkit_status()
    return build_error(
        "TOOLKIT_UNAVAILABLE",
        "UDF-Toolkit is not enabled or properly configured.",
        action=action,
        toolkit_status=status,
        recommended_next_steps=[
            "Set LOCAL_YARGI_UDF_TOOLS=1 or EMSAL_UDF_TOOLS=1.",
            "Set UDF_TOOLKIT_PATH or EMSAL_UDF_TOOLKIT_DIR to a UDF-Toolkit clone.",
        ],
    )


def _ensure_udf_toolkit_for_conversion() -> dict:
    status = get_udf_toolkit_status()
    if status["enabled"] and status["configured"]:
        return status
    if os.environ.get("EMSAL_UDF_AUTO_INSTALL") == "0":
        return status

    installed = install_udf_toolkit()
    if not installed.get("ok"):
        status["autoInstall"] = installed
        return status
    return get_udf_toolkit_status()


def _run_udf_toolkit_script(script_name: str, args: list[str], action: str) -> dict:
    status = _ensure_udf_toolkit_for_conversion()
    if not status["enabled"] or not status["configured"]:
        return _toolkit_unavailable(action)
    if not status["pythonAvailable"] or not status["pythonCmd"]:
        return build_error(
            "PYTHON_UNAVAILABLE",
            "Python is not available to run UDF-Toolkit.",
            action=action,
            toolkit_status=status,
        )

    toolkit_dir = Path(status["toolkitPath"])
    script_path = toolkit_dir / script_name
    if not script_path.exists():
        return build_error(
            "SCRIPT_NOT_FOUND",
            f"Script not found: {script_path}",
            action=action,
            toolkit_status=status,
        )

    try:
        result = subprocess.run(
            [status["pythonCmd"], str(script_path), *args],
            cwd=toolkit_dir,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return build_error(
            "TOOLKIT_TIMEOUT",
            f"UDF-Toolkit command timed out after {COMMAND_TIMEOUT_SECONDS}s.",
            action=action,
            toolkit_status=status,
        )
    except Exception as exc:
        return build_error("EXCEPTION", str(exc), action=action, toolkit_status=status)

    if result.returncode != 0:
        return build_error(
            "CONVERSION_FAILED",
            result.stderr.strip() or result.stdout.strip() or "UDF-Toolkit conversion failed",
            action=action,
            stdout=result.stdout.strip(),
            stderr=result.stderr.strip(),
            toolkit_status=status,
        )

    return {
        "ok": True,
        "action": action,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "toolkit_status": status,
    }


def convert_udf_to_docx(file_path: str | Path, out_path: str | Path | None = None) -> dict:
    """Convert UDF to DOCX via UDF-Toolkit udf_to_docx.py."""
    action = "convert_udf_to_docx"
    src = Path(file_path)
    if not src.exists():
        return build_error("FILE_NOT_FOUND", f"UDF file not found: {src}", action=action)

    out = Path(out_path) if out_path else src.with_suffix(".docx")
    result = _run_udf_toolkit_script("udf_to_docx.py", [str(src), str(out)], action)
    if not result.get("ok"):
        return result
    return {
        **result,
        "out_path": str(out),
        "file_size": out.stat().st_size if out.exists() else 0,
        "warning": UDF_AUTHORING_WARNING,
    }


def convert_udf_to_pdf(file_path: str | Path, out_path: str | Path | None = None) -> dict:
    """Convert UDF to PDF via UDF-Toolkit udf_to_pdf.py."""
    action = "convert_udf_to_pdf"
    src = Path(file_path)
    if not src.exists():
        return build_error("FILE_NOT_FOUND", f"UDF file not found: {src}", action=action)

    out = Path(out_path) if out_path else src.with_suffix(".pdf")
    result = _run_udf_toolkit_script("udf_to_pdf.py", [str(src), str(out)], action)
    if not result.get("ok"):
        return result
    return {**result, "out_path": str(out), "file_size": out.stat().st_size if out.exists() else 0}


def convert_docx_to_udf_experimental(
    file_path: str | Path,
    out_path: str | Path | None = None,
    experimental: bool = False,
) -> dict:
    """Convert DOCX to UDF via UDF-Toolkit docx_to_udf.py.

    The function name is retained for API compatibility. The old experimental
    pure-Python converter is disabled and ignored.
    """
    action = "convert_docx_to_udf_experimental"
    src = Path(file_path)
    if not src.exists():
        return build_error("FILE_NOT_FOUND", f"DOCX file not found: {src}", action=action)

    out = Path(out_path) if out_path else src.with_suffix(".udf")
    result = _run_udf_toolkit_script("docx_to_udf.py", [str(src), str(out)], action)
    if not result.get("ok"):
        return result

    if not out.exists():
        auto_out = src.with_suffix(".udf")
        if auto_out.exists():
            try:
                out.parent.mkdir(parents=True, exist_ok=True)
                auto_out.replace(out)
            except Exception as exc:
                return build_error(
                    "OUTPUT_MOVE_FAILED",
                    str(exc),
                    action=action,
                    stdout=result.get("stdout", ""),
                )
        else:
            return build_error(
                "OUTPUT_MISSING",
                f"Expected UDF output was not created: {out}",
                action=action,
                stdout=result.get("stdout", ""),
            )

    return {
        **result,
        "out_path": str(out),
        "file_size": out.stat().st_size if out.exists() else 0,
        "warning": UDF_AUTHORING_WARNING,
        "experimental": False,
    }
