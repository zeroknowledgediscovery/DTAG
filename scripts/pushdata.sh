#!/bin/bash

DATA_DIR=$1

for f in survey/data/"$DATA_DIR"/*.csv; do
  scripts/magics_artifacts.sh add \
    --local "$f" \
    --kind data \
    --gcs-prefix datasets/survey/files/gss \
    --commit
done



#scripts/magics_artifacts.sh add \
#  --local survey/data/$1 \
#  --kind data \
#  --gcs-prefix datasets/survey/files/$1 \
#  --commit --push
