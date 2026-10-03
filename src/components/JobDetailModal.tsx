import React from 'react';
import {
  X,
  CheckCircle,
  XCircle,
  AlertTriangle,
  HelpCircle,
  Briefcase,
  MapPin,
  DollarSign,
  Calendar,
  ExternalLink,
  ShieldCheck,
  Send,
  ThumbsUp,
  ThumbsDown,
} from 'lucide-react';
import type { Job, RequirementScore, RequirementEvaluation } from '../types/index.js';

interface JobDetailModalProps {
  job: Job | null;
  onClose: () => void;
  onAccept: (jobId: string) => void;
  onReject: (jobId: string) => void;
  onApply: (jobId: string) => void;
  dryRun: boolean;
}

export const JobDetailModal: React.FC<JobDetailModalProps> = ({
  job,
  onClose,
  onAccept,
  onReject,
  onApply,
  dryRun,
}) => {
  if (!job) return null;

  const getEvaluationBadge = (evaluation: RequirementEvaluation) => {
    switch (evaluation) {
      case 'VERIFIED_MATCH':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            <CheckCircle className="w-3 h-3" /> Verified Match
          </span>
        );
      case 'DERIVED_MATCH':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-blue-500/10 text-blue-400 border border-blue-500/20">
            <CheckCircle className="w-3 h-3" /> Derived Match
          </span>
        );
      case 'PARTIAL_MATCH':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
            <AlertTriangle className="w-3 h-3" /> Partial
          </span>
        );
      case 'REVIEW_NEEDED':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20">
            <HelpCircle className="w-3 h-3" /> Review Needed
          </span>
        );
      case 'DERIVED_MISS':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-rose-500/10 text-rose-400 border border-rose-500/20">
            <XCircle className="w-3 h-3" /> Derived Miss
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-slate-700 text-slate-300">
            Unknown
          </span>
        );
    }
  };

  const getDecisionBadge = (decision: string) => {
    switch (decision) {
      case 'STRONG_MATCH':
        return (
          <span className="px-3 py-1 rounded-full text-xs font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
            Strong Match (90%+)
          </span>
        );
      case 'GOOD_MATCH':
        return (
          <span className="px-3 py-1 rounded-full text-xs font-bold bg-blue-500/20 text-blue-300 border border-blue-500/30">
            Good Match (70-89%)
          </span>
        );
      case 'PARTIAL_MATCH':
        return (
          <span className="px-3 py-1 rounded-full text-xs font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30">
            Partial Match
          </span>
        );
      case 'HARD_MISMATCH':
        return (
          <span className="px-3 py-1 rounded-full text-xs font-bold bg-rose-500/20 text-rose-300 border border-rose-500/30">
            Hard Gate Veto
          </span>
        );
      default:
        return (
          <span className="px-3 py-1 rounded-full text-xs font-bold bg-slate-700 text-slate-300">
            Unscored
          </span>
        );
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-xs flex items-center justify-center p-4 overflow-y-auto">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-4xl w-full max-h-[90vh] flex flex-col shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="p-6 border-b border-slate-800 flex items-start justify-between bg-slate-900/90">
          <div className="space-y-1">
            <div className="flex items-center gap-3 flex-wrap">
              <h2 className="text-xl font-bold text-white">{job.title}</h2>
              {getDecisionBadge(job.matchResult.decision)}
              {job.easyApply && (
                <span className="px-2 py-0.5 rounded text-xs font-medium bg-blue-500/20 text-blue-400 border border-blue-500/30">
                  Easy Apply
                </span>
              )}
            </div>
            <div className="flex items-center gap-4 text-sm text-slate-400 flex-wrap">
              <span className="flex items-center gap-1 font-medium text-slate-300">
                <Briefcase className="w-4 h-4 text-slate-500" />
                {job.company}
              </span>
              <span className="flex items-center gap-1">
                <MapPin className="w-4 h-4 text-slate-500" />
                {job.location} ({job.remoteType})
              </span>
              <span className="flex items-center gap-1 text-emerald-400">
                <DollarSign className="w-4 h-4" />
                {job.salaryRange}
              </span>
              <span className="flex items-center gap-1 text-slate-500">
                <Calendar className="w-4 h-4" />
                {job.postedDate}
              </span>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-slate-400 hover:text-white rounded-lg hover:bg-slate-800 transition-colors cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content Body */}
        <div className="p-6 overflow-y-auto space-y-6">
          {/* Hard Gate & Summary Banner */}
          <div
            className={`p-4 rounded-xl border ${
              job.matchResult.gate.status === 'PASS'
                ? 'bg-emerald-950/20 border-emerald-800/40 text-emerald-200'
                : 'bg-rose-950/30 border-rose-800/50 text-rose-200'
            }`}
          >
            <div className="flex items-center gap-2 mb-2 font-semibold">
              <ShieldCheck
                className={`w-5 h-5 ${
                  job.matchResult.gate.status === 'PASS' ? 'text-emerald-400' : 'text-rose-400'
                }`}
              />
              <span>
                Hard Gate Invariant Status:{' '}
                {job.matchResult.gate.status === 'PASS' ? 'PASSED (Eligible)' : 'FAILED (VETOED)'}
              </span>
              <span className="ml-auto text-sm font-bold bg-slate-900/60 px-2.5 py-0.5 rounded border border-current">
                Fit Score: {job.matchResult.overallScore}%
              </span>
            </div>

            {job.matchResult.gate.status === 'FAIL' && (
              <div className="mt-2 text-sm text-rose-300 bg-rose-900/40 p-3 rounded-lg border border-rose-700/50">
                <ul className="list-disc list-inside space-y-1">
                  {job.matchResult.gate.reasons.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </div>
            )}

            <p className="text-sm mt-2 text-slate-300">{job.matchResult.summary}</p>
          </div>

          {/* Requirements Breakdown Table */}
          <div>
            <h3 className="text-base font-semibold text-white mb-3 flex items-center justify-between">
              <span>Requirement Analysis & Evidence Breakdown</span>
              <span className="text-xs text-slate-400 font-normal">
                {job.matchResult.scores.length} Extracted Items
              </span>
            </h3>

            <div className="border border-slate-800 rounded-xl overflow-hidden">
              <table className="w-full text-left text-sm">
                <thead className="bg-slate-800/60 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  <tr>
                    <th className="px-4 py-3">Requirement</th>
                    <th className="px-4 py-3">Category</th>
                    <th className="px-4 py-3">Priority</th>
                    <th className="px-4 py-3">Verdict</th>
                    <th className="px-4 py-3">Candidate Evidence / Reasoning</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800 text-slate-300">
                  {job.matchResult.scores.map((score, idx) => (
                    <tr key={idx} className="hover:bg-slate-800/30 transition-colors">
                      <td className="px-4 py-3 font-medium text-white max-w-xs">
                        {score.requirement_text}
                      </td>
                      <td className="px-4 py-3">
                        <span className="px-2 py-0.5 rounded text-xs bg-slate-800 text-slate-300 font-mono">
                          {score.kind}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`text-xs font-semibold ${
                            score.priority === 'REQUIRED' ? 'text-amber-400' : 'text-slate-400'
                          }`}
                        >
                          {score.priority}
                        </span>
                      </td>
                      <td className="px-4 py-3">{getEvaluationBadge(score.evaluation)}</td>
                      <td className="px-4 py-3 text-xs text-slate-300">
                        <div>{score.reason}</div>
                        {score.candidate_field_path && (
                          <div className="text-[11px] text-blue-400/80 font-mono mt-0.5">
                            ref: {score.candidate_field_path}
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Full Job Description */}
          <div>
            <h3 className="text-base font-semibold text-white mb-2">Original Job Description</h3>
            <div className="bg-slate-950 p-4 rounded-xl border border-slate-800 text-sm text-slate-300 whitespace-pre-line max-h-56 overflow-y-auto leading-relaxed font-sans">
              {job.description}
            </div>
          </div>
        </div>

        {/* Footer Actions */}
        <div className="p-4 sm:p-6 border-t border-slate-800 bg-slate-900/90 flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <a
              href={job.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
            >
              <ExternalLink className="w-4 h-4" />
              Source Posting
            </a>
          </div>

          <div className="flex items-center gap-2">
            {job.status !== 'REJECTED' && (
              <button
                onClick={() => onReject(job.id)}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium bg-rose-500/10 text-rose-400 hover:bg-rose-500/20 border border-rose-500/20 transition-colors cursor-pointer"
              >
                <ThumbsDown className="w-4 h-4" />
                Reject
              </button>
            )}

            {job.status !== 'ACCEPTED' && job.matchResult.gate.status === 'PASS' && (
              <button
                onClick={() => onAccept(job.id)}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 border border-emerald-500/30 transition-colors cursor-pointer"
              >
                <ThumbsUp className="w-4 h-4" />
                Accept to Queue
              </button>
            )}

            <button
              onClick={() => onApply(job.id)}
              disabled={job.matchResult.gate.status === 'FAIL' || job.status === 'APPLIED'}
              className={`inline-flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-semibold transition-all cursor-pointer ${
                job.status === 'APPLIED'
                  ? 'bg-slate-800 text-slate-500 cursor-not-allowed'
                  : job.matchResult.gate.status === 'FAIL'
                  ? 'bg-slate-800 text-slate-500 cursor-not-allowed'
                  : 'bg-blue-600 hover:bg-blue-500 text-white shadow-lg shadow-blue-600/30'
              }`}
            >
              <Send className="w-4 h-4" />
              {job.status === 'APPLIED'
                ? 'Applied'
                : dryRun
                ? 'Simulate Apply (Dry Run)'
                : 'Submit Application'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
