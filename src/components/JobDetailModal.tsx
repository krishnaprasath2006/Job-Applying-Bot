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
import type { Job, MatchResult, Requirement, RequirementScore } from '../types/api.js';

interface JobDetailModalProps {
  job: Job | null;
  /**
   * Match is a separate resource in this API (`POST /jobs/{id}/match`), not a
   * field on Job, so it is supplied separately and may be absent.
   */
  matchResult?: MatchResult | null;
  onClose: () => void;
  onAccept: (jobId: string) => void;
  onReject: (jobId: string) => void;
  onApply: (jobId: string) => void;
  dryRun: boolean;
}

type Evaluation = RequirementScore['evaluation'];

const EVALUATION_BADGES: Record<Evaluation, { label: string; className: string }> = {
  VERIFIED_MATCH: {
    label: 'Verified Match',
    className: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  },
  DERIVED_MATCH: {
    label: 'Derived Match',
    className: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
  },
  VERIFIED_MISMATCH: {
    label: 'Verified Miss',
    className: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
  },
  DERIVED_MISMATCH: {
    label: 'Derived Miss',
    className: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
  },
  REVIEW_REQUIRED: {
    label: 'Review Needed',
    className: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
  },
  UNKNOWN: {
    label: 'Unknown',
    className: 'bg-slate-700 text-slate-300 border-slate-600',
  },
};

const EvaluationIcon: Record<Evaluation, typeof CheckCircle> = {
  VERIFIED_MATCH: CheckCircle,
  DERIVED_MATCH: CheckCircle,
  VERIFIED_MISMATCH: XCircle,
  DERIVED_MISMATCH: XCircle,
  REVIEW_REQUIRED: HelpCircle,
  UNKNOWN: AlertTriangle,
};

