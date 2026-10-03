# Candidate profile: field reference

The profile has three files:

| File | Purpose | Tracked in git |
|---|---|---|
| `data/profile/candidate_profile.json` | Your real, working copy. **Ignored by git.** Every field starts `UNKNOWN`. | No |
| `data/profile/candidate_profile.example.json` | A copy with two fields filled in, to show the shape. | Yes |
| `data/profile/README.md` | This file. | Yes |

Open the JSON in any editor. It is plain JSON with one wrapper per value, so you
can read the whole thing and correct anything that looks wrong.

## The wrapper

Every field looks like this:

```json
"full_name": {
  "field_path": "identity.full_name",
  "value": null,
  "status": "UNKNOWN",
  "source": null,
  "source_id": null,
  "source_location": null,
  "confidence": 1.0,
  "verified_at": null,
  "evidence": []
}
```

| Key | Meaning |
|---|---|
| `value` | The actual data. `null` when unknown. |
| `status` | `UNKNOWN`, `INFERRED`, or `VERIFIED`. See below. |
| `source` | What kind of source this came from: `RESUME`, `PROFILE`, `USER_INPUT`, `JOB_DESCRIPTION`, `VERIFIED_ANSWER`, or `SYSTEM`. |
| `source_id` | Identifier of that source, such as a resume id or a session id. Never a file path. |
| `source_location` | Where inside the source, such as `experience.entries[0]` or `page 2`. |
| `confidence` | How strongly the evidence supports the value, `0.0` to `1.0`. |
| `verified_at` | When it was verified. |
| `evidence` | The supporting records, including the text excerpt. |

### The three statuses

| Status | Meaning | May be typed into a real form? |
|---|---|---|
| `UNKNOWN` | We do not know. The value is `null`. **This is the correct default and is not an error.** | No |
| `INFERRED` | Deterministic code proposed this, such as the resume parser reading it out. Not confirmed by you. | No |
| `VERIFIED` | You, or a source you have accepted, confirmed it. Must name its source. | Yes |

Three rules are enforced by the model, so editing the file cannot break them:

1. An `UNKNOWN` fact cannot carry a value.
2. A `VERIFIED` fact must name its source.
3. A `VERIFIED` fact must have at least one evidence record. "Verified" with
   nothing to show is not verified.

Setting a value by hand without touching `status` leaves the status as it was.
Use the CLI when you want the status checked for you:

```
python job_assistant.py profile set identity.full_name "Your Name"
python job_assistant.py profile validate
python job_assistant.py profile unknown
```

## The 44 fields

`REQUIRED` means a real application cannot proceed without it.

### identity
| Field | Required | Notes |
|---|---|---|
| `identity.full_name` | **yes** | As it should appear on a form. |
| `identity.preferred_name` | no | Only if different. |
| `identity.pronouns` | no | |
| `identity.date_of_birth` | no | Often deliberately left blank. |
| `identity.nationality` | no | |
| `identity.headline` | no | One line, such as "Machine Learning Engineer". |
| `identity.summary` | no | Short professional summary. |

### contact
| Field | Required | Notes |
|---|---|---|
| `contact.email` | **yes** | Format-checked. |
| `contact.phone` | **yes** | Include the country code. |
| `contact.linkedin_url` | no | Must be `http://` or `https://`. |
| `contact.website` | no | Portfolio or personal site. |

### location
| Field | Required | Notes |
|---|---|---|
| `location.current_city` | no | |
| `location.current_state` | no | |
| `location.current_country` | **yes** | |
| `location.postal_code` | no | |
| `location.willing_to_relocate` | no | Boolean. Must agree with `preferences.willing_to_relocate`. |
| `location.preferred_locations` | no | List. |
| `location.timezone` | no | For example `Asia/Kolkata`. |

### education
| Field | Required | Notes |
|---|---|---|
| `education.highest_level` | **yes** | For example `Bachelors`, `Masters`, `PhD`. |

`education.entries` is a list, one item per qualification. Each entry carries
its own verified fields:

