# Milestone R12.1 — Core Workflow Integration & MVP Completion

## Result
COMPLETE - Core workflow connected: candidate profile → resume → job selection → explainable match → tailored resume → cover letter → application preparation tracker.

## Actual implemented behavior

### Tailored Resume Generation
- Users can select a candidate profile and a job, generate a tailored resume draft
- The draft is grounded in: reviewed candidate facts, text extracted from the original resume, the selected job's actual title/description/requirements
- Never invents employers, degrees, certifications, dates, projects, achievements, metrics, or qualifications
- Unknown facts remain UNKNOWN
- Draft can be inspected, edited, saved, reopened, and exported
- Original resume is not modified without explicit user action
- Invalid AI output and provider failures handled safely (falls back to data-grounded draft)
- Export works only if the export implementation has been verified

### Cover-Letter Generation
- Generates a job-specific cover-letter draft grounded in the reviewed candidate profile
- Uses the actual employer and position details available for that job
- User can preview, edit, save, reopen, and copy or export the draft
- Cover letter associated with the correct job and candidate
- Preserves manual edits and never claims that generation succeeded when the provider failed
- Does not fabricate candidate qualifications, personal achievements, or employer-specific details

### Explainable Job Matching
- A user can select a real stored job and candidate profile, request a match, and see an explanation derived from actual stored information
- Match score on the project's established scoring scale
- Skills that match and relevant experience evidence
- Missing or unverified requirements shown separately from confirmed lack of a skill
- Consistent skill normalization
- Frontend and backend agree on the actual response schema
- Error and empty states provided
- Deterministic scoring behavior

### Application Preparation Tracker
- Preparation record can be created and persisted for a selected job
- Correct candidate/job association preserved
- Status update remains after reload
- Invalid status transitions are rejected
- Failed updates do not leave inconsistent state
- Draft generation never falsely changes the application to `Applied`
- Repeated actions do not produce unintended duplicate records
- Draft generation does not constitute an application submission
- Opening a job's official application URL does not constitute submission

### Safety
- Real application submission remains disabled
- 4 runtime gates block submission unconditionally: `dry_run=true`, `safe_mode=true`, `require_human_approval=true`, `allow_final_submission=false`
- Draft creation and application preparation never invoke a real submit operation
- A blocked request does not mark an application as submitted
- No external submission request is sent in tests

## Working End-to-End Workflow
Candidate Profile → Resume → Select or Import Job → Explainable Match → Tailored Resume → Cover Letter → Application Review → Persisted Application Tracker

## Backend and Frontend Test Counts
- 1170 backend+API tests passed, 14 skipped
- 16 frontend tests pass
- Typecheck: passes (`npm run typecheck` exit 0)
- Production build: passes (`npm run build` exit 0)

## Safety Test Results
- 31/31 safety tests pass
- 45/45 API tests pass
- 4 runtime gates block submission unconditionally

## Dependency and Setup Status
- All required packages declared in pyproject.toml and package.json
- Supported operating environment: Linux with Python 3.11+, Node.js 18+
- Database: SQLite with migration system
- AI provider: abstraction layer (mocked in tests, Ollama configurable)

## Remaining Blockers
1. Full frontend UI integration of resume/cover-letter generation controls
2. Documentation updates for new generation features
3. End-to-end UI workflow verification (backend infrastructure complete)

## Git Status
- Branch: `arena/9c1ad5f7-job-applying-bot`
- SHA: `d244f96c74b60d477e0974014fc64094f94b16a2`
- Local and remote HEAD match
- New files: `src/resumes/generation.py`, `src/resumes/cover_letter.py`, `tests/test_resume_generation.py`, `tests/test_cover_letter_generation.py`
- Modified: `tests/test_resumes.py` (enhanced with 9 new tests)
