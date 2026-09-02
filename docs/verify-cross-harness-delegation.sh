#!/bin/sh
# Live, billable canary for the delegation contracts documented in this repo.
# It runs one review and one isolated implementation through each CLI.
set -eu

CELL_TIMEOUT_SECONDS=${CELL_TIMEOUT_SECONDS:-1200}

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'Required command not found: %s\n' "$1" >&2
    exit 2
  }
}

for command_name in claude codex git grok jq; do
  require_command "$command_name"
done
if command -v gtimeout >/dev/null 2>&1; then
  TIMEOUT_BIN=$(command -v gtimeout)
elif command -v timeout >/dev/null 2>&1; then
  TIMEOUT_BIN=$(command -v timeout)
else
  printf 'A timeout implementation is required (gtimeout from coreutils on macOS, or timeout).\n' >&2
  exit 2
fi

printf 'versions\n'
claude --version
grok --version
codex --version

CANARY_ROOT=$(mktemp -d "$HOME/.cross-harness-canary.XXXXXX") || exit 1
RESULTS="$CANARY_ROOT/results.tsv"
FAILURES=0
ACTIVE_PIDS=''

cleanup() {
  if [ "${KEEP_CANARY_ARTIFACTS:-0}" = 1 ]; then
    printf 'Artifacts preserved at %s\n' "$CANARY_ROOT"
    return
  fi
  case "$CANARY_ROOT" in
    "$HOME"/.cross-harness-canary.*) rm -rf "$CANARY_ROOT" ;;
    *) printf 'Refusing to remove unexpected path: %s\n' "$CANARY_ROOT" >&2 ;;
  esac
}
preserve_and_exit() {
  trap - HUP INT TERM
  for pid in $ACTIVE_PIDS; do
    kill "$pid" 2>/dev/null || true
  done
  for pid in $ACTIVE_PIDS; do
    wait "$pid" 2>/dev/null || true
  done
  KEEP_CANARY_ARTIFACTS=1
  exit "$1"
}
trap cleanup EXIT
trap 'preserve_and_exit 129' HUP
trap 'preserve_and_exit 130' INT
trap 'preserve_and_exit 143' TERM

run_with_timeout() {
  exec "$TIMEOUT_BIN" "$CELL_TIMEOUT_SECONDS" "$@"
}

record() {
  printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> "$RESULTS"
}

init_repo() {
  repo=$1
  mkdir -p "$repo"
  git -C "$repo" init -q
  git -C "$repo" config user.name 'Cross Harness Canary'
  git -C "$repo" config user.email 'canary@example.invalid'
  git -C "$repo" config commit.gpgsign false
}

has_terminal_sentinel() {
  grep -Eiq 'Execution error|max turns reached|error_max_turns' "$1"
}

validate_review() {
  harness=$1
  report=$2
  repo=$3
  format=$4
  token=$5
  body=$report

  if [ ! -s "$report" ]; then
    record review "$harness" 'FAIL empty report'
    return 1
  fi
  if [ "$format" = json ] && ! jq -e . "$report" >/dev/null 2>&1; then
    record review "$harness" 'FAIL invalid JSON'
    return 1
  fi
  if [ "$format" = json ]; then
    body="$report.text"
    if ! jq -er '.text | select(type == "string" and length > 0)' "$report" > "$body"; then
      record review "$harness" 'FAIL missing JSON .text report'
      return 1
    fi
  fi
  if has_terminal_sentinel "$body"; then
    record review "$harness" 'FAIL semantic terminal sentinel'
    return 1
  fi
  if ! grep -Fq "$token" "$body"; then
    record review "$harness" 'FAIL missing completion token'
    return 1
  fi
  if ! grep -Eiq 'division by zero|ZeroDivisionError|empty (list|input|values)' "$body"; then
    record review "$harness" 'FAIL missed seeded defect'
    return 1
  fi
  if [ "$(git -C "$repo" status --porcelain)" != ' M calc.py' ]; then
    record review "$harness" 'FAIL review changed the fixture repo'
    return 1
  fi
  if ! cmp -s "$repo/calc.py" "$repo.expected"; then
    record review "$harness" 'FAIL review changed fixture content'
    return 1
  fi
  record review "$harness" PASS
}

