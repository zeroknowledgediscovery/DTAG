"""Investigator-only local export CLI using ADC and private GCS reads. No HTTP route."""
import argparse
import csv
import json
import re
from pathlib import Path

from .study_config import digest

FIELDS = {
    "participants": ["session_id", "policy", "receipt", "completed_at", "baseline_index", "final_index", "source_object"],
    "baseline": ["session_id", "question_id", "variable", "answer", "raw_text_response", "response_interpretation", "missing_reason", "timestamp", "source_object"],
    "questions": ["session_id", "question_id", "phase", "step", "variable", "original_wording", "displayed_wording", "choices", "presented_at", "source_object"],
    "answers": ["session_id", "question_id", "phase", "variable", "answer", "raw_text_response", "response_interpretation", "missing_reason", "response_elapsed_seconds", "timestamp", "source_object"],
    "trajectories": ["session_id", "question_id", "policy", "index_before", "index_after", "predicted_model_delta", "observed_conditional_index_delta", "conditional_distribution", "source_object"],
    "outcomes": ["session_id", "question_id", "variable", "answer", "raw_text_response", "response_interpretation", "missing_reason", "timestamp", "source_object"]}


def export_records(finals, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    tables = {k: [] for k in FIELDS}
    provenance = []
    for name, final in finals:
        if final["content_sha256"] != digest({k: v for k, v in final.items() if k != "content_sha256"}):
            raise ValueError("archive content hash mismatch")
        sid = final["session_id"]
        tables["participants"].append({"session_id": sid, "policy": final["policy"], "receipt": final["receipt"],
            "completed_at": final["timestamp"], "baseline_index": final["baseline_index"], "final_index": final["final_index"], "source_object": name})
        provenance.append({"session_id": sid, "config_hash": final["config_hash"], "provenance": final["provenance"], "source_object": name})
        for q in final["questions"]:
            # Individual answer objects are authoritative source references for each row.
            folder = {"baseline": "baseline", "intervention": "questions", "outcome": "outcomes"}[q["phase"]]
            source = name.rsplit("/", 1)[0] + f"/{folder}/{q['question_id']}.json"
            common = {"session_id": sid, "question_id": q["question_id"], "variable": q["target_variable"], "source_object": source}
            a = {**common, "phase": q["phase"], "answer": q["response_value"],
                 "raw_text_response": q.get("raw_text_response"),
                 "response_interpretation": json.dumps(q.get("response_interpretation"), ensure_ascii=False, sort_keys=True)
                     if q.get("response_interpretation") is not None else "",
                 "missing_reason": q.get("missing_reason"),
                 "response_elapsed_seconds": q["response_elapsed_seconds"], "timestamp": q["response_timestamp"]}
            tables["answers"].append(a)
            tables["questions"].append({**common, "phase": q["phase"], "step": q["step"],
                "original_wording": q["original_wording"], "displayed_wording": q["displayed_wording"],
                "choices": json.dumps(q["choices"], ensure_ascii=False), "presented_at": q["presented_at"]})
            if q["phase"] in ("baseline", "outcome"):
                tables["baseline" if q["phase"] == "baseline" else "outcomes"].append(a)
            if "index_result" in q:
                result = dict(q["index_result"])
                result["conditional_distribution"] = json.dumps(result["conditional_distribution"], sort_keys=True)
                tables["trajectories"].append({**common, "policy": final["policy"], **result})
    for key, rows in tables.items():
        with (out / f"{key}.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS[key], extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    (out / "provenance.json").write_text(json.dumps({"schema_version": "1", "participants": provenance}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--study", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,60}", args.study):
        parser.error("invalid study ID")
    from google.cloud import storage
    client = storage.Client()
    def finals():
        for blob in client.list_blobs(args.bucket, prefix=f"studies/{args.study}/sessions/"):
            if blob.name.endswith("/final.json"):
                yield f"gs://{args.bucket}/{blob.name}", json.loads(blob.download_as_bytes(if_generation_match=int(blob.generation)))
    export_records(finals(), args.out)


if __name__ == "__main__":
    main()
