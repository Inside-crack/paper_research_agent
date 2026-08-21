import asyncio
import json
import sys
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parents[1] / "src"))

from paper_agent.common.models.paper_artifact import PaperArtifact, PaperSection
from paper_agent.common.persistence import StatePersistence
from paper_agent.tools.paper_processing.paper_glossary import PaperGlossaryTool


def _make_artifact(tmp_path, parsed=True):
    persistence = StatePersistence(tmp_path / "artifacts")
    task_id = "task-p12"
    task_dir = persistence.base_dir / task_id
    artifact_dir = task_dir / "papers"
    artifact_dir.mkdir(parents=True)
    artifact = PaperArtifact(
        id="artifact-p12",
        research_spec_id=task_id,
        candidate_id="paper-v1",
        arxiv_id="1706.03762v1",
        title="Test Paper",
        pdf_path="papers/paper-v1.pdf",
        full_text_original=(
            "Chain-of-thought reasoning improves tool use. "
            "The transformer architecture is evaluated."
            if parsed
            else ""
        ),
        sections=[
            PaperSection(
                section_id="section_1",
                title="Introduction",
                level=1,
                original_text="Chain-of-thought reasoning improves tool use.",
            )
        ]
        if parsed
        else [],
    )
    artifact_path = artifact_dir / "paper-v1.json"
    artifact_path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
    return persistence, task_id, "papers/paper-v1.json"


def _valid_terms():
    return [
        {
            "source_term": "chain-of-thought",
            "target_term": "思维链",
            "context": "Chain-of-thought reasoning improves tool use.",
            "confidence": 0.95,
        },
        {
            "source_term": "transformer",
            "target_term": "Transformer",
            "context": "The transformer architecture is evaluated.",
            "confidence": 0.8,
        },
    ]


def test_valid_terms_are_persisted(tmp_path):
    persistence, task_id, artifact_path = _make_artifact(tmp_path)
    result = asyncio.run(
        PaperGlossaryTool(persistence=persistence)._execute(
            task_id=task_id, artifact_path=artifact_path, terms=_valid_terms()
        )
    )

    assert result.success is True
    assert result.data["term_count"] == 2
    artifact = json.loads((persistence.base_dir / task_id / artifact_path).read_text())
    assert [term["source_term"] for term in artifact["glossary"]] == [
        "chain-of-thought",
        "transformer",
    ]


def test_duplicate_terms_keep_highest_confidence(tmp_path):
    persistence, task_id, artifact_path = _make_artifact(tmp_path)
    terms = [
        {"source_term": "Transformer", "target_term": "变换器", "confidence": 0.4},
        {"source_term": " transformer ", "target_term": "Transformer", "confidence": 0.9},
    ]

    result = asyncio.run(
        PaperGlossaryTool(persistence=persistence)._execute(
            task_id=task_id, artifact_path=artifact_path, terms=terms
        )
    )

    assert result.success is True
    assert result.data["term_count"] == 1
    assert result.data["terms"][0]["target_term"] == "Transformer"
    assert result.data["terms"][0]["confidence"] == 0.9


def test_empty_terms_persist_empty_glossary(tmp_path):
    persistence, task_id, artifact_path = _make_artifact(tmp_path)
    result = asyncio.run(
        PaperGlossaryTool(persistence=persistence)._execute(
            task_id=task_id, artifact_path=artifact_path, terms=[]
        )
    )

    assert result.success is True
    assert result.data["term_count"] == 0
    artifact = json.loads((persistence.base_dir / task_id / artifact_path).read_text())
    assert artifact["glossary"] == []


def test_unsupported_term_does_not_update_artifact(tmp_path):
    persistence, task_id, artifact_path = _make_artifact(tmp_path)
    original = (persistence.base_dir / task_id / artifact_path).read_text()
    result = asyncio.run(
        PaperGlossaryTool(persistence=persistence)._execute(
            task_id=task_id,
            artifact_path=artifact_path,
            terms=[{"source_term": "hallucinated concept", "target_term": "幻觉概念"}],
        )
    )

    assert result.success is False
    assert "hallucinated concept" in result.error
    assert (persistence.base_dir / task_id / artifact_path).read_text() == original


def test_invalid_term_fields_are_rejected(tmp_path):
    persistence, task_id, artifact_path = _make_artifact(tmp_path)
    invalid_terms = [
        {"source_term": "transformer", "target_term": "", "confidence": 0.8},
        {"source_term": "transformer", "target_term": "变换器", "confidence": 1.1},
    ]

    for term in invalid_terms:
        result = asyncio.run(
            PaperGlossaryTool(persistence=persistence)._execute(
                task_id=task_id, artifact_path=artifact_path, terms=[term]
            )
        )
        assert result.success is False


def test_unparsed_artifact_is_rejected(tmp_path):
    persistence, task_id, artifact_path = _make_artifact(tmp_path, parsed=False)
    result = asyncio.run(
        PaperGlossaryTool(persistence=persistence)._execute(
            task_id=task_id, artifact_path=artifact_path, terms=_valid_terms()
        )
    )

    assert result.success is False
    assert "P11" in result.error


def test_persistence_failure_is_returned(tmp_path):
    persistence, task_id, artifact_path = _make_artifact(tmp_path)
    persistence.update_paper_artifact = AsyncMock(side_effect=RuntimeError("manifest failed"))
    result = asyncio.run(
        PaperGlossaryTool(persistence=persistence)._execute(
            task_id=task_id, artifact_path=artifact_path, terms=_valid_terms()
        )
    )

    assert result.success is False
    assert "manifest failed" in result.error


def test_paper_glossary_is_registered():
    from paper_agent.tools import get_default_registry

    assert "paper_glossary" in get_default_registry().list_tools()


def main():
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))


if __name__ == "__main__":
    main()