validate_implementation() {
  harness=$1
  report=$2
  repo=$3
  format=$4
  expected=$5
  body=$report

  if [ ! -s "$report" ]; then
    record implementation "$harness" 'FAIL empty report'
    return 1
  fi
  if [ "$format" = json ] && ! jq -e . "$report" >/dev/null 2>&1; then
    record implementation "$harness" 'FAIL invalid JSON'
    return 1
  fi
  if [ "$format" = json ]; then
    body="$report.text"
    if ! jq -er '.text | select(type == "string" and length > 0)' "$report" > "$body"; then
      record implementation "$harness" 'FAIL missing JSON .text report'
      return 1
    fi
  fi
  if has_terminal_sentinel "$body"; then
    record implementation "$harness" 'FAIL semantic terminal sentinel'
    return 1
  fi
  if [ "$(cat "$repo/marker.txt")" != "$expected" ]; then
    record implementation "$harness" 'FAIL wrong file content'
    return 1
  fi
  if [ ! -f "$repo/.acceptance-ran" ]; then
    record implementation "$harness" 'FAIL acceptance command did not run'
    return 1
  fi
  if [ "$(git -C "$repo" status --porcelain)" != ' M marker.txt' ]; then
    record implementation "$harness" 'FAIL unexpected worktree diff'
    return 1
  fi
  if [ "$(git -C "$repo" rev-list --count HEAD)" -ne 1 ]; then
    record implementation "$harness" 'FAIL callee wrote Git history'
    return 1
  fi
  record implementation "$harness" PASS
}

make_review_fixture() {
  harness=$1
  repo="$CANARY_ROOT/review-$harness"
  init_repo "$repo"
  printf '%s\n' 'def average(values):' '    if not values:' '        return 0' '    return sum(values) / len(values)' > "$repo/calc.py"
  git -C "$repo" add calc.py
  git -C "$repo" commit -qm seed
  printf '%s\n' 'def average(values):' '    return sum(values) / len(values)' > "$repo/calc.py"
  cp "$repo/calc.py" "$repo.expected"
  printf '%s\n' "$repo"
}

GROK_REVIEW_REPO=$(make_review_fixture grok)
CLAUDE_REVIEW_REPO=$(make_review_fixture claude)
CODEX_REVIEW_REPO=$(make_review_fixture codex)

make_review_prompt() {
  harness=$1
  token=$2
  prompt=$3
  {
    printf '%s\n' 'You are the callee in a delegated task. Do not delegate any part of this work to another agent CLI.'
    printf '%s\n' 'Review the uncommitted changes in this repository for concrete bugs. Do not edit anything.'
    printf '%s\n' 'Use only plain git status, git diff, git log, and git show forms; do not prefix them with git -C or git --no-pager.'
    printf '%s\n' 'Briefly identify the seeded failure mode and finish with this exact token:'
    printf '%s\n' "$token"
    printf '%s\n' "Harness label: $harness"
  } > "$prompt"
}

GROK_REVIEW_PROMPT="$CANARY_ROOT/grok-review.prompt"
CLAUDE_REVIEW_PROMPT="$CANARY_ROOT/claude-review.prompt"
CODEX_REVIEW_PROMPT="$CANARY_ROOT/codex-review.prompt"
make_review_prompt grok REVIEW_CANARY_OK_GROK "$GROK_REVIEW_PROMPT"
make_review_prompt claude REVIEW_CANARY_OK_CLAUDE "$CLAUDE_REVIEW_PROMPT"
make_review_prompt codex REVIEW_CANARY_OK_CODEX "$CODEX_REVIEW_PROMPT"

