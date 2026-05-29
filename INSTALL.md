# Emsal-mcp Kurulum

## Geliştirme Ortamı

```bash
cd Emsal-mcp
python -m venv .venv
.\.venv\Scripts\activate
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
