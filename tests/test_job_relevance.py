"""Resume relevance: the pick comes from stored evidence, or no pick.

Every rule the decision rests on is here: coverage decides, ties go to a
human, zeros stay zeros, and nothing that is not already in the store
gets a vote.
"""

from __future__ import annotations

import pytest

from core.enums import ResumeRelevanceDecision, SectionType
from jobs.models import Job, Requirement, RequirementKind
from jobs.relevance import ResumeRelevance, recommend_resume
from resumes.models import Resume, ResumeSection


def a_job(**overrides: object) -> Job:
    return Job(**overrides)  # type: ignore[arg-type]


def a_row(
    text: str,
    *,
    kind: RequirementKind = RequirementKind.PROGRAMMING_LANGUAGE,
) -> Requirement:
    return Requirement(text=text, kind=kind)


def a_resume(
    resume_id: str,
    *,
    skills: tuple[str, ...] = (),
    raw_text: str = "",
    sections: tuple[ResumeSection, ...] = (),
) -> Resume:
    return Resume(
        id=resume_id,
        filename=f"{resume_id}.txt",
        file_hash=resume_id,
        skills=list(skills),
        raw_text=raw_text,
        sections=list(sections),
    )


ROWS = [a_row("Python"), a_row("SQL")]


@pytest.fixture()
def profiles(tmp_path, db):
    from candidate_profile.service import ProfileService

    service = ProfileService(db, storage_path=tmp_path / "candidate_profile.json")
    service.create_profile("primary", persist_json=True, actor="user")
    return service


class TestThePick:
    def test_the_resume_covering_more_is_recommended(self) -> None:
        full = a_resume("resume-full", skills=("Python", "SQL"))
        half = a_resume("resume-half", skills=("Python",))
        relevance = recommend_resume(a_job(title="Engineer"), ROWS, [half, full])

        assert relevance.decision is ResumeRelevanceDecision.RECOMMENDED
        assert relevance.recommended_resume_id == "resume-full"
        assert relevance.runner_up_resume_id == "resume-half"
        assert relevance.confidence == 1.0
        assert "2 of 2" in relevance.reason

    def test_a_tie_leaves_the_choice_to_a_human(self) -> None:
        one = a_resume("resume-one", skills=("Python",))
        two = a_resume("resume-two", skills=("SQL",))
        relevance = recommend_resume(a_job(), ROWS, [one, two])

        assert relevance.decision is ResumeRelevanceDecision.REVIEW_REQUIRED
        assert relevance.recommended_resume_id is None
        assert relevance.runner_up_resume_id == "resume-two"
        assert "tie" in relevance.reason

    def test_no_resumes_is_insufficient_evidence(self) -> None:
        relevance = recommend_resume(a_job(title="Engineer"), ROWS, [])
        assert relevance.decision is ResumeRelevanceDecision.INSUFFICIENT_EVIDENCE
        assert relevance.recommended_resume_id is None
        assert "no resumes" in relevance.reason

    def test_a_posting_with_no_measurable_skills_is_insufficient(self) -> None:
        # Compensation says terms, not skills: nothing a resume could cover.
        salary = [a_row("$150k", kind=RequirementKind.COMPENSATION)]
        resume = a_resume("resume-any", skills=("Python",))
        relevance = recommend_resume(a_job(), salary, [resume])

        assert relevance.decision is ResumeRelevanceDecision.INSUFFICIENT_EVIDENCE
        assert "states no skill" in relevance.reason
        assert relevance.scores == []

    def test_zero_coverage_is_reported_not_recommended(self) -> None:
        cobol = a_resume("resume-cobol", skills=("COBOL",))
        relevance = recommend_resume(a_job(), ROWS, [cobol])

        assert relevance.decision is ResumeRelevanceDecision.INSUFFICIENT_EVIDENCE
        assert relevance.recommended_resume_id is None
        assert relevance.scores[0].coverage == 0.0
        assert relevance.scores[0].missed == ["Python", "SQL"]

    def test_confidence_is_the_winners_coverage(self) -> None:
        partial = a_resume("resume-partial", skills=("Python",))
        relevance = recommend_resume(a_job(), ROWS, [partial])
        assert relevance.decision is ResumeRelevanceDecision.RECOMMENDED
        assert relevance.confidence == 0.5
        assert relevance.scores[0].covered == ["Python"]


