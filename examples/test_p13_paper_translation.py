import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.common.models.paper_artifact import PaperArtifact, PaperSection, TermEntry
from paper_agent.common.persistence import StatePersistence
from paper_agent.tools.paper_processing.paper_translate import PaperTranslateTool


def _make_artifact(tmp_path, parsed=True):
    persistence = StatePersistence(tmp_path / "artifacts")
    task_id = "task-p13"
    artifact_dir = persistence.base_dir / task_id / "papers"
    artifact_dir.mkdir(parents=True)
    sections = [
        PaperSection(
            section_id="section_1",
            title="Introduction",
            level=1,
            original_text="Equation (1): x = 2. See [1]. Transformer models.",
            has_formulas=True,
            references=["1"],
        ),
        PaperSection(
            section_id="section_2",
            title="Results",
            level=1,
            original_text="The result is 95.5% on dataset [2].",
            references=["2"],
        ),
    ] if parsed else []
    artifact = PaperArtifact(
        id="artifact-p13",
        research_spec_id=task_id,
        candidate_id="paper-v1",
        arxiv_id="1706.03762v1",
        title="Test Paper",
        pdf_path="papers/paper-v1.pdf",
        sections=sections,
        full_text_original="\n\n".join(section.original_text for section in sections),
        glossary=[
            TermEntry(
                source_term="Transformer",
                target_term="Transformer模型",
                context="Transformer models.",
                confidence=0.9,
            )
        ] if parsed else [],
    )
    artifact_path = artifact_dir / "paper-v1.json"
    artifact_path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
    return persistence, task_id, "papers/paper-v1.json"


def _valid_translations():
    return [
        {
            "section_id": "section_1",
            "translated_text": "公式 (1)：x = 2。参见 [1]。Transformer模型。",
        },
        {
            "section_id": "section_2",
            "translated_text": "该结果在数据集 [2] 上达到 95.5%。",
        },
    ]


def test_all_sections_are_translated_and_persisted(tmp_path):
    persistence, task_id, artifact_path = _make_artifact(tmp_path)
    result = asyncio.run(
        PaperTranslateTool(persistence=persistence)._execute(
            task_id=task_id, artifact_path=artifact_path, translations=_valid_translations()
        )
    )

    assert result.success is True
    assert result.data["section_count"] == 2
    artifact = json.loads((persistence.base_dir / task_id / artifact_path).read_text())
    assert artifact["sections"][0]["translated_text"].startswith("公式")
    assert artifact["sections"][1]["translated_text"].endswith("。")
    assert "95.5%" in artifact["full_text_translated"]


def test_missing_or_duplicate_section_is_rejected(tmp_path):
    persistence, task_id, artifact_path = _make_artifact(tmp_path)
    for translations in (
        [_valid_translations()[0]],
        _valid_translations() + [_valid_translations()[0]],
    ):
        result = asyncio.run(
            PaperTranslateTool(persistence=persistence)._execute(
                task_id=task_id, artifact_path=artifact_path, translations=translations
            )
        )
        assert result.success is False
        assert "section" in result.error


def test_unknown_section_is_rejected(tmp_path):
    persistence, task_id, artifact_path = _make_artifact(tmp_path)
    translations = _valid_translations()
    translations[0]["section_id"] = "section_unknown"
    result = asyncio.run(
        PaperTranslateTool(persistence=persistence)._execute(
            task_id=task_id, artifact_path=artifact_path, translations=translations
        )
    )

    assert result.success is False
    assert "unknown" in result.error


def test_numeric_or_citation_token_change_is_rejected(tmp_path):
    persistence, task_id, artifact_path = _make_artifact(tmp_path)
    translations = _valid_translations()
    translations[0]["translated_text"] = "公式 (1)：x = 3。参见 [1]。Transformer模型。"
    result = asyncio.run(
        PaperTranslateTool(persistence=persistence)._execute(
            task_id=task_id, artifact_path=artifact_path, translations=translations
        )
    )
    assert result.success is False
    assert "section_1" in result.error

    translations = _valid_translations()
    translations[1]["translated_text"] = "该结果达到 95.5%。"
    result = asyncio.run(
        PaperTranslateTool(persistence=persistence)._execute(
            task_id=task_id, artifact_path=artifact_path, translations=translations
        )
    )
    assert result.success is False
    assert "[2]" in result.error


def test_formula_or_glossary_content_is_rejected_when_lost(tmp_path):
    persistence, task_id, artifact_path = _make_artifact(tmp_path)
    translations = _valid_translations()
    translations[0]["translated_text"] = "这是介绍。Transformer模型。"
    result = asyncio.run(
        PaperTranslateTool(persistence=persistence)._execute(
            task_id=task_id, artifact_path=artifact_path, translations=translations
        )
    )
    assert result.success is False
    assert "formula" in result.error.lower() or "公式" in result.error

    translations = _valid_translations()
    translations[0]["translated_text"] = "公式 (1)：x = 2。参见 [1]。这是模型。"
    result = asyncio.run(
        PaperTranslateTool(persistence=persistence)._execute(
            task_id=task_id, artifact_path=artifact_path, translations=translations
        )
    )
    assert result.success is False
    assert "glossary" in result.error or "Transformer" in result.error


def test_empty_translation_and_unparsed_artifact_are_rejected(tmp_path):
    persistence, task_id, artifact_path = _make_artifact(tmp_path)
    result = asyncio.run(
        PaperTranslateTool(persistence=persistence)._execute(
            task_id=task_id, artifact_path=artifact_path, translations=[]
        )
    )
    assert result.success is False

    persistence, task_id, artifact_path = _make_artifact(tmp_path / "unparsed", parsed=False)
    result = asyncio.run(
        PaperTranslateTool(persistence=persistence)._execute(
            task_id=task_id, artifact_path=artifact_path, translations=[]
        )
    )
    assert result.success is False
    assert "P11" in result.error


def test_persistence_failure_is_returned(tmp_path):
    persistence, task_id, artifact_path = _make_artifact(tmp_path)
    persistence.update_paper_artifact = AsyncMock(side_effect=RuntimeError("manifest failed"))
    result = asyncio.run(
        PaperTranslateTool(persistence=persistence)._execute(
            task_id=task_id, artifact_path=artifact_path, translations=_valid_translations()
        )
    )
    assert result.success is False
    assert "manifest failed" in result.error


def test_paper_translate_is_registered():
    from paper_agent.tools import get_default_registry

    assert "paper_translate" in get_default_registry().list_tools()


def main():
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))


if __name__ == "__main__":
    main()
