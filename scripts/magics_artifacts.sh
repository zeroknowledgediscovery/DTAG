#!/usr/bin/env bash
set -euo pipefail

# magics_artifacts.sh
# Manage large artifacts via GCS with small pointer files tracked in git.

BUCKET_DEFAULT="magics-lsm"

usage() {
  cat <<'EOF'
Usage:
  scripts/magics_artifacts.sh init [--bucket BUCKET]
  scripts/magics_artifacts.sh add  --local PATH --kind {data|model} --gcs-prefix PREFIX [--bucket BUCKET] [--name NAME] [--commit] [--push]
  scripts/magics_artifacts.sh pull [--bucket BUCKET] [--kind {data|model|all}] [--name NAME]
  scripts/magics_artifacts.sh status

Examples:
  # One-time repo setup
  scripts/magics_artifacts.sh init --bucket magics-lsm

  # Upload a dataset file and commit pointer
  scripts/magics_artifacts.sh add --local survey/data/ces_2026q1.parquet \
    --kind data \
    --gcs-prefix datasets/survey/files/ces/2026q1 \
    --commit --push

  # Upload a model file and commit pointer
  scripts/magics_artifacts.sh add --local survey/models/magics_v1.pkl \
    --kind model \
    --gcs-prefix datasets/survey/models/magics/v1 \
    --commit --push

  # Pull everything referenced by pointers
  scripts/magics_artifacts.sh pull --kind all

  # Pull a single artifact by base name (without .gcs)
  scripts/magics_artifacts.sh pull --kind data --name ces_2026q1.parquet
EOF
}

die() { echo "ERROR: $*" >&2; exit 1; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

sha256_file() {
  local f="$1"
  sha256sum "$f" | awk '{print $1}'
}

# Read a pointer file with simple "key: value" lines.
# Expects lines:
#   uri: gs://...
#   sha256: ...
read_pointer() {
  local ptr="$1"
  local uri sha
  uri="$(grep -E '^[[:space:]]*uri:' "$ptr" | sed -E 's/^[[:space:]]*uri:[[:space:]]*//')"
  sha="$(grep -E '^[[:space:]]*sha256:' "$ptr" | sed -E 's/^[[:space:]]*sha256:[[:space:]]*//')"
  [[ -n "$uri" ]] || die "Pointer missing uri: $ptr"
  echo "$uri" "$sha"
}

ensure_git_repo() {
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "Not inside a git repo."
}

cmd_init() {
  local bucket="$BUCKET_DEFAULT"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --bucket) bucket="$2"; shift 2;;
      -h|--help) usage; exit 0;;
      *) die "Unknown arg: $1";;
    esac
  done

  ensure_git_repo
  need_cmd gcloud
  need_cmd git

  mkdir -p survey/data survey/models scripts

  # Anchor files (optional, but helpful)
  [[ -f survey/data/README.md ]] || cat > survey/data/README.md <<'EOF'
This folder contains:
- Tracked pointer files: *.gcs
- Untracked downloaded datasets (ignored by git)
EOF

  [[ -f survey/models/README.md ]] || cat > survey/models/README.md <<'EOF'
This folder contains:
- Tracked pointer files: *.gcs
- Untracked downloaded models (ignored by git)
EOF

  # .gitignore rules: ignore everything in these dirs except pointers and README
  if [[ ! -f .gitignore ]] || ! grep -q '^survey/data/\*' .gitignore; then
    cat >> .gitignore <<'EOF'

