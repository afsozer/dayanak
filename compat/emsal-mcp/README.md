# emsal-mcp → Dayanak

Bu proje 2.0.0 sürümüyle **Dayanak** adını aldı. `emsal-mcp` paketi artık yalnızca
[`dayanak`](https://pypi.org/project/dayanak/) paketini kurar; eski `emsal-mcp` ve
`emsal-mcp-server` komutları ile `import emsal_mcp` çalışmaya devam eder, ama yeni
kurulumlarda doğrudan `dayanak` kullanın:

```bash
pip install dayanak
claude mcp add dayanak -- uvx --from dayanak dayanak-server
```

Eski `EMSAL_*` ortam değişkenleri ve `~/.emsal_mcp` veri dizini Dayanak tarafından
okunmaya devam eder.

This project was renamed to **Dayanak** in 2.0.0. This package only installs
[`dayanak`](https://pypi.org/project/dayanak/); the old commands and `import emsal_mcp`
keep working, but new installs should use `dayanak` directly.

Kaynak / source: https://github.com/afsozer/dayanak
