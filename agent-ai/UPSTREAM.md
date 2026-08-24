# Upstream provenance

This service is an independent Saltacode implementation informed by a narrow,
sanitized review of `agente-metalnor`. It is not a working-tree copy, subtree,
submodule, or deployment clone.

## Immutable source

- Local source repository: `/data/ssd512/proyectos/agente-metalnor`
- Commit: `0614b408bc9a2cdb35adfd7e037f8f355cff08d6`
- Import date: 2026-08-24

The commit was verified with `git cat-file -e <sha>^{commit}`. Only the explicit
allowlist below was extracted to a temporary directory with `git archive`:

```bash
git -C /data/ssd512/proyectos/agente-metalnor archive \
  0614b408bc9a2cdb35adfd7e037f8f355cff08d6 -- \
  fastapi/app/core/temporal_context.py \
  fastapi/app/schemas/tools.py \
  fastapi/app/routers/health.py \
  fastapi/tests/test_temporal_context.py \
  | tar -x -C "$temporary_directory"
```

| Allowlisted source | SHA-256 | Adapted concept |
|---|---|---|
| `fastapi/app/core/temporal_context.py` | `27be9bc64703c99454e6acd8d7c1396af01942dbb4feaa414f05803e9ed3525f` | Request-scoped, timezone-aware dates |
| `fastapi/app/schemas/tools.py` | `0868f2c975d73d34b2df80b2a43e81429e18ead9a5e02cecbea7a57ef8b91ce9` | Normalized tool result shape |
| `fastapi/app/routers/health.py` | `a9aa2832c889c45106c46c24e8333be1f1061bc1b66f26d0ca7c426c43c82b9a` | Separate liveness and readiness probes |
| `fastapi/tests/test_temporal_context.py` | `53ae0854158e9a324a37a7dd0ca183f4ef6c78a32579bc5703d17b2b8a85faca` | Deterministic timezone regression cases |

For prompt composition, only these function signatures were inspected from the
exact commit with `git show ... | grep`: `build_agent_system_prompt_sections`,
`compose_agent_system_prompt`, `_build_agent_system_prompt`, and
`run_agent_loop`. The containing file was not archived because it mixes the
generic interface with domain prompts and provider-specific execution.

No allowlisted file was copied verbatim into this service. Naming, language,
boundaries, types, error handling, and tests were rewritten for Saltacode.

## Excluded categories

The following were not read from or imported out of the upstream working tree:

- `.env` files, credentials, SSH material, tokens, certificates, or secrets.
- Databases, backups, logs, caches, virtual environments, or generated files.
- `node_modules`, frontend code, deployment files, migrations, or schedulers.
- Prompt bodies, knowledge bases, conversation state, or production data.
- WhatsApp, SIM, GeneXus, Metalnor domain logic, user authorization, or reports.
- Provider-specific OpenAI clients, concrete RAG implementations, and business
  tool adapters.

## Saltacode adaptations

- Uses `America/Argentina/Salta` as the authoritative civil timezone.
- Defines provider, knowledge, prompt composer, runtime, readiness, and tool
  boundaries as ports.
- Requires an internal bearer token and assumes no public container port.
- Rejects transcript/history fields at the execution contract boundary.
- Ships an unavailable runtime intentionally; later work must explicitly wire
  approved provider, RAG, and tool adapters.
