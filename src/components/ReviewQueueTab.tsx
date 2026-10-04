import React, { useState, useEffect } from 'react';
import { ThumbsUp, ThumbsDown, CheckCircle, Briefcase } from 'lucide-react';
import type { Job, MatchResult, ReviewItem } from '../types/api.js';
import { jobApi } from '../lib/api/index.js';

interface ReviewQueueTabProps {
  jobs: Job[];
  /** Match results keyed by job id. Match is a separate resource, not a Job field. */
  matchResults?: Record<string, MatchResult>;
  onSelectJob: (job: Job) => void;
  onAcceptJob: (jobId: string) => void;
  onRejectJob: (jobId: string) => void;
  onApplyJob: (jobId: string) => void;
  dryRun: boolean;
}

const DECISION_BADGES: Record<ReviewItem['decision'], { label: string; className: string }> = {
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

/** Job statuses that belong in the human review queue. */
const REVIEW_STATUSES: ReadonlySet<Job['status']> = new Set([
  'ANALYSIS_PENDING',
  'ANALYZED',
  'MATCHED',
  'REVIEW_REQUIRED',
  'READY_FOR_APPLICATION',
]);

const STATUS_BADGES: Record<string, string> = {
  REJECTED: 'bg-rose-500/20 text-rose-300',
  APPLIED: 'bg-purple-500/20 text-purple-300',
  READY_FOR_APPLICATION: 'bg-emerald-500/20 text-emerald-300',
};

export const ReviewQueueTab: React.FC<ReviewQueueTabProps> = ({
  jobs,
  matchResults,
  onSelectJob,
  onAcceptJob,
  onRejectJob,
  onApplyJob,
  dryRun,
}) => {
  const [serverItems, setServerItems] = useState<ReviewItem[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    jobApi
      .getReviewQueue()
      .then((res) => {
        if (!cancelled) setServerItems(res.queue?.items ?? []);
      })
      .catch((err) => {
        console.error('Failed to load review queue:', err);
        if (!cancelled) setLoadFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Fall back to deriving rows from the job list when the queue endpoint is unavailable.
  const derivedItems: ReviewItem[] = jobs
    .filter((job) => REVIEW_STATUSES.has(job.status))
    .map((job) => {
      const match = matchResults?.[job.id];
      return {
        job_id: job.id,
        title: job.title,
        company: job.company,
        url: job.url,
        decision: match?.decision ?? 'REVIEW_REQUIRED',
        reasons: [],
        similarity_score: match?.similarity_score,
        matched_at: job.last_seen_at,
        status: job.status,
      };
    });

  const items = serverItems?.length ? serverItems : derivedItems;

  return (
    <div className="space-y-6">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6">
        <div className="flex items-center gap-2">
          <CheckCircle className="w-5 h-5 text-emerald-400" />
          <h2 className="text-xl font-bold text-white">Human Review Queue</h2>
        </div>
        <p className="text-sm text-slate-400 mt-1">
          Jobs requiring a human decision. Review matched requirements, resolve conflicts, and
          approve for application.
        </p>
        {loadFailed && (
          <p className="text-xs text-amber-300 mt-2">
            Could not reach the review queue endpoint; showing jobs derived from the job list.
          </p>
        )}
      </div>

      <div className="space-y-4">
        {items.length === 0 ? (
          <div className="p-12 text-center bg-slate-900/50 rounded-2xl border border-slate-800">
            <CheckCircle className="w-12 h-12 text-emerald-600 mx-auto mb-3" />
            <h3 className="text-lg font-semibold text-white">Review queue is empty</h3>
            <p className="text-sm text-slate-400 mt-1">
              No jobs currently require human review.
            </p>
          </div>
        ) : (
          items.map((item) => {
            const job = jobs.find((j) => j.id === item.job_id);
            const badge = DECISION_BADGES[item.decision] ?? DECISION_BADGES.REVIEW_REQUIRED;
            const isHardVeto = item.decision === 'HARD_MISMATCH';
            const canOpen = Boolean(job);

            return (
              <div
                key={item.job_id}
                className="bg-slate-900/90 border border-slate-800 hover:border-slate-700 rounded-2xl p-5 transition-all hover:shadow-lg hover:shadow-black/40"
              >
                <div className="flex items-center justify-between gap-2 mb-3 flex-wrap">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span
                      className={`text-xs px-2.5 py-0.5 rounded-full font-bold border ${badge.className}`}
                    >
                      {badge.label}
                    </span>
                    {item.reasons?.length > 0 && (
                      <span className="text-xs px-2 py-0.5 rounded bg-purple-500/10 text-purple-400 border border-purple-500/20 font-medium">
                        {item.reasons.length} Review Flag(s)
                      </span>
                    )}
                  </div>

                  {item.status && (
                    <span
                      className={`text-xs px-2 py-0.5 rounded font-mono ${
                        STATUS_BADGES[item.status] ?? 'bg-slate-800 text-slate-400'
                      }`}
                    >
                      {item.status}
                    </span>
                  )}
                </div>

                <h3
                  className={`text-base font-bold text-white ${
                    canOpen ? 'hover:text-blue-400 cursor-pointer transition-colors' : ''
                  }`}
                  onClick={() => job && onSelectJob(job)}
                >
                  {item.title}
                </h3>
                <div className="flex items-center gap-3 text-xs text-slate-400 mt-1 flex-wrap">
                  <span className="font-semibold text-slate-300">{item.company}</span>
                  <span>•</span>
                  <span>
                    Match:{' '}
                    {typeof item.similarity_score === 'number'
                      ? `${Math.round(item.similarity_score * 100)}%`
                      : 'N/A'}
                  </span>
                </div>

                {item.reasons?.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {item.reasons.map((reason, i) => (
                      <span
                        key={i}
                        className="text-xs px-2 py-0.5 rounded bg-purple-500/10 text-purple-400 border border-purple-500/20 font-mono"
                      >
                        {reason}
                      </span>
                    ))}
                  </div>
                )}

                <div className="flex items-center justify-between pt-4 mt-4 border-t border-slate-800/80 gap-2">
                  <button
                    onClick={() => job && onSelectJob(job)}
                    disabled={!canOpen}
                    className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1 font-medium disabled:text-slate-600 disabled:cursor-not-allowed"
                  >
                    <span>Explain Match</span>
                    <Briefcase className="w-3.5 h-3.5" />
                  </button>

                  <div className="flex items-center gap-2">
                    {item.status !== 'REJECTED' && (
                      <button
                        title="Reject Job"
                        onClick={() => onRejectJob(item.job_id)}
                        className="p-1.5 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 transition-colors cursor-pointer"
                      >
                        <ThumbsDown className="w-4 h-4" />
                      </button>
                    )}

                    {item.status !== 'READY_FOR_APPLICATION' && !isHardVeto && (
                      <button
                        title="Approve for application"
                        onClick={() => onAcceptJob(item.job_id)}
                        className="p-1.5 rounded-lg text-slate-400 hover:text-emerald-400 hover:bg-emerald-500/10 transition-colors cursor-pointer"
                      >
                        <ThumbsUp className="w-4 h-4" />
                      </button>
                    )}

                    <button
                      onClick={() => onApplyJob(item.job_id)}
                      disabled={isHardVeto || item.status === 'APPLIED'}
                      className={`flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                        item.status === 'APPLIED' || isHardVeto
                          ? 'bg-slate-800 text-slate-500 cursor-not-allowed'
                          : 'bg-blue-600 hover:bg-blue-500 text-white cursor-pointer'
                      }`}
                    >
                      <Briefcase className="w-3 h-3" />
                      {item.status === 'APPLIED' ? 'Applied' : dryRun ? 'Dry Run' : 'Apply'}
                    </button>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};

export default ReviewQueueTab;