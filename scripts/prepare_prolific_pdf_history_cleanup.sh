#!/usr/bin/env bash
# Prepare, but DO NOT PUSH, a sanitized replacement for the DTAG experiment
# branch. Removes two sensitive Prolific payment-summary PDFs from all commits
# reachable through this branch's history.
#
# Prerequisite: install git-filter-repo (e.g. pipx install git-filter-repo).
# Run from any directory:
#   bash scripts/prepare_prolific_pdf_history_cleanup.sh \
#     "$HOME/private/dtag-pdf-history-cleaned"
#
# This creates a NEW single-branch clone in an absent, private directory and
# rewrites ONLY that clone. It never force-pushes, deletes remote branches,
# modifies the original checkout, or deletes the source PDFs in protected storage.
# A repository administrator must explicitly review and perform the printed
# force-with-lease push afterward (coordinate with collaborators first).
set -euo pipefail
umask 077

repo='git@github.com:zeroknowledgediscovery/DTAG.git'
branch='experiment/prolific-human-study'
a='DEMOCRATIC_recruitment_right_push_prolific_summary_detailed_6ae37b8688d760488b8df1b0.pdf'
b='REPUBLICAN_RECRUIOT_right_push_prolific_summary_detailed_6ae3d74f4c7ff7370986b1e4.pdf'

if [[ $# -ne 1 ]]; then
  printf 'Usage: %s /absolute/private/new-empty-directory\n' "$0" >&2
  exit 2
fi
out="$1"
if [[ "$out" != /* ]]; then
  printf 'ERROR: output must be an absolute path outside the working tree\n' >&2
  exit 2
fi
if [[ -e "$out" ]]; then
  printf 'ERROR: destination exists; refusing to overwrite: %s\n' "$out" >&2
  exit 2
fi
command -v git >/dev/null || { printf 'git is required\n' >&2; exit 2; }
command -v git-filter-repo >/dev/null || {
  printf 'git-filter-repo is required (install with pipx or pip)\n' >&2
  exit 2
}
mkdir -p "$(dirname "$out")"
chmod 700 "$(dirname "$out")" 2>/dev/null || true

git clone --single-branch --no-tags --branch "$branch" "$repo" "$out"
old="$(git -C "$out" rev-parse HEAD)"
printf 'Fetched %s at %s\n' "$branch" "$old"

# This disposable clone has ONLY the experiment branch; no other branch or
# tag is rewritten and no remote is changed.
(
  cd "$out"
  git filter-repo --force \
    --path "$a" \
    --path "$b" \
    --invert-paths

  # git-filter-repo intentionally removes remotes; add back for manual review.
  if ! git remote get-url origin >/dev/null 2>&1; then
    git remote add origin "$repo"
  fi

  # Confirm neither sensitive PDF is reachable in this rewritten history.
  if git rev-list --objects HEAD | grep -F -e "$a" -e "$b" >/dev/null; then
    printf 'FAIL: a sensitive PDF remains reachable in rewritten history\n' >&2
    exit 1
  fi
)
new="$(git -C "$out" rev-parse HEAD)"
if [[ "$new" == "$old" ]]; then
  printf 'WARN: rewritten HEAD unchanged; inspect whether files were in history\n' >&2
fi
printf '\nPrepared clean clone: %s\n' "$out"
printf 'Before publishing: audit refs, coordinate with collaborators, and ensure\n'
printf 'other public branches/tags/PR refs/forks do not retain the files.\n'
printf '\nOnly after authorization, from the clean clone, push with an exact lease:\n'
printf '  git -C %q push --force-with-lease=%q origin %q\n' \
  "$out" "refs/heads/$branch:$old" "$branch"
printf '\nNote: GitHub caches, pull requests, forks, and other refs may retain old\n'
printf 'commits. Removing a commit from branch history does not prove erasure.\n'
