import React from 'react';
import { ShieldCheck, UserCheck, FileCheck, PlayCircle, AlertCircle } from 'lucide-react';
import type { CandidateProfile, SafetySettings, ResumeVariant } from '../types/index.js';

interface StatusBannerProps {
  profile: CandidateProfile | null;
  safety: SafetySettings | null;
  resumes: ResumeVariant[];
}

export const StatusBanner: React.FC<StatusBannerProps> = ({ profile, safety, resumes }) => {
  const activeResume = resumes.find(r => r.isActive) || resumes[0];
  const verifiedSkillsCount = profile?.skills.filter(s => s.status === 'VERIFIED').length || 0;

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
              {profile?.identity.full_name.value || 'Krishna Prasath'}
            </div>
            <div className="text-xs text-emerald-400">
              {verifiedSkillsCount} verified skills • {profile?.experience.total_years.value || 5} yrs exp
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
              {activeResume?.name || 'Default Variant'}
            </div>
            <div className="text-xs text-blue-400">
              {activeResume?.format.toUpperCase()} • Tailored for {activeResume?.targetRole}
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
              {safety?.safeMode ? 'Enforced' : 'Relaxed'} • {safety?.dryRun ? 'Dry-Run Guard' : 'Live'}
            </div>
            <div className="text-xs text-purple-400">
              {safety?.requireHumanApproval ? 'Human Approval Required' : 'Automated Batch'}
            </div>
          </div>
        </div>

        {/* Run Limits */}
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-lg bg-amber-500/10 text-amber-400 border border-amber-500/20">
            <PlayCircle className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xs text-slate-400">Daily Application Quota</div>
            <div className="text-sm font-semibold text-white">
              {safety?.applicationsToday ?? 0} / {safety?.maxApplicationsPerRun ?? 15} Applications
            </div>
            <div className="text-xs text-amber-400 flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400"></span>
              {safety?.applicationsToday && safety.applicationsToday >= (safety.maxApplicationsPerRun || 15)
                ? 'Limit Reached'
                : 'Safe buffer active'}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
