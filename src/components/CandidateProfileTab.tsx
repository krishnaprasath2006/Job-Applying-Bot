import React, { useState, useEffect } from 'react';
import {
  UserCheck,
  CheckCircle,
  AlertCircle,
  HelpCircle,
  Plus,
  Trash2,
  Save,
  ShieldCheck,
  Sparkles,
  ExternalLink,
} from 'lucide-react';
import type { CandidateProfile, FactStatus, ProfileValidationResponse, FactValue } from '../types/api.js';
import { profileApi } from '../lib/api/index.js';

interface CandidateProfileTabProps {
  profile: CandidateProfile | null;
  onUpdateProfile: (updated: CandidateProfile) => Promise<void>;
  onValidateProfile: () => Promise<any>;
}

/** The five skill buckets defined by SkillsSection in the profile schema. */
type SkillGroup = 'proficient' | 'expert' | 'familiar' | 'tools' | 'languages';

const SKILL_GROUPS: Array<{ key: SkillGroup; label: string }> = [
  { key: 'proficient', label: 'Proficient' },
  { key: 'expert', label: 'Expert' },
  { key: 'familiar', label: 'Familiar' },
  { key: 'tools', label: 'Tools' },
  { key: 'languages', label: 'Languages' },
];

/** A fact's value is UNKNOWN (null) until proven, so coerce defensively. */
const asStringList = (fact: FactValue | undefined): string[] =>
  Array.isArray(fact?.value) ? (fact!.value as string[]) : [];

