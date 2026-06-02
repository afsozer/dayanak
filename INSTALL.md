# Emsal-mcp Kurulum

## Geliştirme Ortamı

```bash
# Repo dizinine geçin
cd <repo-dizini>

# Sanal ortam oluştur
python -m venv .venv

# Sanal ortamı aktive et (Windows)
.\.venv\Scripts\Activate.ps1    # PowerShell
# veya
.\.venv\Scripts\activate         # cmd.exe

# Sanal ortamı aktive et (macOS / Linux)
source .venv/bin/activate

# Paketi kur
pip install -e .
```

## Dev + Test Araçları

```bash
pip install -e ".[dev]"
```

## MCP Server Desteği

```bash
pip install -e ".[mcp]"
```

## UDF (LibreOffice Entegrasyonu)

```bash
pip install -e ".[udf]"
```

## İzole Kurulum (pipx)

```bash
pipx install .
```

## On-the-fly (uvx)

```bash
uvx --from . emsal-mcp version
```
