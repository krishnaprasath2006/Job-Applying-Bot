import type { CandidateProfile, FactStatus, FactUpdate, FactValue } from '../types/api.js';

/**
 * A fact is any object carrying both a `field_path` and a `status`. Every leaf
 * of a profile section is one of these; structural keys such as `section_path`
 * and the `entries` lists are not.
 */
const isFact = (candidate: unknown): candidate is FactValue =>
  typeof candidate === 'object' &&
  candidate !== null &&
  'field_path' in candidate &&
  'status' in candidate;

/** Structural equality for the scalar and string-array values facts hold. */
const sameValue = (left: unknown, right: unknown): boolean => {
  if (left === right) return true;
  if (left === null || right === null || left === undefined || right === undefined) {
    return false;
  }
  if (Array.isArray(left) || Array.isArray(right)) {
    if (!Array.isArray(left) || !Array.isArray(right)) return false;
    return (
      left.length === right.length &&
      left.every((item, index) => item === right[index])
    );
  }
  return false;
};

/**
 * A value that carries no information. Blanking a text field or emptying a
 * skill list is a *clear*, not a claim of an empty string.
 *
 * `false` and `0` are deliberately not treated as blank: `false` is a real
 * answer to "requires visa sponsorship?" and collapsing it would silently
 * corrupt the fact.
 */
const isBlank = (value: unknown): boolean => {
  if (typeof value === 'string') return value.trim() === '';
  if (Array.isArray(value)) return value.length === 0;
  return false;
};

/** Read a fact's value without trusting the static type of the lookup. */
const factValue = (candidate: unknown): FactValue | undefined =>
  isFact(candidate) ? candidate : undefined;

/**
 * Translate one changed fact into the single-fact write the API accepts.
 *
 * A non-empty value is posted without a status: the server defaults a human
 * claim to INFERRED, which is the honest description of something typed into a
 * form. The UI deliberately never asserts VERIFIED, because VERIFIED requires a
 * cited source and this form has none to offer.
 *
 * A cleared value is posted as an explicit UNKNOWN with no value, because the
 * model forbids an UNKNOWN fact from carrying one.
 */
const toFactUpdate = (fact: FactValue, previous: FactValue | undefined): FactUpdate => {
  if (isBlank(fact.value)) {
    return { field_path: fact.field_path, value: null, status: 'UNKNOWN' as FactStatus };
  }
  const update: FactUpdate = { field_path: fact.field_path, value: fact.value };
  // Preserve a deliberate status the UI already holds (e.g. a skill the user
  // marked VERIFIED); otherwise let the server choose.
  if (previous && previous.status !== fact.status && fact.status !== 'UNKNOWN') {
    update.status = fact.status;
  }
  return update;
};

/**
 * Collect the facts whose value changed between two versions of a profile.
 *
 * The API writes one fact per request, so the caller needs the list of writes
 * rather than the whole profile. Sections are walked one level deep, which is
 * the shape of the schema: every section holds `FactValue` leaves directly.
 * Entry lists (experience, education, ...) are not walked; this covers the
 * scalar and grouped facts the profile form actually edits.
 */
export const diffProfileFacts = (
  before: CandidateProfile | null,
  after: CandidateProfile | null,
): FactUpdate[] => {
  if (!after) return [];

  const updates: FactUpdate[] = [];

  for (const [sectionKey, section] of Object.entries(after)) {
    if (isFact(section)) {
      const previous = factValue(before?.[sectionKey as keyof CandidateProfile]);
      if (!sameValue(previous?.value, section.value)) {
        updates.push(toFactUpdate(section, previous));
      }
      continue;
    }

    if (typeof section !== 'object' || section === null || Array.isArray(section)) {
      continue;
    }

    const previousSection = before?.[sectionKey as keyof CandidateProfile];

    for (const [leafKey, leaf] of Object.entries(section)) {
      if (!isFact(leaf)) continue;
      const previous = factValue(
        (previousSection as Record<string, unknown> | undefined)?.[leafKey],
      );
      if (!sameValue(previous?.value, leaf.value)) {
        updates.push(toFactUpdate(leaf, previous));
      }
    }
  }

  return updates;
};