export const CandidateProfileTab: React.FC<CandidateProfileTabProps> = ({
  profile,
  onUpdateProfile,
  onValidateProfile,
}) => {
  const [formData, setFormData] = useState<CandidateProfile | null>(profile);
  const [validationResult, setValidationResult] = useState<ProfileValidationResponse | null>(null);
  const [isValidating, setIsValidating] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // New skill form
  const [newSkillName, setNewSkillName] = useState('');
  const [newSkillGroup, setNewSkillGroup] = useState<SkillGroup>('proficient');

  // Reload formData when profile changes
  useEffect(() => {
    setFormData(profile);
  }, [profile]);

  const handleSave = async () => {
    if (!formData) return;
    setIsSaving(true);
    setSaveError(null);
    try {
      await onUpdateProfile(formData);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err) {
      console.error(err);
      setSaveError(
        err instanceof Error
          ? err.message
          : 'The server rejected these facts. Nothing was saved.',
      );
    } finally {
      setIsSaving(false);
    }
  };

  const handleValidate = async () => {
    setIsValidating(true);
    try {
      const res = await onValidateProfile();
      setValidationResult(res);
    } finally {
      setIsValidating(false);
    }
  };

  const addSkill = () => {
    if (!newSkillName.trim() || !formData) return;
    const name = newSkillName.trim();
    const current = asStringList(formData.skills?.[newSkillGroup]);
    if (current.some((s) => s.toLowerCase() === name.toLowerCase())) return;
    setFormData({
      ...formData,
      skills: {
        ...formData.skills,
        [newSkillGroup]: {
          ...formData.skills![newSkillGroup],
          value: [...current, name],
          // A skill typed into this form is a claim, not a sourced fact. The
          // server stores a human claim as INFERRED, and asserting VERIFIED
          // here would show a status the backend will not keep.
          status: 'INFERRED',
        },
      },
    });
    setNewSkillName('');
  };

  const removeSkill = (group: SkillGroup, index: number) => {
    if (!formData) return;
    const current = asStringList(formData.skills?.[group]);
    setFormData({
      ...formData,
      skills: {
        ...formData.skills,
        [group]: {
          ...formData.skills![group],
          value: current.filter((_, i) => i !== index),
        },
      },
    });
  };

  // Helper to update a nested fact value
  const updateFact = (path: string, value: any) => {
    if (!formData) return;
    // This is a simplified update - a full implementation would use
    // a deep path setter. For now we rely on the form inputs directly.
  };

  if (!formData) return null;

  return (
    <div className="space-y-6">
      {/* Header & Completeness */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <UserCheck className="w-5 h-5 text-blue-400" />
            <h2 className="text-xl font-bold text-white">Candidate Facts & Evidence Profile</h2>
            <span className="text-xs px-2.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-semibold">
              Phase 2 Evidence-Backed
            </span>
          </div>
          <p className="text-sm text-slate-400 mt-1">
            Every application answer and match computation derives strictly from these verified facts.
            No hallucinated values are ever used.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={handleValidate}
            disabled={isValidating}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 cursor-pointer"
          >
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
            <span>{isValidating ? 'Validating...' : 'Validate Profile'}</span>
          </button>

          <button
            onClick={handleSave}
            disabled={isSaving}
            className="flex items-center gap-1.5 px-5 py-2 rounded-xl text-sm font-semibold bg-blue-600 hover:bg-blue-500 text-white shadow-md shadow-blue-500/20 cursor-pointer"
          >
            <Save className="w-4 h-4" />
            <span>{isSaving ? 'Saving...' : saveSuccess ? 'Saved!' : 'Save Facts'}</span>
          </button>
        </div>
      </div>

      {/* Save failure is shown here, not only as a toast: a save that did not
          persist must never read as a success. */}
      {saveError && (
        <div className="flex items-start gap-2 p-4 rounded-xl border bg-rose-950/30 border-rose-800/50 text-rose-200">
          <AlertCircle className="w-5 h-5 shrink-0 text-rose-400" />
          <div>
            <div className="font-semibold">Nothing was saved</div>
            <p className="text-sm mt-0.5 break-words">{saveError}</p>
          </div>
        </div>
      )}

      {/* Validation Result Findings Banner */}
      {validationResult && (
        <div
          className={`p-4 rounded-xl border ${
            validationResult.is_valid
              ? 'bg-emerald-950/20 border-emerald-800/40 text-emerald-200'
              : 'bg-amber-950/30 border-amber-800/50 text-amber-200'
          }`}
        >
          <div className="flex items-center gap-2 font-semibold">
            {validationResult.is_valid ? (
              <CheckCircle className="w-5 h-5 text-emerald-400" />
            ) : (
              <AlertCircle className="w-5 h-5 text-amber-400" />
            )}
            <span>
              Validation Result: {validationResult.is_valid ? 'Profile Complete & Valid' : 'Missing Required Application Fields'}
            </span>
            <span className="ml-auto text-xs bg-slate-900/60 px-2 py-0.5 rounded border border-current">
              Completeness: {Math.round(validationResult.completeness * 100)}%
            </span>
          </div>

          {validationResult.missing_required.length > 0 && (
            <div className="mt-2 text-xs text-amber-300">
              Missing required fields: {validationResult.missing_required.join(', ')}
            </div>
          )}

          {validationResult.issues.length > 0 && (
            <div className="mt-2 text-xs text-slate-300 space-y-0.5">
              {validationResult.issues.map((issue, i) => (
                <div key={i}>• [{issue.severity}] {issue.code}: {issue.message}</div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 2-Column Sections */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Identity & Contact */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <h3 className="font-bold text-white text-base">Identity & Contact Information</h3>
            <span className="text-xs px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 font-mono">
              VERIFIED
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1">Full Legal Name</label>
              <input
                type="text"
                value={formData.identity?.full_name?.value || ''}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    identity: {
                      ...formData.identity,
                      full_name: { ...formData.identity!.full_name, value: e.target.value },
                    },
                  })
                }
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white focus:border-blue-500"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1">Email Address</label>
              <input
                type="email"
                value={formData.contact?.email?.value || ''}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    contact: {
                      ...formData.contact,
                      email: { ...formData.contact!.email, value: e.target.value },
                    },
                  })
                }
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white focus:border-blue-500"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1">Phone Number</label>
              <input
                type="text"
                value={formData.contact?.phone?.value || ''}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    contact: {
                      ...formData.contact,
                      phone: { ...formData.contact!.phone, value: e.target.value },
                    },
                  })
                }
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white focus:border-blue-500"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1">Current Location</label>
              <input
                type="text"
                value={formData.location?.current_city?.value || ''}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    location: {
                      ...formData.location,
                      current_city: { ...formData.location!.current_city, value: e.target.value },
                    },
                  })
                }
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white focus:border-blue-500"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1">LinkedIn Profile URL</label>
              <input
                type="text"
                value={formData.contact?.linkedin_url?.value || ''}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    contact: {
                      ...formData.contact,
                      linkedin_url: { ...formData.contact!.linkedin_url, value: e.target.value },
                    },
                  })
                }
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white focus:border-blue-500 font-mono text-xs"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1">Website / Portfolio</label>
              <input
                type="text"
                value={formData.contact?.website?.value || ''}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    contact: {
                      ...formData.contact,
                      website: { ...formData.contact!.website, value: e.target.value },
                    },
                  })
                }
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white focus:border-blue-500 font-mono text-xs"
              />
            </div>
          </div>
        </div>

        {/* Work Authorization & Hard Gate Drivers */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <h3 className="font-bold text-white text-base">Work Authorization & Hard Gate Facts</h3>
            <span className="text-xs px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 font-mono">
              CRITICAL VETO GATE
            </span>
          </div>

          <div className="space-y-3 text-sm">
            <div className="flex items-center justify-between p-3 rounded-xl bg-slate-950 border border-slate-800">
              <div>
                <div className="font-semibold text-white">Requires Visa Sponsorship</div>
                <div className="text-xs text-slate-400">
                  Controls hard gate evaluation for jobs stating "No sponsorship provided"
                </div>
              </div>
              <select
                value={formData.authorization?.requires_sponsorship?.value ? 'yes' : 'no'}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    authorization: {
                      ...formData.authorization,
                      requires_sponsorship: {
                        ...formData.authorization!.requires_sponsorship,
                        value: e.target.value === 'yes',
                      },
                    },
                  })
                }
                className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white focus:border-blue-500"
              >
                <option value="no">No (Authorized without sponsorship)</option>
                <option value="yes">Yes (Requires sponsorship)</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1">
                Visa / Legal Status Description
              </label>
              <input
                type="text"
                value={formData.authorization?.visa_status?.value || ''}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    authorization: {
                      ...formData.authorization,
                      visa_status: {
                        ...formData.authorization!.visa_status,
                        value: e.target.value,
                      },
                    },
                  })
                }
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white focus:border-blue-500"
              />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">
                  Total Verified Years of Experience
                </label>
                <input
                  type="number"
                  step="0.5"
                  min="0"
                  value={formData.experience?.total_years_experience?.value || 0}
                  onChange={(e) =>
                    setFormData({
                      ...formData,
                      experience: {
                        ...formData.experience,
                        total_years_experience: {
                          ...formData.experience!.total_years_experience,
                          value: parseFloat(e.target.value) || 0,
                        },
                      },
                    })
                  }
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white focus:border-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">
                  Target Headline
                </label>
                <input
                  type="text"
                  value={formData.identity?.headline?.value || ''}
                  onChange={(e) =>
                    setFormData({
                      ...formData,
                      identity: {
                        ...formData.identity,
                        headline: {
                          ...formData.identity!.headline,
                          value: e.target.value,
                        },
                      },
                    })
                  }
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white focus:border-blue-500"
                />
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Skills Inventory Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 border-b border-slate-800 pb-3">
          <div>
            <h3 className="font-bold text-white text-base">Verified Skills Inventory</h3>
            <p className="text-xs text-slate-400">
              Matcher tests extracted job requirements against these claimed skills.
            </p>
          </div>
          <span className="text-xs text-slate-400 font-mono">
            {SKILL_GROUPS.reduce(
              (total, group) => total + asStringList(formData.skills?.[group.key]).length,
              0,
            )}{' '}
            Registered Skills
          </span>
        </div>

        {/* Add Skill Row */}
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-2 bg-slate-950 p-3 rounded-xl border border-slate-800">
          <input
            type="text"
            placeholder="Skill Name (e.g. Next.js, Go, Kafka)"
            value={newSkillName}
            onChange={(e) => setNewSkillName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') addSkill();
            }}
            className="sm:col-span-2 bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-white focus:border-blue-500"
          />
          <select
            value={newSkillGroup}
            onChange={(e) => setNewSkillGroup(e.target.value as SkillGroup)}
            className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-white focus:border-blue-500"
          >
            {SKILL_GROUPS.map((group) => (
              <option key={group.key} value={group.key}>
                {group.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={addSkill}
            className="flex items-center justify-center gap-1 bg-blue-600 hover:bg-blue-500 text-white rounded-lg px-3 py-1.5 text-xs font-semibold cursor-pointer"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Add Skill</span>
          </button>
        </div>

        {/* Skill Groups */}
        <div className="space-y-3">
          {SKILL_GROUPS.map((group) => {
            const names = asStringList(formData.skills?.[group.key]);
            const status = formData.skills?.[group.key]?.status;
            return (
              <div key={group.key} className="bg-slate-950/60 border border-slate-800 rounded-xl p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-bold text-slate-200">{group.label}</span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 font-mono">
                    {status || 'UNKNOWN'} • {names.length}
                  </span>
                </div>
                {names.length === 0 ? (
                  <div className="text-[11px] text-slate-600 font-mono">No skills recorded</div>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {names.map((skill, index) => (
                      <div
                        key={`${group.key}-${skill}-${index}`}
                        className="flex items-center gap-1.5 pl-2.5 py-1 rounded-lg bg-slate-900 border border-slate-800 hover:border-slate-700 transition-colors"
                      >
                        <span className="text-xs font-semibold text-white">{skill}</span>
                        <button
                          type="button"
                          onClick={() => removeSkill(group.key, index)}
                          className="text-slate-500 hover:text-rose-400 p-0.5 cursor-pointer"
                          aria-label={`Remove ${skill}`}
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

export default CandidateProfileTab;