import React from 'react';
import { ShieldCheck, UserCheck, FileCheck, PlayCircle, AlertCircle } from 'lucide-react';
import type { CandidateProfile, SafetyReport, Resume } from '../types/api.js';

interface StatusBannerProps {
  profile: CandidateProfile | null;
  safety: SafetyReport | null;
  resumes: Resume[];
}

export const StatusBanner: React.FC<StatusBannerProps> = ({ profile, safety, resumes }) => {
  const activeResume = resumes.find((r) => r.status === 'PARSED') || resumes[0];

  // Skills are stored in five grouped facts; a skill counts as verified only
  // when the group it lives in is itself VERIFIED.
  const skillGroups = profile?.skills
    ? ([
        profile.skills.proficient,
        profile.skills.expert,
        profile.skills.familiar,
        profile.skills.tools,
        profile.skills.languages,
      ] as const)
    : [];
  const verifiedSkillsCount = skillGroups.reduce(
    (total, fact) =>
      total + (fact?.status === 'VERIFIED' && Array.isArray(fact.value) ? fact.value.length : 0),
    0,
  );

  return (
    <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4 mb-6 shadow-sm">
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {/* Candidate Summary */}
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            <UserCheck className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xs text-slate-400">Target Candidate</div>
            <div className="text-sm font-semibold text-white">
              {profile?.identity?.full_name?.value || 'Unknown'}
            </div>
            <div className="text-xs text-emerald-400">
              {verifiedSkillsCount} verified skills • {profile?.experience?.total_years_experience?.value || 0} yrs exp
            </div>
          </div>
        </div>

        {/* Active Resume */}
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-lg bg-blue-500/10 text-blue-400 border border-blue-500/20">
            <FileCheck className="w-5 h-5" />
          </div>
          <div className="min-w-0">
            <div className="text-xs text-slate-400">Active Resume Variant</div>
            <div className="text-sm font-semibold text-white truncate">
              {activeResume?.variant || activeResume?.filename || 'Default Variant'}
            </div>
            <div className="text-xs text-blue-400">
              {activeResume?.file_type || 'PDF'} • Tailored for {activeResume?.role_focus || 'General'}
            </div>
          </div>
        </div>

        {/* Safety Mode */}
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-lg bg-purple-500/10 text-purple-400 border border-purple-500/20">
            <ShieldCheck className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xs text-slate-400">Safety Invariants</div>
            <div className="text-sm font-semibold text-white">
              {safety?.safe_mode ? 'Enforced' : 'Relaxed'} • {safety?.dry_run ? 'Dry-Run Guard' : 'Live'}
            </div>
            <div className="text-xs text-purple-400">
              {safety?.require_human_approval ? 'Human Approval Required' : 'Automated Batch'}
            </div>
          </div>
        </div>

        {/* Submission Control */}
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-lg bg-amber-500/10 text-amber-400 border border-amber-500/20">
            <PlayCircle className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xs text-slate-400">Submission Control</div>
            <div className="text-sm font-semibold text-white">
              {safety?.allow_final_submission ? 'Submission Enabled' : 'Submission Disabled'}
            </div>
            <div className="text-xs text-amber-400 flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400"></span>
              {safety?.allow_final_submission
                ? 'Review dry-run output before enabling'
                : 'Dry-run only by policy'}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default StatusBanner;