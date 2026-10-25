#!/usr/bin/env python3
"""Read-only investigator diagnosis of V3 question-generation retries.

Prints only state/progress/failure categories; never participant text,
question wording, LLM content or identifiers that link to participants.
Requires Google Application Default Credentials and Firestore reader access.
"""
import argparse

from google.cloud import firestore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="pkcsaas-01")
    parser.add_argument("--database", default="dtag-human-pilot")
    parser.add_argument("--study", default="pilot-v3")
    args = parser.parse_args()

    client = firestore.Client(project=args.project, database=args.database)
    sessions = (client.collection("studies").document(args.study)
                .collection("sessions").order_by(
                    "updated_at", direction=firestore.Query.DESCENDING
                ).limit(1).stream())
    latest = next(sessions, None)
    if latest is None:
        print("No V3 sessions found")
        return
    session = latest.to_dict() or {}
    print("study:", args.study)
    print("phase:", session.get("phase"), "answers_saved:", session.get("next_step"))
    for doc in latest.reference.collection("questions").stream():
        question = doc.to_dict() or {}
        if question.get("status") == "generating":
            print("generation pending, phase:", question.get("phase"))
            print("variable:", question.get("target_variable"))
            print("generation failures:", question.get("generation_failure_count", 0))
            print("last error class:", question.get("last_generation_error", "unknown"))
            print("failure codes:", question.get("last_generation_failure_codes", []))
    print("This diagnostic is read-only; no saved answer or question was changed.")


if __name__ == "__main__":
    main()
