# LICENSES.md — emsal-mcp Dependency Licenses

Last updated: 2026-05-30

## Core Dependencies

| Package | Version Range | License | Copyleft |
|---------|--------------|---------|----------|
| httpx | >=0.27 | BSD-3-Clause | No |
| beautifulsoup4 | >=4.12 | MIT | No |
| lxml | >=5.0 | BSD-3-Clause | No |
| pydantic | >=2.7 | MIT | No |
| python-docx | >=1.1 | MIT | No |
| typer | >=0.12 | MIT | No |

## Optional Dependencies

### `[mcp]`
| Package | Version Range | License | Copyleft |
|---------|--------------|---------|----------|
| mcp | >=1.0,<2.0 | MIT | No |

### `[embeddings]`
| Package | Version Range | License | Copyleft |
|---------|--------------|---------|----------|
| fastembed | >=0.4,<1.0 | Apache-2.0 | No |

### `[ocr]`
| Package | Version Range | License | Copyleft |
|---------|--------------|---------|----------|
| pypdf | >=4.0,<6.0 | BSD-3-Clause | No |
| pillow | >=10.0,<12.0 | MIT-CMU | No |

### `[udf]`
| Package | Version Range | License | Copyleft |
|---------|--------------|---------|----------|
| python-docx | >=1.1 | MIT | No |

### `[dev]`
| Package | Version Range | License | Copyleft |
|---------|--------------|---------|----------|
| pytest | >=8.0,<9.0 | MIT | No |
| pytest-cov | >=5.0,<7.0 | MIT | No |
| ruff | >=0.5,<1.0 | MIT | No |
| mypy | >=1.0,<2.0 | MIT | No |

## Summary

- **All 13 dependencies** use permissive licenses (MIT, BSD-3-Clause, Apache-2.0).
- **Zero copyleft** concerns (no GPL, LGPL, AGPL, or MPL dependencies).
- emsal-mcp itself is MIT-licensed.