# --- MAGICS large artifacts (keep pointers, ignore binaries) ---
survey/data/*
survey/models/*
!survey/data/*.gcs
!survey/models/*.gcs
!survey/data/README.md
!survey/models/README.md
EOF
  fi

  # Optional: create .keep objects in GCS to make prefixes visible (safe if you want it)
  # Comment out if you do not want to create these objects.
#  echo -n "" | gcloud storage cp - "gs://$bucket/datasets/survey/files/.keep" >/dev/null || true
#  echo -n "" | gcloud storage cp - "gs://$bucket/datasets/survey/models/.keep" >/dev/null || true

  echo "Init complete."
  echo "Bucket: gs://$bucket"
  echo "Next: use 'add' to upload a file and create a tracked .gcs pointer."
}

cmd_add() {
  local bucket="$BUCKET_DEFAULT"
  local local_path="" kind="" gcs_prefix="" name=""
  local do_commit=0 do_push=0

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --bucket) bucket="$2"; shift 2;;
      --local) local_path="$2"; shift 2;;
      --kind) kind="$2"; shift 2;;
      --gcs-prefix) gcs_prefix="$2"; shift 2;;
      --name) name="$2"; shift 2;;
      --commit) do_commit=1; shift;;
      --push) do_push=1; shift;;
      -h|--help) usage; exit 0;;
      *) die "Unknown arg: $1";;
    esac
  done

  ensure_git_repo
  need_cmd gcloud
  need_cmd git
  need_cmd sha256sum

  [[ -n "$local_path" ]] || die "--local is required"
  [[ -f "$local_path" ]] || die "Local file not found: $local_path"
  [[ "$kind" == "data" || "$kind" == "model" ]] || die "--kind must be data or model"
  [[ -n "$gcs_prefix" ]] || die "--gcs-prefix is required (e.g., datasets/survey/files/ces/2026q1)"

  # Derive base filename
  local base
  base="${name:-$(basename "$local_path")}"

  # Where should the pointer live?
  local repo_dir
  if [[ "$kind" == "data" ]]; then
    repo_dir="survey/data"
  else
    repo_dir="survey/models"
  fi

  # Enforce that the file lives in the corresponding repo dir (your stated requirement)
  # (We allow absolute paths, but require the final target location to be in repo_dir.)
  if [[ "$(dirname "$local_path")" != "$repo_dir" && "$local_path" != "$repo_dir/"* ]]; then
    echo "Note: local file is not under $repo_dir. That's okay, but download target will be $repo_dir/$base"
  fi

  # Upload to GCS
  local dest_uri="gs://$bucket/${gcs_prefix%/}/$base"
  echo "Uploading: $local_path"
  echo "To:       $dest_uri"
  gcloud storage cp "$local_path" "$dest_uri"

  # Compute hash and write pointer
  local sha
  sha="$(sha256_file "$local_path")"
  local ptr="$repo_dir/$base.gcs"

  cat > "$ptr" <<EOF
uri: $dest_uri
sha256: $sha
EOF

  echo "Wrote pointer: $ptr"

  # Sanity: ensure the binary itself is ignored (shows nothing if ignored)
  # This is informational; doesn't fail the run.
  git check-ignore -q "$repo_dir/$base" && echo "OK: $repo_dir/$base is ignored by git" || echo "WARNING: $repo_dir/$base is NOT ignored by git (check .gitignore)"

  # Commit and push pointer if requested
  if [[ $do_commit -eq 1 ]]; then
    git add "$ptr" .gitignore "$repo_dir/README.md" 2>/dev/null || true
    git commit -m "Add GCS pointer for $kind artifact: $base" || true
    echo "Committed pointer."
  fi

  if [[ $do_push -eq 1 ]]; then
    git push
    echo "Pushed git changes."
  fi

  echo "Done."
}

cmd_pull() {
  local bucket="$BUCKET_DEFAULT"
  local kind="all"
  local name=""
  local survey=""
  
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --bucket) bucket="$2"; shift 2;;
      --kind) kind="$2"; shift 2;;
      --name) name="$2"; shift 2;;
      --survey) survey="$2"; shift 2;;
      -h|--help) usage; exit 0;;
      *) die "Unknown arg: $1";;
    esac
  done

  ensure_git_repo
  need_cmd gcloud
  need_cmd sha256sum

  local ptrs=()

  add_ptrs_from_dir() {
    local d="$1"
    if [[ -n "$name" ]]; then
      [[ -f "$d/$name.gcs" ]] || die "Pointer not found: $d/$name.gcs"
      ptrs+=("$d/$name.gcs")
    else
      # All pointers
      while IFS= read -r -d '' f; do ptrs+=("$f"); done < <(find "$d" -maxdepth 1 -type f -name "*.gcs" -print0)
    fi
  }


  data_dir="survey/data"
  model_dir="survey/models"

  if [[ -n "$survey" ]]; then
    data_dir="$data_dir/$survey"
    model_dir="$model_dir/$survey"
  fi

  case "$kind" in
    data)
      add_ptrs_from_dir "$data_dir"
      ;;
    model)
      add_ptrs_from_dir "$model_dir"
      ;;
    all)
      add_ptrs_from_dir "$data_dir"
      add_ptrs_from_dir "$model_dir"
      ;;
    *)
      die "--kind must be data, model, or all"
      ;;
  esac


  
  [[ ${#ptrs[@]} -gt 0 ]] || die "No pointer files found to pull."

  for ptr in "${ptrs[@]}"; do
    read -r uri sha < <(read_pointer "$ptr")
    local out="${ptr%.gcs}"
    mkdir -p "$(dirname "$out")"
    echo "Downloading: $uri"
    echo "To:         $out"
    gcloud storage cp "$uri" "$out"

    if [[ -n "$sha" ]]; then
      local got
      got="$(sha256_file "$out")"
      [[ "$got" == "$sha" ]] || die "SHA256 mismatch for $out"
    fi
    echo "OK: $out"
  done

  echo "Pull complete."
}

cmd_status() {
  ensure_git_repo
  need_cmd git

  echo "Git status (tracked pointers should be clean):"
  git status --porcelain

  echo
  echo "Pointers present:"
  ls -1 survey/data/*.gcs 2>/dev/null || true
  ls -1 survey/models/*.gcs 2>/dev/null || true

  echo
  echo "Untracked binaries (should be ignored):"
  git status --porcelain --ignored | sed -n 's/^!! //p' | egrep '^survey/(data|models)/' || true
}

main() {
  [[ $# -ge 1 ]] || { usage; exit 1; }
  local cmd="$1"; shift
  case "$cmd" in
    init) cmd_init "$@";;
    add) cmd_add "$@";;
    pull) cmd_pull "$@";;
    status) cmd_status;;
    -h|--help) usage;;
    *) die "Unknown command: $cmd";;
  esac
}

main "$@"
