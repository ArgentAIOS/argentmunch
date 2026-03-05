# Security Policy — ArgentMunch

## Supported Versions

| Version | Supported |
|---|---|
| main (pre-release) | ✅ Active development |
| < 1.0.0 | ⚠️ No SLA — report issues but no guarantee of fix timeline |

---

## Reporting a Vulnerability

**Do NOT open a public GitHub issue for security vulnerabilities.**

Report security issues privately:
- **Email:** jbrashear@titaniumcomputing.com
- **Subject line:** `[SECURITY] ArgentMunch - <brief description>`
- **Expected response:** Within 72 hours
- **Resolution target:** Critical issues patched within 7 days

Include in your report:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (optional)

---

## Data Handling Policy

ArgentMunch indexes source code. The following rules apply to all indexed data:

1. **Local-only by default** — indexed symbol data stays on the machine running the server
2. **No telemetry** — ArgentMunch does not phone home or transmit code to external services
3. **Index storage** — stored in `~/.code-index/` (local disk only)
4. **No cloud sync** — index data is never synced to external storage without explicit operator configuration
5. **Sensitive file detection** — files matching secret patterns are excluded from indexing (see below)

---

## Repo Allowlist Policy

ArgentMunch only indexes repos that are explicitly configured by the operator.

- No auto-discovery of repos on disk
- Repos must be explicitly added to the index configuration
- Wildcards require explicit opt-in
- MAO agents may only query repos in the allowlist — no arbitrary repo access

---

## Secret Exclusion Policy

ArgentMunch **never** indexes files matching these patterns:

```
.env
.env.*
*.key
*.pem
*.p12
*.pfx
*.cert
*.crt
secrets/
.secrets/
credentials/
config/secrets*
**/*secret*
**/*password*
**/*token*
**/*api_key*
```

These exclusions are enforced at the file discovery layer — matching files are skipped before any content is read.

**Additional hardening:**
- Symbol extraction never logs file content — only symbol names, types, and locations
- Query results never return raw file content — only structured symbol metadata

---

## Known Inherited Risks (from jCodeMunch upstream)

ArgentMunch inherits the following security controls from jCodeMunch:

- **Path traversal prevention** — all paths validated to be descendants of repo root
- **Symlink escape protection** — symlinks outside repo root are rejected
- **GitHub API token scoping** — only `repo:read` scope required

See [upstream SECURITY.md](https://github.com/jgravelle/jcodemunch-mcp/blob/main/SECURITY.md) for full upstream controls.

---

*Last updated: 2026-03-04 | ArgentOS / ArgentAIOS team*
