"""Requirement extraction: reading asks out of prose, with rules and with a schema.

Two readers, one vocabulary. The deterministic reader is tested against saved
fixtures and against descriptions written inline to isolate one rule at a time;
the schema is tested for what it refuses, because a schema that accepts
anything is not a schema.

Nothing here reaches a model or a network: the AI path is covered by the shape
it demands of a response, not by the response.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from core.enums import ExtractionMethod, RequirementPriority
from jobs.extraction_schema import ExtractedRequirement, RequirementExtraction
from jobs.models import Requirement, RequirementKind
from jobs.normalizer import normalize_text
from jobs.requirements import extract_requirements, merge_requirements
from pydantic import ValidationError

FIXTURES = Path(__file__).resolve().parent / "fixtures"
HTML_FIXTURES = FIXTURES / "html"


def extract(description: str, *, raw: str | None = None) -> list[Requirement]:
    return extract_requirements(description, raw=raw)


def section(heading: str, *items: str) -> str:
    body = "".join(f"<li>{item}</li>" for item in items)
    return f"<h3>{heading}</h3><ul>{body}</ul>"


def priorities(requirements: list[Requirement]) -> dict[str, int]:
    return {
        priority.value: sum(
            1 for row in requirements if row.priority.value == priority.value
        )
        for priority in RequirementPriority
    }


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------
class TestSectionTone:
    @pytest.mark.parametrize(
        "heading",
        [
            "Required qualifications",
            "Requirements",
            "What we look for",
            "Must have",
            "Qualifications",
            "Minimum qualifications",
        ],
    )
    def test_a_requirements_heading_makes_its_items_required(self, heading: str) -> None:
        rows = extract(section(heading, "Python", "SQL"))
        assert [row.priority for row in rows] == [
            RequirementPriority.REQUIRED,
            RequirementPriority.REQUIRED,
        ]

    @pytest.mark.parametrize(
        "heading",
        ["Nice to have", "Bonus points", "Preferred qualifications", "Desirable"],
    )
    def test_a_nice_to_have_heading_marks_items_preferred(self, heading: str) -> None:
        rows = extract(section(heading, "Kubernetes"))
        assert [row.priority for row in rows] == [RequirementPriority.PREFERRED]

    @pytest.mark.parametrize(
        "heading",
        ["Responsibilities", "What you will do", "About us", "Benefits", "The role"],
    )
    def test_a_section_that_asks_for_nothing_contributes_nothing(
        self, heading: str
    ) -> None:
        rows = extract(section(heading, "Build the ingestion pipeline"))
        assert rows == []

    def test_a_description_with_only_responsibilities_has_no_requirements(self) -> None:
        description = (
            section("Responsibilities", "Write the code", "Review the code")
            + section("What you will do", "Ship the product")
        )
        assert extract(description) == []

    def test_an_unrecognised_heading_stops_inheriting_the_previous_tone(self) -> None:
        # The rule that keeps a "TECHNOLOGIES" list from being read as part of
        # the responsibilities section above it.
        description = (
            section("Responsibilities", "Run the pipelines")
            + section("TECHNOLOGIES", "Redis", "Kafka")
        )
        rows = extract(description)
        assert [row.text for row in rows] == ["Redis", "Kafka"]
        assert [row.priority for row in rows] == [
            RequirementPriority.UNKNOWN,
            RequirementPriority.UNKNOWN,
        ]

    def test_the_tone_of_a_later_section_wins(self) -> None:
        description = section("Requirements", "Python") + section(
            "Nice to have", "Rust"
        )
        rows = extract(description)
        assert [(row.text, row.priority) for row in rows] == [
            ("Python", RequirementPriority.REQUIRED),
            ("Rust", RequirementPriority.PREFERRED),
        ]


# ---------------------------------------------------------------------------
# What a line says for itself
# ---------------------------------------------------------------------------
class TestLinePriority:
    def test_a_line_that_says_a_plus_beats_a_required_section(self) -> None:
        rows = extract(section("Requirements", "Docker a plus"))
        assert rows[0].priority is RequirementPriority.PREFERRED
        assert rows[0].confidence == pytest.approx(0.9)

    def test_a_line_that_says_experience_is_not_required_is_not_required(self) -> None:
        rows = extract(section("Requirements", "No prior experience required"))
        assert rows[0].priority is RequirementPriority.UNKNOWN

    def test_a_line_that_says_welcome_is_preferred(self) -> None:
        rows = extract(
            section("Requirements", "Scala is welcome but not required")
        )
        assert rows[0].priority is RequirementPriority.PREFERRED

    def test_a_line_that_states_a_requirement_outside_a_section(self) -> None:
        rows = extract("<p>Python experience required for this role.</p>")
        assert [row.priority for row in rows] == [RequirementPriority.REQUIRED]

    def test_an_item_under_a_requirements_heading_needs_no_signal(self) -> None:
        # "Attention to detail" is neither phrased as a signal nor a sentence;
        # the section it sits under is what makes it an ask.
        rows = extract(section("Requirements", "Attention to detail"))
        assert len(rows) == 1

    def test_neutral_prose_without_a_signal_is_not_a_requirement(self) -> None:
        rows = extract("<p>We care deeply about our people and the places we work.</p>")
        assert rows == []

    def test_neutral_prose_with_a_signal_is_a_requirement(self) -> None:
        rows = extract(
            "<p>Candidates need experience with distributed systems.</p>"
        )
        assert len(rows) == 1
        assert rows[0].priority is RequirementPriority.UNKNOWN


# ---------------------------------------------------------------------------
# Years and categories
# ---------------------------------------------------------------------------
class TestYearsOfExperience:
    @pytest.mark.parametrize(
        ("line", "years"),
        [
            ("3+ years of professional Python development", 3.0),
            ("At least 5 years of experience with distributed systems", 5.0),
            ("Two years of experience", None),
            ("A decade of building things", None),
            ("Python", None),
        ],
    )
    def test_years_are_read_when_a_number_says_them(
        self, line: str, years: float | None
    ) -> None:
        rows = extract(section("Requirements", line))
        assert rows[0].min_years == years

    def test_a_line_that_is_only_about_years_is_categorised_as_such(self) -> None:
        rows = extract(section("Requirements", "5+ years of experience in a similar role"))
        assert rows[0].kind is RequirementKind.YEARS_OF_EXPERIENCE
        assert rows[0].min_years == 5.0

    def test_a_tech_line_keeps_its_category_and_still_carries_the_years(
        self,
    ) -> None:
        rows = extract(section("Requirements", "5+ years of Python development"))
        assert rows[0].kind is RequirementKind.PROGRAMMING_LANGUAGE
        assert rows[0].min_years == 5.0

    def test_years_are_clamped_to_a_plausible_range(self) -> None:
        rows = extract(section("Requirements", "97 years of experience"))
        assert rows[0].min_years is None


class TestCategories:
    @pytest.mark.parametrize(
        ("line", "kind"),
        [
            ("Python", RequirementKind.PROGRAMMING_LANGUAGE),
            ("TypeScript", RequirementKind.PROGRAMMING_LANGUAGE),
            ("AWS", RequirementKind.CLOUD),
            ("PostgreSQL", RequirementKind.DATABASE),
            ("Kubernetes", RequirementKind.TECHNOLOGY),
            ("Django", RequirementKind.FRAMEWORK),
            ("bachelor's degree in a related field", RequirementKind.EDUCATION),
            ("AWS certified solutions architect", RequirementKind.CERTIFICATION),
            ("Fluent in English", RequirementKind.LANGUAGE),
            ("machine learning", RequirementKind.DOMAIN),
            ("mentoring junior engineers", RequirementKind.SOFT_SKILL),
            ("sponsorship is available", RequirementKind.SPONSORSHIP),
            ("hybrid working", RequirementKind.WORKPLACE_TYPE),
        ],
    )
    def test_a_known_term_is_categorised(self, line: str, kind: RequirementKind) -> None:
        rows = extract(section("Requirements", line))
        assert rows[0].kind is kind, line

    def test_an_unfamiliar_line_falls_back_rather_than_guessing(self) -> None:
        rows = extract(section("Requirements", "The ability to explain things twice"))
        assert rows[0].kind in (RequirementKind.OTHER, RequirementKind.EXPERIENCE)


# ---------------------------------------------------------------------------
# Duplicates and disagreements
# ---------------------------------------------------------------------------
class TestDeduplication:
    def test_the_same_item_twice_is_stored_once(self) -> None:
        rows = extract(section("Requirements", "Python", "Python", "SQL"))
        assert [row.text for row in rows] == ["Python", "SQL"]

    def test_a_stack_list_and_a_requirement_agree_on_one_row(self) -> None:
        description = section("Requirements", "Python") + section(
            "TECHNOLOGIES", "Python", "pytest"
        )
        rows = extract(description)
        by_text = {row.text: row for row in rows}
        assert set(by_text) == {"Python", "pytest"}
        assert by_text["Python"].priority is RequirementPriority.REQUIRED

    def test_a_real_disagreement_is_kept_as_the_stricter_reading(self) -> None:
        description = section("Requirements", "Python") + section(
            "Nice to have", "Python"
        )
        rows = extract(description)
        assert len(rows) == 1
        assert rows[0].priority is RequirementPriority.REQUIRED
        assert rows[0].ambiguous is True

    def test_the_merged_row_keeps_the_most_specific_category(self) -> None:
        rows = merge_requirements(
            [
                Requirement(kind=RequirementKind.OTHER, text="Python"),
                Requirement(kind=RequirementKind.PROGRAMMING_LANGUAGE, text="Python"),
            ]
        )
        assert rows[0].kind is RequirementKind.PROGRAMMING_LANGUAGE

    def test_the_merged_row_keeps_the_largest_minimum_years(self) -> None:
        rows = merge_requirements(
            [
                Requirement(kind=RequirementKind.OTHER, text="3+ years required", min_years=3),
                Requirement(kind=RequirementKind.OTHER, text="3+ years required", min_years=5),
            ]
        )
        assert rows[0].min_years == 5.0

    def test_merging_preserves_document_order(self) -> None:
        rows = merge_requirements(
            [
                Requirement(kind=RequirementKind.OTHER, text="one"),
                Requirement(kind=RequirementKind.OTHER, text="two"),
                Requirement(kind=RequirementKind.OTHER, text="one"),
            ]
        )
        assert [row.text for row in rows] == ["one", "two"]

    def test_an_unknown_priority_never_survives_a_known_one(self) -> None:
        rows = merge_requirements(
            [
                Requirement(kind=RequirementKind.OTHER, text="Python"),
                Requirement(
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                    text="Python",
                    priority=RequirementPriority.PREFERRED,
                ),
            ]
        )
        assert rows[0].priority is RequirementPriority.PREFERRED
        assert rows[0].ambiguous is False


# ---------------------------------------------------------------------------
# What is kept about each row
# ---------------------------------------------------------------------------
class TestProvenance:
    def test_every_row_says_where_it_came_from(self) -> None:
        for row in extract(section("Requirements", "Python", "SQL")):
            assert row.extraction_source is ExtractionMethod.DETERMINISTIC
            assert row.source_excerpt == row.text
            assert row.normalized == normalize_text(row.text).lower()
            assert 0.0 < row.confidence <= 1.0

    def test_the_excerpt_can_be_found_in_the_description(self) -> None:
        description = (
            "<h3>Requirements</h3><ul><li>Experience with PyTorch</li></ul>"
        )
        rows = extract(description)
        assert rows[0].source_excerpt == "Experience with PyTorch"
        assert "Experience with PyTorch" in description

    def test_a_stated_priority_is_confident_and_an_inferred_one_is_not(self) -> None:
        rows = extract(section("Requirements", "Python"))
        assert rows[0].confidence == pytest.approx(0.9)
        rows = extract(section("Stack", "Python"))
        assert rows[0].confidence == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# Unhelpful input
# ---------------------------------------------------------------------------
class TestUnhelpfulInput:
    @pytest.mark.parametrize("description", ["", "   ", "x", "<p>short</p>"])
    def test_nothing_to_read_is_nothing_read(self, description: str) -> None:
        assert extract(description) == []

    def test_unclosed_markup_does_not_raise(self) -> None:
        rows = extract("<h3>Requirements<ul><li>Python<li>SQL")
        assert {row.text for row in rows} == {"Python", "SQL"}

    def test_a_line_of_prose_without_structure_is_read_sentence_by_sentence(
        self,
    ) -> None:
        text = (
            "We are hiring a machine learning engineer. "
            "You need experience with PyTorch. "
            "Apply through the careers page."
        )
        rows = extract(text)
        texts = [row.text for row in rows]
        assert "You need experience with PyTorch." in texts
        assert not any("careers page" in text for text in texts)

    def test_metadata_and_rules_are_not_content(self) -> None:
        description = (
            "================================================\n"
            "Company: Northwind Analytics\n"
            "Location: Remote\n"
            "------------------------------------------------\n"
            "\n"
            "Requirements: Python\n"
        )
        rows = extract(description)
        assert rows == [] or all("Northwind" not in row.text for row in rows)


# ---------------------------------------------------------------------------
# The saved fixtures
# ---------------------------------------------------------------------------
class TestSavedJobDescription:
    @pytest.fixture(scope="class")
    def requirements(self) -> list[Requirement]:
        text = (FIXTURES / "synthetic_job_description.txt").read_text(encoding="utf-8")
        return extract(text)

    def test_the_sections_read_as_the_headings_say(self, requirements) -> None:
        counts = priorities(requirements)
        assert counts["REQUIRED"] >= 6
        assert counts["PREFERRED"] >= 4

    def test_responsibilities_are_not_requirements(self, requirements) -> None:
        for row in requirements:
            assert "ingestion pipelines" not in row.text
            assert "labelled question sets" not in row.text

    def test_the_stack_is_read_as_a_list_of_terms(self, requirements) -> None:
        texts = {row.text for row in requirements}
        assert {"Python", "Pydantic", "SQLite", "pytest"} <= texts

    def test_years_and_categories_survive_the_round_trip(self, requirements) -> None:
        first = requirements[0]
        assert first.min_years == 3.0
        assert first.kind is RequirementKind.PROGRAMMING_LANGUAGE
        assert first.priority is RequirementPriority.REQUIRED


class TestCapturedPosting:
    def test_requirements_read_from_a_captured_posting(self) -> None:
        from jobs.acquisition import parse_job_page

        html = (HTML_FIXTURES / "job_detail.html").read_text(encoding="utf-8")
        page = parse_job_page(
            html, source="linkedin", page_url="https://www.linkedin.com/jobs/view/1"
        )
        rows = extract(page.description_text, raw=page.description_raw)

        required = [row for row in rows if row.priority is RequirementPriority.REQUIRED]
        assert len(required) == 4
        years = [row for row in rows if row.min_years is not None]
        assert years and years[0].min_years == 5.0
        assert any(row.kind is RequirementKind.CLOUD for row in rows)

    def test_a_capture_without_structure_still_reads_its_sections(self) -> None:
        from jobs.acquisition import parse_job_page

        html = (HTML_FIXTURES / "job_detail_element.html").read_text(encoding="utf-8")
        page = parse_job_page(
            html, source="linkedin", page_url="https://www.linkedin.com/jobs/view/1"
        )
        rows = extract(page.description_text, raw=page.description_raw)
        assert any(row.priority is RequirementPriority.REQUIRED for row in rows)
        assert any(row.min_years == 3.0 for row in rows)


# ---------------------------------------------------------------------------
# Storing what was read
# ---------------------------------------------------------------------------
class TestRequirementsAreStorable:
    def test_a_captured_set_round_trips_through_the_database(self, db) -> None:
        from database.repositories.jobs import JobRepository
        from jobs.models import Job

        repo = JobRepository(db)
        job_id, _ = repo.save(
            Job(source="linkedin", company="Acme", title="Engineer")
        )
        rows = extract(
            section("Requirements", "Python", "3+ years of experience")
            + section("Nice to have", "Kafka")
        )

        written = repo.replace_requirements(job_id, rows)
        stored = repo.requirements(job_id)

        assert written == len(rows) == 3
        assert [(row.text, row.priority) for row in stored] == [
            (row.text, row.priority) for row in rows
        ]
        assert stored[1].min_years == 3.0
        assert all(
            row.extraction_source is ExtractionMethod.DETERMINISTIC for row in stored
        )


# ---------------------------------------------------------------------------
# The model's schema
# ---------------------------------------------------------------------------
class TestExtractionSchema:
    def test_a_well_formed_response_is_accepted(self) -> None:
        payload = RequirementExtraction(
            requirements=[
                ExtractedRequirement(
                    text="Python",
                    category=RequirementKind.PROGRAMMING_LANGUAGE,
                    priority=RequirementPriority.REQUIRED,
                    min_years=3.0,
                    evidence="3+ years of Python",
                    confidence=0.85,
                ),
                ExtractedRequirement(
                    text="Kafka",
                    category=RequirementKind.TECHNOLOGY,
                    priority=RequirementPriority.PREFERRED,
                ),
            ]
        )
        rows = payload.to_requirements()
        assert [row.text for row in rows] == ["Python", "Kafka"]

    def test_converted_rows_are_attributed_to_a_model(self) -> None:
        row = RequirementExtraction(
            requirements=[
                ExtractedRequirement(text="Python", category="PROGRAMMING_LANGUAGE")
            ]
        ).to_requirements()[0]
        assert row.extraction_source is ExtractionMethod.AI
        assert row.analysis_source is not None
        assert row.normalized == normalize_text("Python").lower()
        assert row.source_excerpt is None

    def test_evidence_becomes_the_excerpt_it_quoted(self) -> None:
        row = RequirementExtraction(
            requirements=[
                ExtractedRequirement(
                    text="Python",
                    category="PROGRAMMING_LANGUAGE",
                    evidence="  experience with Python  ",
                )
            ]
        ).to_requirements()[0]
        assert row.source_excerpt == "experience with Python"

    def test_an_invented_category_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            ExtractedRequirement(text="Python", category="NINJA_SKILL")

    def test_a_blank_requirement_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            ExtractedRequirement(text="   ", category="SKILL")

    def test_a_confidence_outside_the_range_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            ExtractedRequirement(text="Python", category="SKILL", confidence=1.5)

    def test_years_outside_the_plausible_range_are_refused(self) -> None:
        with pytest.raises(ValidationError):
            ExtractedRequirement(text="Python", category="SKILL", min_years=120.0)

    def test_fields_a_reader_does_not_expect_are_refused(self) -> None:
        with pytest.raises(ValidationError):
            ExtractedRequirement.model_validate(
                {"text": "Python", "category": "SKILL", "importance": 11}
            )

    def test_a_response_with_no_requirements_is_still_a_response(self) -> None:
        assert RequirementExtraction().to_requirements() == []

    def test_duplicates_in_a_response_fold_like_the_rule_says(self) -> None:
        payload = RequirementExtraction(
            requirements=[
                ExtractedRequirement(
                    text="Python", category="PROGRAMMING_LANGUAGE", priority="REQUIRED"
                ),
                ExtractedRequirement(
                    text="python", category="TECHNOLOGY", priority="PREFERRED"
                ),
            ]
        )
        rows = payload.to_requirements()
        assert len(rows) == 1
        assert rows[0].priority is RequirementPriority.REQUIRED
        assert rows[0].ambiguous is True

    @pytest.mark.parametrize("kind", list(RequirementKind))
    def test_every_stored_category_is_a_category_the_schema_accepts(
        self, kind: RequirementKind
    ) -> None:
        row = ExtractedRequirement(text="thing", category=kind.value)
        assert row.category is kind

    @pytest.mark.parametrize("priority", list(RequirementPriority))
    def test_every_stored_priority_is_a_priority_the_schema_accepts(
        self, priority: RequirementPriority
    ) -> None:
        row = ExtractedRequirement(text="thing", category="SKILL", priority=priority.value)
        assert row.priority is priority

    def test_a_deterministic_row_could_be_reported_by_a_model(self) -> None:
        # The two paths must share a vocabulary, or one day they will be
        # stored side by side and read as different things.
        for row in extract(section("Requirements", "Python", "3+ years of experience")):
            mirrored = ExtractedRequirement(
                text=row.text,
                category=row.kind.value,
                priority=row.priority.value,
                min_years=row.min_years,
                confidence=row.confidence,
            )
            assert mirrored.category is row.kind
            assert mirrored.priority is row.priority
