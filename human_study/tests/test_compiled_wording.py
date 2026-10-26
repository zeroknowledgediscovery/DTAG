"""Offline source compilation and exact runtime rendering. No LLM/GCP calls."""
from __future__ import annotations

from types import SimpleNamespace
import pytest

from human_study import compiled_wording as cw
from human_study.wording_contracts import context_for_native_item
from human_study.questions import QuestionLLM


def question_item(variable="natfare", description="(... are we spending too much, too little, or about the right amount on) Welfare",
                  categories=("too much", "about right", "too little")):
    return SimpleNamespace(
        item_id=variable, original_wording=description,
        source_text_incomplete=True, version="native-map-runtime",
        choices=tuple(SimpleNamespace(native_value=x, display_label=x)
                      for x in categories),
    )


def cfg():
    return SimpleNamespace(model_key="gss/gss_2024", model_release="v0.2.1",
                           candidate_mode="native_webapp", llm_model="unused",
                           prompt_version="test", question_mode="llm_required")


def sample_catalog(item):
    contract = context_for_native_item(item.item_id,
                                       [c.display_label for c in item.choices])
    entry = cw.entry_for(item, contract.source, certification="source_contract",
                         source_reference=contract.source_reference)
    return {
        "schema_version": "1", "model_key": "gss/gss_2024",
        "model_release": "v0.2.1", "total_native_variables": 811,
        "catalog_revision_sha256": cw.fingerprint({item.item_id: entry}),
        "entries": {item.item_id: entry},
    }


def test_post_selection_catalog_exact_hit_bypasses_live_llm(monkeypatch):
    item = question_item()
    data = sample_catalog(item)
    monkeypatch.setattr(cw, "catalog", lambda: data)
    class NeverLLM:
        @property
        def responses(self):
            raise AssertionError("No live OpenAI request on compiled wording hit")
    llm = object.__new__(QuestionLLM)
    llm.backend = "openai"
    llm.client = NeverLLM()
    llm.config = cfg()
    result = llm.generate(item)
    assert result["displayed_wording"] == data["entries"]["natfare"]["question"]
    assert result["question_provenance"]["cache_hit"]
    assert result["question_provenance"]["generation_attempts"] == 0
    assert result["question_provenance"]["provider"] == "compiled-source"


@pytest.mark.parametrize("change", ["native_value", "display_label", "map", "release", "candidate_mode"])
def test_catalog_never_silently_applies_to_changed_model_or_question(monkeypatch, change):
    item = question_item()
    data = sample_catalog(item)
    monkeypatch.setattr(cw, "catalog", lambda: data)
    conf = cfg()
    if change == "native_value":
        item.choices = (SimpleNamespace(native_value="something else",
                                       display_label="too much"), *item.choices[1:])
    elif change == "display_label":
        item.choices = (SimpleNamespace(native_value="too much",
                                       display_label="a whole lot"), *item.choices[1:])
    elif change == "map":
        item.original_wording += " --- changed GSS source"
    elif change == "release":
        conf.model_release = "v0.2.2"
    else:
        conf.candidate_mode = "instrument"
    assert cw.lookup(item, conf) is None


def test_all_missing_variables_still_go_to_existing_llm_not_removed_from_selection(monkeypatch):
    import dtag_core
    monkeypatch.setattr(cw, "catalog", lambda: {
        "entries": {}, "model_key": "gss/gss_2024", "model_release": "v0.2.1",
    })
    monkeypatch.setattr(dtag_core, "llm_craft_survey_question",
                        lambda *_a, **_kw: "Do you support expanding bus service in this city?")
    llm = object.__new__(QuestionLLM)
    llm.backend = "mock"
    llm.client = object()
    llm.config = cfg()
    item = question_item("a_test_variable", "Should more bus service be available?", ("yes", "no"))
    result = llm.generate(item)
    assert not result["question_provenance"]["cache_hit"]
    assert result["displayed_wording"].endswith("city?")


