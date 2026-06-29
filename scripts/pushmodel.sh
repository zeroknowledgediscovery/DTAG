#!/bin/bash
MODELS_DIR=$1

for f in survey/models/"$MODELS_DIR"/*; do
  [ -f "$f" ] || continue
  scripts/magics_artifacts.sh add \
    --local "$f" \
    --kind model \
    --gcs-prefix datasets/survey/models/gss \
    --commit
done
git push

#scripts/magics_artifacts.sh add \
#  --local survey/models/$1 \
#  --kind model \
#  --gcs-prefix datasets/survey/models/$1 \
#  --commit --push
