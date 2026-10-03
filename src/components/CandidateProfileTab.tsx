import React, { useState } from 'react';
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
import type { CandidateProfile, FactStatus } from '../types/index.js';

interface CandidateProfileTabProps {
  profile: CandidateProfile | null;
  onUpdateProfile: (updated: CandidateProfile) => Promise<void>;
  onValidateProfile: () => Promise<any>;
}

export const CandidateProfileTab: React.FC<CandidateProfileTabProps> = ({
  profile,
  onUpdateProfile,
  onValidateProfile,
}) => {
  const [formData, setFormData] = useState<CandidateProfile | null>(profile);
  const [validationResult, setValidationResult] = useState<any>(null);
  const [isValidating, setIsValidating] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // New skill form
  const [newSkillName, setNewSkillName] = useState('');
  const [newSkillYears, setNewSkillYears] = useState(3);
  const [newSkillProficiency, setNewSkillProficiency] = useState<'Beginner' | 'Intermediate' | 'Advanced' | 'Expert'>('Advanced');
  const [newSkillCategory, setNewSkillCategory] = useState('LANGUAGES');

  if (!formData) return null;

  const handleSave = async () => {
    setIsSaving(true);
    try {
      await onUpdateProfile(formData);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
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
    if (!newSkillName.trim()) return;
    const updatedSkills = [
      ...formData.skills,
      {
        name: newSkillName.trim(),
        years: Number(newSkillYears),
        proficiency: newSkillProficiency,
        category: newSkillCategory,
        status: 'VERIFIED' as FactStatus,
      },
    ];
    setFormData({ ...formData, skills: updatedSkills });
    setNewSkillName('');
  };

  const removeSkill = (index: number) => {
    const updatedSkills = formData.skills.filter((_, i) => i !== index);
    setFormData({ ...formData, skills: updatedSkills });
  };

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
              Completeness: {validationResult.completeness}%
            </span>
          </div>

          {validationResult.missing_required.length > 0 && (
            <div className="mt-2 text-xs text-amber-300">
              Missing required fields: {validationResult.missing_required.join(', ')}
            </div>
          )}

          {validationResult.findings.length > 0 && (
            <div className="mt-2 text-xs text-slate-300 space-y-0.5">
              {validationResult.findings.map((f: string, i: number) => (
                <div key={i}>• {f}</div>
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
                value={formData.identity.full_name.value || ''}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    identity: {
                      ...formData.identity,
                      full_name: { ...formData.identity.full_name, value: e.target.value },
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
                value={formData.identity.email.value || ''}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    identity: {
                      ...formData.identity,
                      email: { ...formData.identity.email, value: e.target.value },
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
                value={formData.identity.phone.value || ''}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    identity: {
                      ...formData.identity,
                      phone: { ...formData.identity.phone, value: e.target.value },
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
                value={formData.identity.location.value || ''}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    identity: {
                      ...formData.identity,
                      location: { ...formData.identity.location, value: e.target.value },
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
                value={formData.identity.linkedin_url.value || ''}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    identity: {
                      ...formData.identity,
                      linkedin_url: { ...formData.identity.linkedin_url, value: e.target.value },
                    },
                  })
                }
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white focus:border-blue-500 font-mono text-xs"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1">GitHub / Portfolio URL</label>
              <input
                type="text"
                value={formData.identity.github_url.value || ''}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    identity: {
                      ...formData.identity,
                      github_url: { ...formData.identity.github_url, value: e.target.value },
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
                  Controls hard gate evaluation for jobs stating &quot;No sponsorship provided&quot;
                </div>
              </div>
              <select
                value={formData.work_authorization.requires_sponsorship.value ? 'yes' : 'no'}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    work_authorization: {
                      ...formData.work_authorization,
                      requires_sponsorship: {
                        ...formData.work_authorization.requires_sponsorship,
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
                value={formData.work_authorization.visa_status.value || ''}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    work_authorization: {
                      ...formData.work_authorization,
                      visa_status: {
                        ...formData.work_authorization.visa_status,
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
                  value={formData.experience.total_years.value || 0}
                  onChange={(e) =>
                    setFormData({
                      ...formData,
                      experience: {
                        ...formData.experience,
                        total_years: {
                          ...formData.experience.total_years,
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
                  Current / Target Seniority
                </label>
                <input
                  type="text"
                  value={formData.experience.seniority_level.value || ''}
                  onChange={(e) =>
                    setFormData({
                      ...formData,
                      experience: {
                        ...formData.experience,
                        seniority_level: {
                          ...formData.experience.seniority_level,
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
            {formData.skills.length} Registered Skills
          </span>
        </div>

        {/* Add Skill Row */}
        <div className="grid grid-cols-1 sm:grid-cols-5 gap-2 bg-slate-950 p-3 rounded-xl border border-slate-800">
          <input
            type="text"
            placeholder="Skill Name (e.g. Next.js, Go, Kafka)"
            value={newSkillName}
            onChange={(e) => setNewSkillName(e.target.value)}
            className="sm:col-span-2 bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-white focus:border-blue-500"
          />
          <input
            type="number"
            min="1"
            max="30"
            placeholder="Years"
            value={newSkillYears}
            onChange={(e) => setNewSkillYears(parseInt(e.target.value, 10) || 1)}
            className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-white focus:border-blue-500"
          />
          <select
            value={newSkillProficiency}
            onChange={(e) => setNewSkillProficiency(e.target.value as any)}
            className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-white focus:border-blue-500"
          >
            <option value="Beginner">Beginner</option>
            <option value="Intermediate">Intermediate</option>
            <option value="Advanced">Advanced</option>
            <option value="Expert">Expert</option>
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

        {/* Skills Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2.5">
          {formData.skills.map((skill, index) => (
            <div
              key={index}
              className="flex items-center justify-between p-2.5 rounded-xl bg-slate-950 border border-slate-800 hover:border-slate-700 transition-colors"
            >
              <div>
                <div className="text-xs font-bold text-white">{skill.name}</div>
                <div className="text-[11px] text-slate-400">
                  {skill.years} yrs • {skill.proficiency}
                </div>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono">
                  {skill.status}
                </span>
                <button
                  type="button"
                  onClick={() => removeSkill(index)}
                  className="text-slate-500 hover:text-rose-400 p-1"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