const getEvaluationBadge = (evaluation: Evaluation) => {
  const badge = EVALUATION_BADGES[evaluation] ?? EVALUATION_BADGES.UNKNOWN;
  const Icon = EvaluationIcon[evaluation] ?? AlertTriangle;
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium border ${badge.className}`}
    >
      <Icon className="w-3 h-3" /> {badge.label}
    </span>
  );
};

const DECISION_BADGES: Record<MatchResult['decision'], { label: string; className: string }> = {
  MATCH: {
    label: 'Strong Match',
    className: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
  },
  PARTIAL_MATCH: {
    label: 'Partial Match',
    className: 'bg-blue-500/20 text-blue-300 border-blue-500/30',
  },
  HARD_MISMATCH: {
    label: 'Hard Gate Veto',
    className: 'bg-rose-500/20 text-rose-300 border-rose-500/30',
  },
  INSUFFICIENT_EVIDENCE: {
    label: 'Insufficient Evidence',
    className: 'bg-amber-500/20 text-amber-300 border-amber-500/30',
  },
  REVIEW_REQUIRED: {
    label: 'Review Required',
    className: 'bg-amber-500/20 text-amber-300 border-amber-500/30',
  },
};

const getDecisionBadge = (decision?: MatchResult['decision']) => {
  if (!decision) {
    return (
      <span className="px-3 py-1 rounded-full text-xs font-bold bg-slate-700 text-slate-300">
        Unscored
      </span>
    );
  }
  const badge = DECISION_BADGES[decision];
  return (
    <span
      className={`px-3 py-1 rounded-full text-xs font-bold border ${badge.className}`}
    >
      {badge.label}
    </span>
  );
};

/** Coarse bucket used to drive button visibility. */
type DisplayStatus = 'DISCOVERED' | 'IN_REVIEW' | 'READY' | 'APPLIED' | 'REJECTED';

const getDisplayStatus = (status: Job['status']): DisplayStatus => {
  switch (status) {
    case 'ANALYSIS_PENDING':
    case 'ANALYZED':
    case 'MATCHED':
    case 'REVIEW_REQUIRED':
      return 'IN_REVIEW';
    case 'READY_FOR_APPLICATION':
      return 'READY';
    case 'APPLYING':
    case 'APPLIED':
      return 'APPLIED';
    case 'REJECTED':
    case 'SKIPPED':
    case 'FAILED':
      return 'REJECTED';
    default:
      return 'DISCOVERED';
  }
};

/** Requirements carry no evaluation; only scored rows do. */
type Row = { kind: 'score'; score: RequirementScore } | { kind: 'requirement'; requirement: Requirement };

export const JobDetailModal: React.FC<JobDetailModalProps> = ({
  job,
  matchResult,
  onClose,
  onAccept,
  onReject,
  onApply,
  dryRun,
}) => {
  if (!job) return null;

  const gateStatus = matchResult?.gate?.status;
  const gatePassed = gateStatus === 'PASS';
  const isHardVeto = gateStatus === 'HARD_MISMATCH';
  const displayStatus = getDisplayStatus(job.status);

  const mismatchChecks = (matchResult?.gate?.checks ?? []).filter(
    (check) => check.evaluation === 'VERIFIED_MISMATCH' || check.evaluation === 'DERIVED_MISMATCH',
  );

  const rows: Row[] = matchResult?.scores?.length
    ? matchResult.scores.map((score) => ({ kind: 'score' as const, score }))
    : (job.requirements ?? []).map((requirement) => ({ kind: 'requirement' as const, requirement }));

  const fitScore =
    typeof matchResult?.similarity_score === 'number'
      ? `${Math.round(matchResult.similarity_score * 100)}%`
      : 'n/a';

  const salary =
    job.salary_min && job.salary_max
      ? `$${(job.salary_min / 1000).toFixed(0)}k - $${(job.salary_max / 1000).toFixed(0)}k`
      : job.salary_min
        ? `$${(job.salary_min / 1000).toFixed(0)}k+`
        : 'Not specified';

  return (
    <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-xs flex items-center justify-center p-4 overflow-y-auto">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-4xl w-full max-h-[90vh] flex flex-col shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="p-6 border-b border-slate-800 flex items-start justify-between bg-slate-900/90">
          <div className="space-y-1">
            <div className="flex items-center gap-3 flex-wrap">
              <h2 className="text-xl font-bold text-white">{job.title}</h2>
              {getDecisionBadge(matchResult?.decision)}
            </div>
            <div className="flex items-center gap-4 text-sm text-slate-400 flex-wrap">
              <span className="flex items-center gap-1 font-medium text-slate-300">
                <Briefcase className="w-4 h-4 text-slate-500" />
                {job.company}
              </span>
              <span className="flex items-center gap-1">
                <MapPin className="w-4 h-4 text-slate-500" />
                {job.location || 'Unknown'} ({job.workplace_type || 'Unknown'})
              </span>
              <span className="flex items-center gap-1 text-emerald-400">
                <DollarSign className="w-4 h-4" />
                {salary}
              </span>
              <span className="flex items-center gap-1 text-slate-500">
                <Calendar className="w-4 h-4" />
                {job.posted_at || 'Unknown'}
              </span>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-slate-400 hover:text-white rounded-lg hover:bg-slate-800 transition-colors cursor-pointer"
            aria-label="Close"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content Body */}
        <div className="p-6 overflow-y-auto space-y-6">
          {/* Hard Gate Banner */}
          <div
            className={`p-4 rounded-xl border ${
              gatePassed
                ? 'bg-emerald-950/20 border-emerald-800/40 text-emerald-200'
                : 'bg-rose-950/30 border-rose-800/50 text-rose-200'
            }`}
          >
            <div className="flex items-center gap-2 mb-2 font-semibold">
              <ShieldCheck className={`w-5 h-5 ${gatePassed ? 'text-emerald-400' : 'text-rose-400'}`} />
              <span>
                Hard Gate Invariant Status:{' '}
                {gateStatus ? (gatePassed ? 'PASSED (Eligible)' : gateStatus) : 'Not evaluated'}
              </span>
              <span className="ml-auto text-sm font-bold bg-slate-900/60 px-2.5 py-0.5 rounded border border-current">
                Fit Score: {fitScore}
              </span>
            </div>

            {mismatchChecks.length > 0 && (
              <ul className="list-disc list-inside space-y-1 mt-2 text-sm text-rose-300">
                {mismatchChecks.map((check, i) => (
                  <li key={check.requirement_index ?? i}>
                    <span className="font-semibold">{check.requirement_text}</span> — {check.reason}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Requirements Breakdown Table */}
          <div>
            <h3 className="text-base font-semibold text-white mb-3 flex items-center justify-between">
              <span>Requirement Analysis & Evidence Breakdown</span>
              <span className="text-xs text-slate-400 font-normal">{rows.length} Extracted Items</span>
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
                  {rows.map((row, idx) => {
                    const text =
                      row.kind === 'score' ? row.score.requirement_text : row.requirement.text;
                    const kind = row.kind === 'score' ? row.score.kind : row.requirement.kind;
                    const priority = row.kind === 'score' ? row.score.priority : row.requirement.priority;
                    const evidencePath =
                      row.kind === 'score' ? row.score.candidate_field_path : undefined;
                    const reasoning =
                      row.kind === 'score'
                        ? row.score.reason
                        : row.requirement.evidence?.[0]?.text_excerpt || row.requirement.text;

                    return (
                      <tr key={idx} className="hover:bg-slate-800/30 transition-colors">
                        <td className="px-4 py-3 font-medium text-white max-w-xs">{text}</td>
                        <td className="px-4 py-3">
                          <span className="px-2 py-0.5 rounded text-xs bg-slate-800 text-slate-300 font-mono">
                            {kind}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`text-xs font-semibold ${
                              priority === 'REQUIRED' ? 'text-amber-400' : 'text-slate-400'
                            }`}
                          >
                            {priority}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          {row.kind === 'score' ? (
                            getEvaluationBadge(row.score.evaluation)
                          ) : (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-slate-700 text-slate-300">
                              Not scored
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-300">
                          <div>{reasoning}</div>
                          {evidencePath && (
                            <div className="text-[11px] text-blue-400/80 font-mono mt-0.5">
                              ref: {evidencePath}
                            </div>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Full Job Description */}
          <div>
            <h3 className="text-base font-semibold text-white mb-2">Original Job Description</h3>
            <div className="bg-slate-950 p-4 rounded-xl border border-slate-800 text-sm text-slate-300 whitespace-pre-line max-h-56 overflow-y-auto leading-relaxed font-sans">
              {job.description_text || job.description_raw || 'No description available'}
            </div>
          </div>
        </div>

        {/* Footer Actions */}
        <div className="p-4 sm:p-6 border-t border-slate-800 bg-slate-900/90 flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <a
              href={job.url || job.canonical_url || '#'}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
            >
              <ExternalLink className="w-4 h-4" />
              Source Posting
            </a>
          </div>

          <div className="flex items-center gap-2">
            {displayStatus !== 'REJECTED' && (
              <button
                onClick={() => onReject(job.id)}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium bg-rose-500/10 text-rose-400 hover:bg-rose-500/20 border border-rose-500/20 transition-colors cursor-pointer"
              >
                <ThumbsDown className="w-4 h-4" />
                Reject
              </button>
            )}

            {displayStatus !== 'READY' && !isHardVeto && (
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
              disabled={isHardVeto || displayStatus === 'APPLIED'}
              className={`inline-flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-semibold transition-all cursor-pointer ${
                displayStatus === 'APPLIED' || isHardVeto
                  ? 'bg-slate-800 text-slate-500 cursor-not-allowed'
                  : 'bg-blue-600 hover:bg-blue-500 text-white shadow-lg shadow-blue-600/30'
              }`}
            >
              <Send className="w-4 h-4" />
              {displayStatus === 'APPLIED'
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

export default JobDetailModal;