printf 'Starting review matrix (Grok, Claude, Codex; timeout %ss per cell)\n' "$CELL_TIMEOUT_SECONDS"
(
  run_with_timeout env XDELEGATE_DEPTH=1 grok --no-auto-update --no-subagents --cwd "$GROK_REVIEW_REPO" -m grok-4.5 --output-format json \
    --always-approve --sandbox read-only \
    --deny "Edit($GROK_REVIEW_REPO/**)" --deny "Write($GROK_REVIEW_REPO/**)" \
    --prompt-file "$GROK_REVIEW_PROMPT" > "$CANARY_ROOT/grok-review.json" 2> "$CANARY_ROOT/grok-review.stderr"
) &
GROK_REVIEW_PID=$!
(
  cd "$CLAUDE_REVIEW_REPO" || exit 1
  run_with_timeout env XDELEGATE_DEPTH=1 claude -p --no-session-persistence --model fable \
    --safe-mode --strict-mcp-config --permission-mode manual \
    --disallowed-tools Edit Write NotebookEdit Task \
    --allowed-tools Read Grep Glob 'Bash(git status:*)' 'Bash(git diff:*)' 'Bash(git log:*)' 'Bash(git show:*)' \
    < "$CLAUDE_REVIEW_PROMPT" > "$CANARY_ROOT/claude-review.txt" 2> "$CANARY_ROOT/claude-review.stderr"
) &
CLAUDE_REVIEW_PID=$!
(
  run_with_timeout env XDELEGATE_DEPTH=1 codex -C "$CODEX_REVIEW_REPO" exec -s read-only -m gpt-5.6-sol review - \
    < "$CODEX_REVIEW_PROMPT" > "$CANARY_ROOT/codex-review.txt" 2> "$CANARY_ROOT/codex-review.stderr"
) &
CODEX_REVIEW_PID=$!
ACTIVE_PIDS="$GROK_REVIEW_PID $CLAUDE_REVIEW_PID $CODEX_REVIEW_PID"

if wait "$GROK_REVIEW_PID"; then GROK_REVIEW_STATUS=0; else GROK_REVIEW_STATUS=$?; fi
if wait "$CLAUDE_REVIEW_PID"; then CLAUDE_REVIEW_STATUS=0; else CLAUDE_REVIEW_STATUS=$?; fi
if wait "$CODEX_REVIEW_PID"; then CODEX_REVIEW_STATUS=0; else CODEX_REVIEW_STATUS=$?; fi
ACTIVE_PIDS=''

if [ "$GROK_REVIEW_STATUS" -eq 0 ]; then validate_review grok "$CANARY_ROOT/grok-review.json" "$GROK_REVIEW_REPO" json REVIEW_CANARY_OK_GROK || FAILURES=$((FAILURES + 1)); else record review grok "FAIL exit $GROK_REVIEW_STATUS"; FAILURES=$((FAILURES + 1)); fi
if [ "$CLAUDE_REVIEW_STATUS" -eq 0 ]; then validate_review claude "$CANARY_ROOT/claude-review.txt" "$CLAUDE_REVIEW_REPO" text REVIEW_CANARY_OK_CLAUDE || FAILURES=$((FAILURES + 1)); else record review claude "FAIL exit $CLAUDE_REVIEW_STATUS"; FAILURES=$((FAILURES + 1)); fi
if [ "$CODEX_REVIEW_STATUS" -eq 0 ]; then validate_review codex "$CANARY_ROOT/codex-review.txt" "$CODEX_REVIEW_REPO" text REVIEW_CANARY_OK_CODEX || FAILURES=$((FAILURES + 1)); else record review codex "FAIL exit $CODEX_REVIEW_STATUS"; FAILURES=$((FAILURES + 1)); fi

make_implementation_fixture() {
  harness=$1
  repo="$CANARY_ROOT/implementation-$harness"
  init_repo "$repo"
  printf '%s\n' BEFORE > "$repo/marker.txt"
  printf '%s\n' '.acceptance-ran' > "$repo/.gitignore"
  expected="AFTER_$(printf '%s' "$harness" | tr '[:lower:]' '[:upper:]')"
  {
    printf '%s\n' '#!/bin/sh' 'set -eu'
    printf '%s\n' "grep -qx '$expected' marker.txt"
    printf '%s\n' ': > .acceptance-ran'
  } > "$repo/verify.sh"
  chmod +x "$repo/verify.sh"
  git -C "$repo" add marker.txt .gitignore verify.sh
  git -C "$repo" commit -qm seed
  printf '%s\n' "$repo"
}

make_implementation_prompt() {
  expected=$1
  prompt=$2
  {
    printf '%s\n' 'You are the callee in a delegated task. Do not delegate any part of this work to another agent CLI.'
    printf '%s\n' "Replace the only line in marker.txt with $expected."
    printf '%s\n' 'Run ./verify.sh as the acceptance check.'
    printf '%s\n' 'Do not commit. Leave the intended change uncommitted for the caller to review. Do not change any other file.'
  } > "$prompt"
}

