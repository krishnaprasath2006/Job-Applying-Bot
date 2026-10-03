import React, { useState } from 'react';
import {
  Layers,
  CheckCircle2,
  XCircle,
  Clock,
  Play,
  Briefcase,
  MapPin,
  DollarSign,
  AlertCircle,
  FileCheck,
  Send,
  Eye,
} from 'lucide-react';
import type { Job } from '../types/index.js';

interface ReviewQueueTabProps {
  jobs: Job[];
  onSelectJob: (job: Job) => void;
  onAcceptJob: (jobId: string) => void;
  onRejectJob: (jobId: string) => void;
  onApplyJob: (jobId: string) => void;
  dryRun: boolean;
}

export const ReviewQueueTab: React.FC<ReviewQueueTabProps> = ({
  jobs,
  onSelectJob,
  onAcceptJob,
  onRejectJob,
  onApplyJob,
  dryRun,
}) => {
  const [activeSubTab, setActiveSubTab] = useState<'pending' | 'accepted' | 'applied' | 'rejected'>('accepted');

  const pendingJobs = jobs.filter((j) => j.status === 'IN_REVIEW' || j.status === 'DISCOVERED');
  const acceptedJobs = jobs.filter((j) => j.status === 'ACCEPTED');
  const appliedJobs = jobs.filter((j) => j.status === 'APPLIED');
  const rejectedJobs = jobs.filter((j) => j.status === 'REJECTED');

  const handleApplyAllAccepted = async () => {
    for (const job of acceptedJobs) {
      if (job.matchResult.gate.status === 'PASS') {
        onApplyJob(job.id);
      }
    }
  };

  return (
    <div className="space-y-6">
      {/* Top Banner */}
      <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <Layers className="w-5 h-5 text-blue-400" />
            <span>Human-In-The-Loop Review & Execution Queue</span>
          </h2>
          <p className="text-sm text-slate-400 mt-1">
            Every application requires human sign-off prior to submission, honoring Phase 2 safety
            invariants.
          </p>
        </div>

        {acceptedJobs.length > 0 && (
          <button
            onClick={handleApplyAllAccepted}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold bg-emerald-600 hover:bg-emerald-500 text-white shadow-lg shadow-emerald-600/20 transition-all cursor-pointer"
          >
            <Play className="w-4 h-4" />
            <span>
              Batch {dryRun ? 'Simulate Apply' : 'Submit'} ({acceptedJobs.length} Jobs)
            </span>
          </button>
        )}
      </div>

      {/* Sub Tabs */}
      <div className="flex border-b border-slate-800 space-x-2">
        <button
          onClick={() => setActiveSubTab('accepted')}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-all cursor-pointer ${
            activeSubTab === 'accepted'
              ? 'border-emerald-500 text-emerald-400 bg-emerald-500/5'
              : 'border-transparent text-slate-400 hover:text-white'
          }`}
        >
          <CheckCircle2 className="w-4 h-4 text-emerald-400" />
          <span>Approved & Ready to Apply</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 font-mono">
            {acceptedJobs.length}
          </span>
        </button>

        <button
          onClick={() => setActiveSubTab('pending')}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-all cursor-pointer ${
            activeSubTab === 'pending'
              ? 'border-blue-500 text-blue-400 bg-blue-500/5'
              : 'border-transparent text-slate-400 hover:text-white'
          }`}
        >
          <Clock className="w-4 h-4 text-blue-400" />
          <span>Needs Human Review</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 font-mono">
            {pendingJobs.length}
          </span>
        </button>

        <button
          onClick={() => setActiveSubTab('applied')}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-all cursor-pointer ${
            activeSubTab === 'applied'
              ? 'border-purple-500 text-purple-400 bg-purple-500/5'
              : 'border-transparent text-slate-400 hover:text-white'
          }`}
        >
          <Send className="w-4 h-4 text-purple-400" />
          <span>Applied Log</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 font-mono">
            {appliedJobs.length}
          </span>
        </button>

        <button
          onClick={() => setActiveSubTab('rejected')}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-all cursor-pointer ${
            activeSubTab === 'rejected'
              ? 'border-rose-500 text-rose-400 bg-rose-500/5'
              : 'border-transparent text-slate-400 hover:text-white'
          }`}
        >
          <XCircle className="w-4 h-4 text-rose-400" />
          <span>Archived / Rejected</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 font-mono">
            {rejectedJobs.length}
          </span>
        </button>
      </div>

      {/* List Content */}
      <div className="space-y-3">
        {activeSubTab === 'accepted' && (
          acceptedJobs.length === 0 ? (
            <div className="p-12 text-center bg-slate-900/50 rounded-2xl border border-slate-800 text-slate-400">
              No approved jobs yet. Go to Job Matching or &quot;Needs Human Review&quot; to approve roles.
            </div>
          ) : (
            acceptedJobs.map((job) => (
              <div
                key={job.id}
                className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 hover:border-slate-700 transition-colors"
              >
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                      {job.matchResult.overallScore}% MATCH
                    </span>
                    <h3 className="font-bold text-white hover:text-blue-400 cursor-pointer" onClick={() => onSelectJob(job)}>
                      {job.title}
                    </h3>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-slate-400">
                    <span className="font-semibold text-slate-300">{job.company}</span>
                    <span>•</span>
                    <span>{job.location} ({job.remoteType})</span>
                    <span>•</span>
                    <span className="text-emerald-400">{job.salaryRange}</span>
                  </div>
                  {job.reviewNotes && (
                    <div className="text-xs text-slate-300 bg-slate-950 px-2.5 py-1 rounded border border-slate-800 mt-1">
                      Note: {job.reviewNotes}
                    </div>
                  )}
                </div>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() => onSelectJob(job)}
                    className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 text-xs flex items-center gap-1 cursor-pointer"
                  >
                    <Eye className="w-4 h-4" />
                    <span>Inspect</span>
                  </button>
                  <button
                    onClick={() => onRejectJob(job.id)}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium text-rose-400 hover:bg-rose-500/10 border border-rose-500/20 cursor-pointer"
                  >
                    Reject
                  </button>
                  <button
                    onClick={() => onApplyJob(job.id)}
                    className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-semibold bg-blue-600 hover:bg-blue-500 text-white cursor-pointer"
                  >
                    <Send className="w-3.5 h-3.5" />
                    <span>{dryRun ? 'Simulate Apply' : 'Submit Apply'}</span>
                  </button>
                </div>
              </div>
            ))
          )
        )}

        {activeSubTab === 'pending' && (
          pendingJobs.length === 0 ? (
            <div className="p-12 text-center bg-slate-900/50 rounded-2xl border border-slate-800 text-slate-400">
              No pending jobs waiting for human review.
            </div>
          ) : (
            pendingJobs.map((job) => (
              <div
                key={job.id}
                className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 hover:border-slate-700 transition-colors"
              >
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20">
                      {job.matchResult.overallScore}% FIT
                    </span>
                    <h3 className="font-bold text-white hover:text-blue-400 cursor-pointer" onClick={() => onSelectJob(job)}>
                      {job.title}
                    </h3>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-slate-400">
                    <span className="font-semibold text-slate-300">{job.company}</span>
                    <span>•</span>
                    <span>{job.location}</span>
                  </div>
                  <p className="text-xs text-slate-400 line-clamp-1">{job.matchResult.summary}</p>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() => onSelectJob(job)}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium text-slate-300 hover:bg-slate-800 border border-slate-700 cursor-pointer"
                  >
                    Details
                  </button>
                  <button
                    onClick={() => onRejectJob(job.id)}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium text-rose-400 hover:bg-rose-500/10 border border-rose-500/20 cursor-pointer"
                  >
                    Decline
                  </button>
                  <button
                    onClick={() => onAcceptJob(job.id)}
                    disabled={job.matchResult.gate.status === 'FAIL'}
                    className="px-4 py-1.5 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white disabled:opacity-40 cursor-pointer"
                  >
                    Approve
                  </button>
                </div>
              </div>
            ))
          )
        )}

        {activeSubTab === 'applied' && (
          appliedJobs.length === 0 ? (
            <div className="p-12 text-center bg-slate-900/50 rounded-2xl border border-slate-800 text-slate-400">
              No applications in log. Apply to an approved job to see submission audit.
            </div>
          ) : (
            appliedJobs.map((job) => (
              <div
                key={job.id}
                className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4"
              >
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold px-2 py-0.5 rounded bg-purple-500/10 text-purple-400 border border-purple-500/20">
                      {job.applicationMode === 'DRY_RUN_SIMULATED' ? 'DRY-RUN SIMULATED' : 'LIVE APPLIED'}
                    </span>
                    <h3 className="font-bold text-white">{job.title}</h3>
                  </div>
                  <div className="text-xs text-slate-400">
                    {job.company} • Applied at {new Date(job.appliedAt || Date.now()).toLocaleString()}
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <span className="text-xs px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                    Form Answers Verified
                  </span>
                  <button
                    onClick={() => onSelectJob(job)}
                    className="px-3 py-1.5 rounded-lg text-xs text-slate-300 hover:bg-slate-800 border border-slate-700 cursor-pointer"
                  >
                    View Record
                  </button>
                </div>
              </div>
            ))
          )
        )}

        {activeSubTab === 'rejected' && (
          rejectedJobs.length === 0 ? (
            <div className="p-12 text-center bg-slate-900/50 rounded-2xl border border-slate-800 text-slate-400">
              No rejected jobs.
            </div>
          ) : (
            rejectedJobs.map((job) => (
              <div
                key={job.id}
                className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 flex items-center justify-between opacity-80"
              >
                <div>
                  <h3 className="font-semibold text-slate-300 line-through">{job.title}</h3>
                  <div className="text-xs text-slate-500">{job.company} • {job.location}</div>
                </div>
                <button
                  onClick={() => onAcceptJob(job.id)}
                  className="px-3 py-1.5 rounded-lg text-xs font-medium text-blue-400 hover:bg-blue-500/10 border border-blue-500/20 cursor-pointer"
                >
                  Restore to Queue
                </button>
              </div>
            ))
          )
        )}
      </div>
    </div>
  );
};