class TestResumeEvidence:
    def test_declared_skills_are_read(self) -> None:
        resume = a_resume("resume-skills", skills=("Python", "SQL"))
        relevance = recommend_resume(a_job(), ROWS, [resume])
        assert relevance.scores[0].coverage == 1.0

    def test_the_skills_section_speaks_when_skills_are_empty(self) -> None:
        section = ResumeSection(
            section_type=SectionType.SKILLS,
            raw_text="Python, SQL, and Kubernetes",
        )
        resume = a_resume("resume-section", sections=(section,))
        relevance = recommend_resume(a_job(), ROWS, [resume])
        assert relevance.scores[0].coverage == 1.0

    def test_the_documents_own_text_is_the_last_resort(self) -> None:
        resume = a_resume("resume-text", raw_text="Built pipelines in Python and SQL")
        relevance = recommend_resume(a_job(), ROWS, [resume])
        assert relevance.scores[0].coverage == 1.0

    def test_numbers_and_generic_words_cover_nothing(self) -> None:
        rows = [
            a_row("3+ years of experience required", kind=RequirementKind.OTHER),
            a_row("Python"),
        ]
        any_resume = a_resume("resume-any", skills=("Python",))
        relevance = recommend_resume(a_job(), rows, [any_resume])
        # "years"/"experience" were words no resume owes the posting, so
        # the measurable set is Python alone - covered, at full marks.
        assert relevance.scores[0].coverage == 1.0
        assert relevance.scores[0].covered == ["Python"]

    def test_scores_are_ordered_best_first(self) -> None:
        weak = a_resume("resume-weak", skills=("Python",))
        strong = a_resume("resume-strong", skills=("Python", "SQL"))
        mid = a_resume("resume-mid", skills=("SQL",))
        relevance = recommend_resume(a_job(), ROWS, [weak, strong, mid])
        assert [score.resume_id for score in relevance.scores] == [
            "resume-strong",
            "resume-weak",
            "resume-mid",
        ]


class TestDeterminism:
    def test_two_calls_with_the_same_inputs_agree(self) -> None:
        resumes = [
            a_resume("resume-a", skills=("Python",)),
            a_resume("resume-b", skills=("Python", "SQL")),
        ]
        first = recommend_resume(a_job(title="Engineer"), ROWS, resumes)
        second = recommend_resume(a_job(title="Engineer"), ROWS, resumes)
        assert first.model_dump() == second.model_dump()

    def test_the_relevance_is_json_round_trippable(self) -> None:
        resume = a_resume("resume-one", skills=("Python",))
        relevance = recommend_resume(a_job(), ROWS, [resume])
        assert ResumeRelevance.model_validate(relevance.model_dump()) == relevance


class TestServiceWiring:
    def test_the_service_reads_resumes_from_its_provider(
        self, db, profiles
    ) -> None:
        from assistant.job_service import JobService

        resume = a_resume("resume-plugged", skills=("Python", "SQL"))
        service = JobService(
            db,
            profile_service=profiles,
            candidate_id="primary",
            resume_provider=lambda: [resume],
        )
        job = a_job(
            title="Engineer",
            description_text="<h3>Skills</h3><ul><li>Python</li><li>SQL</li></ul>",
        )
        job_id, _ = service.save(job)

        relevance = service.relevance(job_id)
        assert relevance.decision is ResumeRelevanceDecision.RECOMMENDED
        assert relevance.recommended_resume_id == "resume-plugged"