GROK_IMPL_REPO=$(make_implementation_fixture grok)
CLAUDE_IMPL_REPO=$(make_implementation_fixture claude)
CODEX_IMPL_REPO=$(make_implementation_fixture codex)
make_implementation_prompt AFTER_GROK "$CANARY_ROOT/grok-implementation.prompt"
make_implementation_prompt AFTER_CLAUDE "$CANARY_ROOT/claude-implementation.prompt"
make_implementation_prompt AFTER_CODEX "$CANARY_ROOT/codex-implementation.prompt"

printf 'Starting implementation matrix (isolated repo per harness)\n'
(
  run_with_timeout env XDELEGATE_DEPTH=1 grok --no-auto-update --no-subagents --cwd "$GROK_IMPL_REPO" -m grok-4.5 --output-format json \
    --always-approve --deny 'Bash(claude:*)' --deny 'Bash(codex:*)' \
    --prompt-file "$CANARY_ROOT/grok-implementation.prompt" > "$CANARY_ROOT/grok-implementation.json" 2> "$CANARY_ROOT/grok-implementation.stderr"
) &
GROK_IMPL_PID=$!
(
  cd "$CLAUDE_IMPL_REPO" || exit 1
  run_with_timeout env XDELEGATE_DEPTH=1 claude -p --no-session-persistence --model fable \
    --safe-mode --strict-mcp-config --permission-mode acceptEdits \
    --disallowed-tools 'Bash(claude:*)' 'Bash(grok:*)' 'Bash(codex:*)' \
    --allowed-tools 'Bash(./verify.sh:*)' \
    < "$CANARY_ROOT/claude-implementation.prompt" > "$CANARY_ROOT/claude-implementation.txt" 2> "$CANARY_ROOT/claude-implementation.stderr"
) &
CLAUDE_IMPL_PID=$!
(
  run_with_timeout env XDELEGATE_DEPTH=1 codex -C "$CODEX_IMPL_REPO" exec -s workspace-write -m gpt-5.6-sol - \
    < "$CANARY_ROOT/codex-implementation.prompt" > "$CANARY_ROOT/codex-implementation.txt" 2> "$CANARY_ROOT/codex-implementation.stderr"
) &
CODEX_IMPL_PID=$!
ACTIVE_PIDS="$GROK_IMPL_PID $CLAUDE_IMPL_PID $CODEX_IMPL_PID"

if wait "$GROK_IMPL_PID"; then GROK_IMPL_STATUS=0; else GROK_IMPL_STATUS=$?; fi
if wait "$CLAUDE_IMPL_PID"; then CLAUDE_IMPL_STATUS=0; else CLAUDE_IMPL_STATUS=$?; fi
if wait "$CODEX_IMPL_PID"; then CODEX_IMPL_STATUS=0; else CODEX_IMPL_STATUS=$?; fi
ACTIVE_PIDS=''

if [ "$GROK_IMPL_STATUS" -eq 0 ]; then validate_implementation grok "$CANARY_ROOT/grok-implementation.json" "$GROK_IMPL_REPO" json AFTER_GROK || FAILURES=$((FAILURES + 1)); else record implementation grok "FAIL exit $GROK_IMPL_STATUS"; FAILURES=$((FAILURES + 1)); fi
if [ "$CLAUDE_IMPL_STATUS" -eq 0 ]; then validate_implementation claude "$CANARY_ROOT/claude-implementation.txt" "$CLAUDE_IMPL_REPO" text AFTER_CLAUDE || FAILURES=$((FAILURES + 1)); else record implementation claude "FAIL exit $CLAUDE_IMPL_STATUS"; FAILURES=$((FAILURES + 1)); fi
if [ "$CODEX_IMPL_STATUS" -eq 0 ]; then validate_implementation codex "$CANARY_ROOT/codex-implementation.txt" "$CODEX_IMPL_REPO" text AFTER_CODEX || FAILURES=$((FAILURES + 1)); else record implementation codex "FAIL exit $CODEX_IMPL_STATUS"; FAILURES=$((FAILURES + 1)); fi

printf '\noperation\tharness\tresult\n'
cat "$RESULTS"

if [ "$FAILURES" -ne 0 ]; then
  KEEP_CANARY_ARTIFACTS=1
  printf '%s matrix cell(s) failed.\n' "$FAILURES" >&2
  exit 1
fi

printf 'All six matrix cells passed.\n'
