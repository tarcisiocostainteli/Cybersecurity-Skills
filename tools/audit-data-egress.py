#!/usr/bin/env python3
"""Audit repository files for potential data egress paths.

The scanner is intentionally conservative: it does not prove that a script leaks
information, but it inventories code paths and hard-coded endpoints that can send
processed artifacts, indicators, logs, or credentials outside the local runtime.
It uses only the Python standard library so it can run in restricted enterprise
build environments.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

DEFAULT_PATHS = ("skills", "tools")
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv"}
TEXT_SUFFIXES = {
    ".md", ".py", ".json", ".yml", ".yaml", ".toml", ".txt", ".sh", ".ps1",
}
PRIVATE_HOST_RE = re.compile(
    r"(^localhost$)|(^127\.)|(^10\.)|(^172\.(1[6-9]|2\d|3[0-1])\.)|(^192\.168\.)|"
    r"(^::1$)|(\.local$)|(\.internal$)|(\.corp$)|(\.lan$)",
    re.IGNORECASE,
)
URL_RE = re.compile(r"https?://[^\s\]\[)('\\\"<>]+")

NETWORK_IMPORTS = {
    "requests": "HTTP client",
    "httpx": "HTTP client",
    "aiohttp": "HTTP client",
    "urllib": "stdlib HTTP client",
    "urllib.request": "stdlib HTTP client",
    "boto3": "AWS SDK",
    "botocore": "AWS SDK",
    "googleapiclient": "Google API client",
    "google.cloud": "Google Cloud SDK",
    "azure": "Azure SDK",
    "paramiko": "SSH client",
    "socket": "raw socket networking",
    "websocket": "WebSocket client",
    "websockets": "WebSocket client",
    "smtplib": "SMTP client",
    "imaplib": "IMAP client",
    "poplib": "POP3 client",
    "ftplib": "FTP client",
    "dns": "DNS client",
    "dns.resolver": "DNS resolver",
    "shodan": "Shodan API client",
    "misp": "MISP client",
    "pymisp": "MISP client",
    "taxii2client": "TAXII client",
    "openai": "OpenAI API client",
    "anthropic": "Anthropic API client",
}

EGRESS_CALLS = {
    "requests.get", "requests.post", "requests.put", "requests.patch", "requests.delete",
    "requests.head", "requests.options", "requests.request",
    "httpx.get", "httpx.post", "httpx.put", "httpx.patch", "httpx.delete", "httpx.request",
    "urllib.request.urlopen", "urllib.request.Request",
    "socket.create_connection", "smtplib.SMTP", "smtplib.SMTP_SSL",
    "ftplib.FTP", "ftplib.FTP_TLS", "websocket.create_connection",
}

THIRD_PARTY_KEYWORDS = {
    "abuseipdb", "alienvault", "anthropic", "api.github.com", "api.greynoise.io",
    "api.openai.com", "api.shodan.io", "censys", "crt.sh", "greynoise", "hybrid-analysis",
    "malpedia", "misp", "otx", "pastebin", "securitytrails", "shodan", "slack.com",
    "telegram", "urlscan", "virustotal",
}


@dataclass(frozen=True)
class Finding:
    severity: str
    category: str
    path: str
    line: int
    detail: str
    evidence: str


def iter_files(paths: Iterable[str]) -> Iterable[Path]:
    for raw in paths:
        root = Path(raw)
        if root.is_file():
            yield root
            continue
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                path = Path(dirpath) / name
                if path.suffix.lower() in TEXT_SUFFIXES:
                    yield path


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            return None
    except OSError:
        return None


def dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = dotted_name(node.value)
        if parent:
            return f"{parent}.{node.attr}"
    return None


def is_private_or_placeholder(hostname: str) -> bool:
    host = hostname.lower().strip("[]")
    if PRIVATE_HOST_RE.search(host):
        return True
    return host in {"example.com", "example.org", "example.net", "test.local"}


def classify_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url.rstrip(".,;"))
    host = parsed.hostname or ""
    if not host:
        return "low", "URL could not be parsed"
    lowered = url.lower()
    if is_private_or_placeholder(host):
        return "info", "local/private/example endpoint"
    if any(keyword in lowered for keyword in THIRD_PARTY_KEYWORDS):
        return "high", "known third-party intelligence/SaaS endpoint"
    return "medium", "public external endpoint"


def scan_urls(path: Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for match in URL_RE.finditer(line):
            url = match.group(0).rstrip(".,;`")
            severity, detail = classify_url(url)
            findings.append(Finding(severity, "hardcoded-url", str(path), lineno, detail, url))
    return findings


def scan_python_ast(path: Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        return [Finding("info", "parse-error", str(path), exc.lineno or 1, "Python AST parse failed", exc.msg)]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                root = name.split(".", 1)[0]
                if name in NETWORK_IMPORTS or root in NETWORK_IMPORTS:
                    findings.append(Finding(
                        "medium", "network-import", str(path), node.lineno,
                        f"imports {NETWORK_IMPORTS.get(name) or NETWORK_IMPORTS.get(root)}", name,
                    ))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".", 1)[0]
            if module in NETWORK_IMPORTS or root in NETWORK_IMPORTS:
                findings.append(Finding(
                    "medium", "network-import", str(path), node.lineno,
                    f"imports {NETWORK_IMPORTS.get(module) or NETWORK_IMPORTS.get(root)}", module,
                ))
        elif isinstance(node, ast.Call):
            call = dotted_name(node.func)
            if call in EGRESS_CALLS:
                findings.append(Finding(
                    "medium", "network-call", str(path), node.lineno,
                    "direct outbound network call", call,
                ))
            if call in {"requests.Session", "httpx.Client", "httpx.AsyncClient"}:
                findings.append(Finding(
                    "medium", "network-client", str(path), node.lineno,
                    "creates reusable outbound network client", call,
                ))
            for keyword in node.keywords:
                if keyword.arg == "verify" and isinstance(keyword.value, ast.Constant) and keyword.value.value is False:
                    findings.append(Finding(
                        "high", "tls-verification-disabled", str(path), node.lineno,
                        "TLS certificate verification disabled for outbound request", "verify=False",
                    ))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                target_name = dotted_name(target)
                if target_name and target_name.endswith(".verify"):
                    if isinstance(node.value, ast.Constant) and node.value.value is False:
                        findings.append(Finding(
                            "high", "tls-verification-disabled", str(path), node.lineno,
                            "TLS certificate verification disabled on reusable session", f"{target_name} = False",
                        ))
    return findings


def summarize(findings: list[Finding]) -> dict[str, int]:
    counts = {"high": 0, "medium": 0, "low": 0, "info": 0}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    return counts


def to_markdown(findings: list[Finding]) -> str:
    counts = summarize(findings)
    lines = [
        "# Data Egress Audit Report",
        "",
        "This report inventories potential outbound data paths. Review each high/medium item before running skills with corporate data.",
        "",
        "## Summary",
        "",
        f"- High: {counts.get('high', 0)}",
        f"- Medium: {counts.get('medium', 0)}",
        f"- Low: {counts.get('low', 0)}",
        f"- Info: {counts.get('info', 0)}",
        "",
        "## Findings",
        "",
        "| Severity | Category | Location | Detail | Evidence |",
        "|---|---|---|---|---|",
    ]
    for f in sorted(findings, key=lambda item: (item.path, item.line, item.severity, item.category)):
        evidence = f.evidence.replace("|", "\\|")[:180]
        detail = f.detail.replace("|", "\\|")
        lines.append(f"| {f.severity} | {f.category} | `{f.path}:{f.line}` | {detail} | `{evidence}` |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit potential third-party data egress paths.")
    parser.add_argument("paths", nargs="*", default=list(DEFAULT_PATHS), help="Files or directories to scan")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--fail-on", choices=("none", "high", "medium"), default="none",
                        help="Return non-zero if findings at or above the selected severity exist")
    args = parser.parse_args(argv)

    findings: list[Finding] = []
    for path in iter_files(args.paths):
        text = read_text(path)
        if text is None:
            continue
        findings.extend(scan_urls(path, text))
        if path.suffix.lower() == ".py":
            findings.extend(scan_python_ast(path, text))

    if args.format == "json":
        print(json.dumps({"summary": summarize(findings), "findings": [asdict(f) for f in findings]}, indent=2))
    else:
        print(to_markdown(findings), end="")

    counts = summarize(findings)
    if args.fail_on == "high" and counts.get("high", 0):
        return 1
    if args.fail_on == "medium" and (counts.get("high", 0) or counts.get("medium", 0)):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