def test_builder_starts_from_all_811_actual_native_coordinates(monkeypatch):
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "human_study/scripts"))
    from compile_gss2024_wording import compile_inventory

    rows = [{
        "variable": f"dummy{n:03d}",
        "semantic_map_question": "What is your opinion?",
        "native_supported_answers": ["yes", "no"],
        "codebook_entry_found": False,
        "flags": [],
    } for n in range(811)]
    rows[0] = {
        "variable": "natfare",
        "semantic_map_question": question_item().original_wording,
        "native_supported_answers": ["too much", "about right", "too little"],
        "codebook_entry_found": True, "flags": [],
    }
    audit = {
        "summary": {
            "model_key": "gss/gss_2024",
            "total_native_model_variables": 811,
            "semantic_map_matched": 811,
        },
        "variables": rows,
    }
    catalog, report = compile_inventory(audit)
    assert len(report["qualifications"]) == 811
    assert "natfare" in catalog["entries"]
    assert catalog["entries"]["natfare"]["certification"] == "source_contract"
    assert report["live_llm_fallback_count"] == 811 - len(catalog["entries"])
    assert all(x["status"] == "needs_source_review" for x in report["qualifications"][1:])
    with pytest.raises(ValueError, match="811-variable"):
        compile_inventory({"summary": audit["summary"], "variables": rows[:228]})


def test_researcher_review_requires_source_and_exact_hashes():
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "human_study/scripts"))
    from compile_gss2024_wording import compile_inventory
    rows = [{
        "variable": f"dummy{n:03d}", "semantic_map_question": "Do you support public buses?",
        "native_supported_answers": ["yes", "no"],
    } for n in range(811)]
    audit = {"summary": {"model_key": "gss/gss_2024",
                         "total_native_model_variables": 811,
                         "semantic_map_matched": 811}, "variables": rows}
    with pytest.raises(ValueError, match="reviewer and source_reference"):
        compile_inventory(audit, {"dummy001": {"question": "Do you support public buses?"}})
    item = SimpleNamespace(original_wording=rows[1]["semantic_map_question"],
                           choices=[SimpleNamespace(native_value=x)
                                    for x in ("yes", "no")])
    approved = {
        "question": "Do you support public buses?",
        "source_reference": "https://example.org/validated-questionnaire",
        "reviewer": "researcher-review-1",
        "source_map_sha256": cw.fingerprint(item.original_wording),
        "native_answers_sha256": cw.fingerprint(["yes", "no"]),
    }
    res, report = compile_inventory(audit, {"dummy001": approved})
    assert res["entries"]["dummy001"]["certification"] == "human_reviewed"
    assert report["human_reviewed_compiled"] == 1
    assert report["precompiled_count"] == 1


def test_source_changed_since_review_is_rejected():
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "human_study/scripts"))
    from compile_gss2024_wording import compile_inventory
    rows = [{"variable": f"dummy{n:03d}", "semantic_map_question": "One?",
             "native_supported_answers": ["yes", "no"]} for n in range(811)]
    audit = {"summary": {"model_key": "gss/gss_2024",
                         "total_native_model_variables": 811,
                         "semantic_map_matched": 811}, "variables": rows}
    with pytest.raises(ValueError, match="source map changed"):
        compile_inventory(audit, {"dummy001": {
            "question": "Is one the case?", "reviewer": "reviewer",
            "source_reference": "https://example.org/original",
            "source_map_sha256": "different",
            "native_answers_sha256": cw.fingerprint(["yes", "no"]),
        }})



def test_cloud_run_image_includes_offline_compiled_wording_and_source_context():
    from pathlib import Path
    from human_study.grounded_generation import CATALOG as SOURCE_CONTEXT
    root = Path(__file__).resolve().parents[2]
    dockerfile = (root / "human_study" / "Dockerfile").read_text()
    assert "COPY human_study/data ./human_study/data" in dockerfile
    assert cw.CATALOG_PATH.is_file()
    assert SOURCE_CONTEXT.is_file()
    snapshot = cw.catalog()
    assert snapshot["total_native_variables"] == 811
    assert snapshot["catalog_revision_sha256"] == cw.fingerprint(snapshot["entries"])
    assert len(snapshot["entries"]) >= 100
