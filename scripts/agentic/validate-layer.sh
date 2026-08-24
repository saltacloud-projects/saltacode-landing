#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

required_files=(
  AGENTS.md
  README.md
  .gitignore
  .codex/config.toml
  docs/discovery/initial-baseline.md
  docs/discovery/production-baseline.md
  docs/architecture/technology-direction.md
  docs/architecture/ai-chat-boundary.md
  docs/quality/seo-performance-contract.md
  docs/agentic/tooling.md
  .github/workflows/agentic-layer.yml
)

agent_names=(
  repo_explorer
  seo_auditor
  performance_auditor
  frontend_implementer
  chat_integration_architect
  release_verifier
)

skill_names=(
  production-discovery
  seo-regression
  performance-budget
  asset-optimization
  accessibility-quality
  ai-chat-boundary
  cloudflare-release
)

for file in "${required_files[@]}"; do
  [[ -f "$file" ]] || fail "missing required file: $file"
done

grep -Eq '^\[agents\][[:space:]]*$' .codex/config.toml || fail '.codex/config.toml must define [agents]'
grep -Eq '^enabled[[:space:]]*=[[:space:]]*true[[:space:]]*$' .codex/config.toml || fail 'agents.enabled must be true'
grep -Eq '^max_concurrent_threads_per_session[[:space:]]*=[[:space:]]*4[[:space:]]*$' .codex/config.toml || fail 'agent thread cap must be 4'
if grep -Eq '^(model|model_reasoning_effort|approval_policy|sandbox_mode)[[:space:]]*=' .codex/config.toml; then
  fail '.codex/config.toml must not pin models or override sandbox/approval policy'
fi

for name in "${agent_names[@]}"; do
  file=".codex/agents/${name}.toml"
  [[ -f "$file" ]] || fail "missing agent: $file"
  grep -Eq "^name[[:space:]]*=[[:space:]]*\"${name}\"[[:space:]]*$" "$file" || fail "$file has an invalid name"
  grep -Eq '^description[[:space:]]*=[[:space:]]*"[^"]+"[[:space:]]*$' "$file" || fail "$file needs a one-line description"
  grep -Eq '^developer_instructions[[:space:]]*=[[:space:]]*"""' "$file" || fail "$file needs developer_instructions"
  if grep -Eq '^(model|model_reasoning_effort|approval_policy)[[:space:]]*=' "$file"; then
    fail "$file must inherit model and approval settings"
  fi
done

for name in "${skill_names[@]}"; do
  file=".agents/skills/${name}/SKILL.md"
  [[ -f "$file" ]] || fail "missing skill: $file"
  [[ "$(head -n 1 "$file")" == '---' ]] || fail "$file has no opening frontmatter delimiter"
  grep -Eq "^name:[[:space:]]+${name}[[:space:]]*$" "$file" || fail "$file has an invalid name"
  grep -Eq '^description: "Trigger: .+"$' "$file" || fail "$file has an invalid trigger description"
  grep -Eq '^license: Apache-2.0$' "$file" || fail "$file has an invalid license"
  grep -Eq '^  author: "Oscar Vargas"$' "$file" || fail "$file has an invalid author"
  grep -Eq '^  version: "1.0"$' "$file" || fail "$file has an invalid version"
  if grep -Eq 'https?://' "$file"; then
    fail "$file contains a non-local reference"
  fi

  previous=0
  for section in 'Activation Contract' 'Hard Rules' 'Decision Gates' 'Execution Steps' 'Output Contract' 'References'; do
    line="$(grep -n -m1 "^## ${section}$" "$file" | cut -d: -f1 || true)"
    [[ -n "$line" ]] || fail "$file is missing section: $section"
    (( line > previous )) || fail "$file has sections out of order"
    previous="$line"
  done
done

printf 'Agentic layer validation passed: %d agents, %d skills.\n' "${#agent_names[@]}" "${#skill_names[@]}"