```json
"entries": [
  {
    "institution": { "field_path": "education.entries[0].institution", "value": null, "status": "UNKNOWN", "...": "..." },
    "degree": { "...": "..." },
    "field_of_study": { "...": "..." },
    "start_date": { "...": "..." },
    "end_date": { "...": "..." },
    "is_current": { "...": "..." },
    "grade": { "...": "..." },
    "gpa": { "...": "..." },
    "location": { "...": "..." },
    "description": { "...": "..." }
  }
]
```

An empty `entries` list is fine. It means no education detail yet, not a
validation failure.

### experience
| Field | Required | Notes |
|---|---|---|
| `experience.total_years_experience` | **yes** | A number. |
| `experience.years_of_experience_verified` | no | Boolean, whether that total is confirmed. |

`experience.entries` is a list, one item per role. Each entry has
`employer`, `title`, `employment_type`, `location`, `start_date`, `end_date`,
`is_current`, `description`, `responsibilities`, `achievements`, and
`technologies`.

The validator reports, without changing anything:

- `end_date` before `start_date`,
- a role marked `is_current` that also has an `end_date`,
- two roles whose date ranges overlap,
- a duration that disagrees with `total_years_experience`,
- an implausible total.

### skills
| Field | Required | Notes |
|---|---|---|
| `skills.proficient` | no | List. |
| `skills.expert` | no | List. |
| `skills.familiar` | no | List. |
| `skills.languages` | no | Natural languages. |
| `skills.tools` | no | List. |

The same skill in two lists is reported as a duplicate. It is not merged
silently, because quietly dropping a value you typed is worse than telling you.

### projects
`projects.entries`, each with `name`, `description`, `role`, `technologies`,
`link`, `start_date`, `end_date`, and `metrics`.

### certifications
`certifications.entries`, each with `name`, `issuer`, `issue_date`,
`expiry_date`, `credential_id`, and `url`. An `expiry_date` already in the past
is reported.

### links
`links.entries`, each with `label`, `url`, and `kind`.

### preferences
| Field | Required | Notes |
|---|---|---|
| `preferences.desired_roles` | no | List. |
| `preferences.desired_locations` | no | List. |
| `preferences.remote_preference` | no | For example remote, hybrid, onsite. |
| `preferences.minimum_salary` | no | A number. |
| `preferences.maximum_salary` | no | A number. Reported if it is below the minimum. |
| `preferences.willing_to_relocate` | no | Boolean. Must agree with `location.willing_to_relocate`. |
| `preferences.notice_period` | no | |
| `preferences.willing_to_travel` | no | Boolean. |

### authorization
| Field | Required | Notes |
|---|---|---|
| `authorization.requires_sponsorship` | **yes** | Boolean. |
| `authorization.authorized_countries` | no | List. |
| `authorization.visa_status` | no | If sponsorship is not required, a visa status mentioning sponsorship is reported as a contradiction. |
| `authorization.sponsorship_available` | no | Boolean. |
| `authorization.security_clearance` | no | |

### availability
| Field | Required | Notes |
|---|---|---|
| `availability.available_from` | **yes** | A date such as `2026-04-01`. |
| `availability.notice_period_days` | no | A number. Negative is reported. |
| `availability.hours_per_week` | no | A number. |
| `availability.open_to_contract` | no | Boolean. |
| `availability.open_to_part_time` | no | Boolean. |

## Validation

```
python job_assistant.py profile validate
```

The report is read-only. It changes nothing on disk, so it is always safe to
run. Two severities:

- **Error**: the value cannot be used. A malformed email, an impossible date
  range, a contradiction, a required field that is not `VERIFIED`.
- **Warning**: worth a look, not necessarily wrong.

Every finding carries a code such as `UNKNOWN_VALUE_FOR_REQUIRED_FIELD` or
`IMPOSSIBLE_DATE_RANGE`, so problems can be tracked rather than re-read as prose.

### Completeness

`completeness` is the fraction of all 44 fields that could be typed into a real
form. An `INFERRED` field counts as incomplete on purpose, because a guessed
value is not progress. Completeness is not a quality score: a profile at 100%
can still be wrong, since a `VERIFIED` fact is only as good as the person who
confirmed it.

## What validation will not do

It will not guess. An empty profile reports 44 `UNKNOWN` fields and 0%
completeness, and that is a correct result, not a failure. Nothing in this
project invents a value, and nothing becomes `VERIFIED` without an explicit
source and evidence.
