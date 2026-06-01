# Data egress and third-party processing controls

This repository contains cybersecurity skills and helper scripts that may process
sensitive company artifacts such as logs, indicators of compromise, URLs,
hashes, cloud metadata, tickets, memory/disk artifacts, and vulnerability scan
results. Treat every script as untrusted automation until its outbound behavior is
reviewed for the target environment.

## Baseline policy

- **No silent third-party sharing:** scripts should not send collected or
  processed data to public SaaS, threat-intelligence, LLM, telemetry, paste, chat,
  or analytics services unless the skill explicitly documents that behavior.
- **Offline/local-first by default:** prefer local parsing, local rules, local
  enrichment caches, and internally hosted services for corporate data.
- **Explicit consent for enrichment:** any call to VirusTotal, Shodan, AbuseIPDB,
  GreyNoise, urlscan.io, OTX, MISP/OpenCTI, cloud APIs, or similar services must
  be intentionally enabled by the operator and approved for the data type being
  submitted.
- **No implicit telemetry:** do not add analytics, crash reporting, model tracing,
  prompt logging, or package-level telemetry without an opt-in control and clear
  documentation.
- **Network allowlisting:** run skills in an environment with egress firewalling.
  Allow only internal endpoints and specifically approved third-party APIs.
- **TLS stays on:** certificate verification must remain enabled by default. If a
  lab requires self-signed certificates, expose an explicit `--insecure` option
  and print a warning.
- **Secrets stay local:** API keys and tokens must come from environment
  variables, vaults, or runtime prompts. Do not hardcode real credentials in
  skills, fixtures, or reports.

## Review workflow for company use

1. Run the static egress scanner before importing or updating skills:

   ```bash
   python3 tools/audit-data-egress.py --format markdown > data-egress-report.md
   ```

2. Review all `high` and `medium` findings. A finding is not automatically a
   leak; it is a path where data can leave the local process.
3. For each approved third-party integration, document:
   - destination service and hostname,
   - data types submitted,
   - legal/business approval,
   - API key source,
   - retention expectations,
   - compensating controls such as anonymization or hashing.
4. Run skills inside a constrained execution profile:
   - no default internet route for offline analysis skills,
   - proxy or firewall logs enabled for enrichment skills,
   - read-only mounts for evidence unless output is required,
   - separate lab credentials from production credentials.
5. Re-run the scanner and review dependency changes whenever scripts are added or
   updated.

## Static scanner

`tools/audit-data-egress.py` inventories potential egress points using only the
Python standard library. It detects:

- hardcoded HTTP/HTTPS URLs,
- common outbound network imports such as `requests`, `urllib`, `boto3`,
  `paramiko`, `socket`, `smtplib`, `dns`, and selected API clients,
- direct outbound call sites such as `requests.get(...)` and
  `urllib.request.urlopen(...)`,
- disabled TLS verification via `verify=False` or `session.verify = False`.

Example CI-friendly commands:

```bash
# Inventory all findings without failing the build.
python3 tools/audit-data-egress.py --format json > data-egress-report.json

# Fail if any high-severity egress risk is present.
python3 tools/audit-data-egress.py --fail-on high
```

## Important limitation

Static scanning cannot guarantee that libraries never contact third parties at
runtime. Some dependencies may perform network activity dynamically, through
plugins, environment variables, default cloud credentials, DNS lookups, update
checks, or native binaries. For high-assurance environments, combine this repo
level review with dependency pinning, SBOM review, package allowlisting, proxy
inspection, DNS logging, and default-deny egress controls.
