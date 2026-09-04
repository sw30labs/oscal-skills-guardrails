# Changelog

## Unreleased

### Security — deepagents 0.7 recursive delete

deepagents 0.7 classifies recursive `delete` as a write operation, so prior
write-allow rules could authorize subtree deletion. Guardrails now always append
a deny-write permission on `/**` (unless policy explicitly allows delete) and,
when the API is present, wire a read-biased `FilesystemMiddleware` tool
allowlist (`ls` / `read_file` / `glob` / `grep`) from `create_guarded_deep_agent`.
Optional dependency pin raised to `deepagents>=0.7.13`.
