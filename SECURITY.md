# Security Policy

## Security maintainer

Dayanak has a single security maintainer, Alpaslan Fatih Sözer
(GitHub [@afsozer](https://github.com/afsozer)), who receives every report,
decides on fixes and publishes security advisories.

## Reporting a vulnerability

Please do not open a public issue for a security problem. Report it privately
through GitHub's private vulnerability reporting: open the repository's
**Security** tab and choose **Report a vulnerability**, or go directly to
<https://github.com/afsozer/dayanak/security/advisories/new>.

If you cannot use GitHub, email bilgi@avfatihsozer.com with a subject line
that starts with `[SECURITY] dayanak`.

A useful report names the affected version or commit, says how the server was
run (stdio or streamable HTTP, and which tool profile), lists the steps to
reproduce the problem and explains what an attacker could achieve with it. A
working exploit is not required; a clear description is enough.

## What to expect

- Your report is acknowledged within 3 business days.
- An initial assessment, saying whether the issue is accepted and how severe it
  is, follows within 10 business days.
- Accepted issues are fixed or mitigated as soon as practical, with a target of
  30 days for critical and high-severity issues.
- Disclosure is coordinated: once a fix is released, a GitHub Security Advisory
  is published and, where the issue qualifies, a CVE is requested through
  GitHub. Reporters are credited unless they ask not to be. If a fix takes
  longer, the advisory is published no later than 90 days after the report
  unless we agree on a different date.

## Supported versions

Security fixes are made on the latest release line.

| Version | Supported |
| ------- | --------- |
| 1.0.x   | Yes       |
| < 1.0   | No        |

## Scope

In scope is the code in this repository, including the MCP server and its stdio
and streamable HTTP transports, the command-line tools, the document export
pipeline and the source adapters.

Out of scope:

- the accuracy or completeness of court decisions and legislation, which is a
  data-quality question rather than a security one (please open a normal issue);
- vulnerabilities in the official sources that the adapters query, such as
  mevzuat.gov.tr or the Ministry of Justice's Bedesten service, which should be
  reported to their operators;
- publicly known vulnerabilities in third-party dependencies, unless Dayanak
  uses the dependency in a way that makes them exploitable;
- installations run by other people.

## Safe harbour

Good-faith research that follows this policy is welcome. Test only against your
own installation, do not access data that is not yours, and do not degrade
services that others rely on, including the public sources the adapters query.
Research carried out this way will not be the subject of legal action by the
maintainer.

## Türkçe özet

Güvenlik açıklarını herkese açık issue olarak değil, deponun **Security**
sekmesindeki **Report a vulnerability** bağlantısıyla ya da konu satırı
`[SECURITY] dayanak` ile başlayan bir e-postayla bilgi@avfatihsozer.com
adresine bildirin. Bildirimler 3 iş günü içinde yanıtlanır; düzeltme
yayımlandıktan sonra GitHub güvenlik duyurusu çıkar ve uygunsa CVE istenir.
Testleri yalnızca kendi kurulumunuzda yapın.
