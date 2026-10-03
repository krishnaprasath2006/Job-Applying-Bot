import React, { useState } from 'react';
import {
  Search,
  Plus,
  SlidersHorizontal,
  Briefcase,
  MapPin,
  DollarSign,
  Sparkles,
  ExternalLink,
  ChevronRight,
  ShieldAlert,
  ShieldCheck,
  Send,
  ThumbsUp,
  ThumbsDown,
} from 'lucide-react';
import type { Job } from '../types/index.js';

interface JobDiscoveryTabProps {
  jobs: Job[];
  onSelectJob: (job: Job) => void;
  onAcceptJob: (jobId: string) => void;
  onRejectJob: (jobId: string) => void;
  onApplyJob: (jobId: string) => void;
  onIngestJob: (newJob: Partial<Job>) => Promise<void>;
  dryRun: boolean;
}

export const JobDiscoveryTab: React.FC<JobDiscoveryTabProps> = ({
  jobs,
  onSelectJob,
  onAcceptJob,
  onRejectJob,
  onApplyJob,
  onIngestJob,
  dryRun,
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [remoteOnly, setRemoteOnly] = useState(false);
  const [easyApplyOnly, setEasyApplyOnly] = useState(false);
  const [showIngestModal, setShowIngestModal] = useState(false);

  // Ingestion form state
  const [title, setTitle] = useState('');
  const [company, setCompany] = useState('');
  const [location, setLocation] = useState('San Francisco, CA');
  const [remoteType, setRemoteType] = useState<'Remote' | 'Hybrid' | 'On-site'>('Remote');
  const [salaryRange, setSalaryRange] = useState('$150,000 - $180,000');
  const [easyApply, setEasyApply] = useState(true);
  const [description, setDescription] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleIngestSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || !description.trim()) return;

    setIsSubmitting(true);
    try {
      await onIngestJob({
        title,
        company,
        location,
        remoteType,
        salaryRange,
        easyApply,
        description,
      });
      setShowIngestModal(false);
      setTitle('');
      setCompany('');
      setDescription('');
    } finally {
      setIsSubmitting(false);
    }
  };

  const loadPresetJob = (preset: 'fintech' | 'startup' | 'veto') => {
    if (preset === 'fintech') {
      setTitle('Lead Backend Engineer - Payments Core');
      setCompany('FinTech Scaling Co');
      setLocation('New York, NY (Remote)');
      setRemoteType('Remote');
      setSalaryRange('$175,000 - $205,000');
      setEasyApply(true);
      setDescription(`We are hiring a Lead Backend Engineer to build resilient distributed payment rails.
Requirements:
- 5+ years of software engineering experience in backend systems
- Hands-on mastery of Node.js, TypeScript, and Python
- Deep knowledge of PostgreSQL, Redis caching, and Docker
- Strong background in high-concurrency microservices
- Must be authorized to work in the US (No visa sponsorship provided)`);
    } else if (preset === 'startup') {
      setTitle('Frontend Platform Architect (React/Next.js)');
      setCompany('Aura Design Systems');
      setLocation('San Francisco, CA');
      setRemoteType('Hybrid');
      setSalaryRange('$160,000 - $185,000');
      setEasyApply(true);
      setDescription(`Seeking a Frontend Architect to create our design system and next-generation UI component library.
Requirements:
- 4+ years building production applications with React, TypeScript, and Tailwind CSS
- Demonstrated experience in web performance, accessibility, and E2E testing
- Degree in Computer Science or related degree preferred`);
    } else {
      setTitle('Principal Cloud Security Architect (Active TS/SCI Clearance)');
      setCompany('GovDefense Aerospace');
      setLocation('Washington, DC');
      setRemoteType('On-site');
      setSalaryRange('$220,000 - $260,000');
      setEasyApply(false);
      setDescription(`Requires active Top Secret TS/SCI Security Clearance and minimum 10+ years experience in defense infrastructure, C++, and hardware security modules. Strict US Citizenship & Clearance required.`);
    }
  };

  // Filter jobs
  const filteredJobs = jobs.filter((job) => {
    const matchesSearch =
      job.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      job.company.toLowerCase().includes(searchQuery.toLowerCase()) ||
      job.description.toLowerCase().includes(searchQuery.toLowerCase());

    const matchesStatus = statusFilter === 'ALL' || job.status === statusFilter;
    const matchesRemote = !remoteOnly || job.remoteType === 'Remote';
    const matchesEasyApply = !easyApplyOnly || job.easyApply;

    return matchesSearch && matchesStatus && matchesRemote && matchesEasyApply;
  });

  return (
    <div className="space-y-6">
      {/* Search & Actions Bar */}
      <div className="flex flex-col md:flex-row gap-4 items-stretch md:items-center justify-between">
        <div className="flex-1 relative">
          <Search className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            type="text"
            placeholder="Search by title, company, skills (e.g. React, Python, Node)..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-slate-900 border border-slate-800 rounded-xl pl-10 pr-4 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-hidden focus:border-blue-500 transition-colors"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Status Filter */}
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-sm text-slate-300 focus:outline-hidden focus:border-blue-500"
          >
            <option value="ALL">All Statuses</option>
            <option value="DISCOVERED">Discovered</option>
            <option value="IN_REVIEW">In Review</option>
            <option value="ACCEPTED">Accepted</option>
            <option value="APPLIED">Applied</option>
            <option value="REJECTED">Rejected</option>
          </select>

          {/* Quick Filters */}
          <button
            onClick={() => setRemoteOnly(!remoteOnly)}
            className={`px-3 py-2 rounded-xl text-xs font-medium border transition-colors cursor-pointer ${
              remoteOnly
                ? 'bg-blue-500/20 text-blue-300 border-blue-500/40'
                : 'bg-slate-900 text-slate-400 border-slate-800 hover:text-white'
            }`}
          >
            Remote Only
          </button>

          <button
            onClick={() => setEasyApplyOnly(!easyApplyOnly)}
            className={`px-3 py-2 rounded-xl text-xs font-medium border transition-colors cursor-pointer ${
              easyApplyOnly
                ? 'bg-blue-500/20 text-blue-300 border-blue-500/40'
                : 'bg-slate-900 text-slate-400 border-slate-800 hover:text-white'
            }`}
          >
            Easy Apply Only
          </button>

          {/* Ingest Job Modal Trigger */}
          <button
            onClick={() => setShowIngestModal(true)}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-semibold bg-blue-600 hover:bg-blue-500 text-white shadow-md shadow-blue-500/20 transition-all cursor-pointer"
          >
            <Plus className="w-4 h-4" />
            <span>Ingest Job</span>
          </button>
        </div>
      </div>

      {/* Ingest Job Modal */}
      {showIngestModal && (
        <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-xs flex items-center justify-center p-4 overflow-y-auto">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-2xl w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2">
                <Sparkles className="w-5 h-5 text-blue-400" />
                <h3 className="text-lg font-bold text-white">Ingest New Job Posting</h3>
              </div>
              <button
                onClick={() => setShowIngestModal(false)}
                className="text-slate-400 hover:text-white"
              >
                ✕
              </button>
            </div>

            {/* Quick Presets */}
            <div className="flex items-center gap-2 text-xs text-slate-400">
              <span>Load sample posting:</span>
              <button
                type="button"
                onClick={() => loadPresetJob('fintech')}
                className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-blue-400"
              >
                FinTech Backend (High Match)
              </button>
              <button
                type="button"
                onClick={() => loadPresetJob('startup')}
                className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-emerald-400"
              >
                Frontend Architect
              </button>
              <button
                type="button"
                onClick={() => loadPresetJob('veto')}
                className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-rose-400"
              >
                Clearance Job (Hard Veto)
              </button>
            </div>

            <form onSubmit={handleIngestSubmit} className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-400 mb-1">
                    Job Title *
                  </label>
                  <input
                    type="text"
                    required
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="e.g. Senior Full Stack Engineer"
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-hidden"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-400 mb-1">
                    Company Name
                  </label>
                  <input
                    type="text"
                    value={company}
                    onChange={(e) => setCompany(e.target.value)}
                    placeholder="e.g. Stripe Partner Co"
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-hidden"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-400 mb-1">
                    Location
                  </label>
                  <input
                    type="text"
                    value={location}
                    onChange={(e) => setLocation(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-hidden"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-400 mb-1">
                    Workplace Type
                  </label>
                  <select
                    value={remoteType}
                    onChange={(e) => setRemoteType(e.target.value as any)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-hidden"
                  >
                    <option value="Remote">Remote</option>
                    <option value="Hybrid">Hybrid</option>
                    <option value="On-site">On-site</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-400 mb-1">
                    Salary Range
                  </label>
                  <input
                    type="text"
                    value={salaryRange}
                    onChange={(e) => setSalaryRange(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-hidden"
                  />
                </div>
              </div>

              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="easyApplyCheckbox"
                  checked={easyApply}
                  onChange={(e) => setEasyApply(e.target.checked)}
                  className="rounded border-slate-700 bg-slate-900 text-blue-600 focus:ring-0"
                />
                <label htmlFor="easyApplyCheckbox" className="text-xs text-slate-300">
                  Tagged with LinkedIn Easy Apply
                </label>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-400 mb-1">
                  Full Job Description & Requirements *
                </label>
                <textarea
                  rows={6}
                  required
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Paste verbatim job posting or requirements here..."
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg p-3 text-sm text-white focus:border-blue-500 focus:outline-hidden font-mono"
                />
                <p className="text-[11px] text-slate-500 mt-1">
                  The bot will automatically parse requirements, evaluate the hard gate (years,
                  sponsorship), and score against your candidate profile.
                </p>
              </div>

              <div className="flex justify-end gap-2 pt-2 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setShowIngestModal(false)}
                  className="px-4 py-2 rounded-lg text-sm text-slate-400 hover:text-white"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-5 py-2 rounded-lg text-sm font-semibold bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50"
                >
                  {isSubmitting ? 'Analyzing & Scoring...' : 'Run Extraction & Score'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Jobs Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {filteredJobs.length === 0 ? (
          <div className="col-span-full p-12 text-center bg-slate-900/50 rounded-2xl border border-slate-800">
            <Briefcase className="w-12 h-12 text-slate-600 mx-auto mb-3" />
            <h3 className="text-lg font-semibold text-white">No job postings found</h3>
            <p className="text-sm text-slate-400 mt-1">
              Try adjusting your search criteria or click &quot;Ingest Job&quot; to add a new
              posting.
            </p>
          </div>
        ) : (
          filteredJobs.map((job) => {
            const isHardVeto = job.matchResult.gate.status === 'FAIL';
            const isStrong = job.matchResult.decision === 'STRONG_MATCH';

            return (
              <div
                key={job.id}
                className="bg-slate-900/90 border border-slate-800 hover:border-slate-700 rounded-2xl p-5 flex flex-col justify-between transition-all hover:shadow-lg hover:shadow-black/40"
              >
                <div>
                  {/* Top Badges */}
                  <div className="flex items-center justify-between gap-2 mb-3">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span
                        className={`text-xs px-2.5 py-0.5 rounded-full font-bold border ${
                          isHardVeto
                            ? 'bg-rose-500/10 text-rose-400 border-rose-500/20'
                            : isStrong
                            ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                            : 'bg-blue-500/10 text-blue-400 border-blue-500/20'
                        }`}
                      >
                        {isHardVeto
                          ? 'HARD GATE VETO'
                          : `${job.matchResult.overallScore}% MATCH`}
                      </span>

                      {job.easyApply && (
                        <span className="text-xs px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 font-medium">
                          Easy Apply
                        </span>
                      )}

                      <span
                        className={`text-xs px-2 py-0.5 rounded font-mono ${
                          job.status === 'ACCEPTED'
                            ? 'bg-emerald-500/20 text-emerald-300'
                            : job.status === 'APPLIED'
                            ? 'bg-purple-500/20 text-purple-300'
                            : job.status === 'REJECTED'
                            ? 'bg-rose-500/20 text-rose-300'
                            : 'bg-slate-800 text-slate-400'
                        }`}
                      >
                        {job.status}
                      </span>
                    </div>

                    <div className="flex items-center gap-1 text-xs">
                      {isHardVeto ? (
                        <span className="flex items-center gap-1 text-rose-400 font-semibold">
                          <ShieldAlert className="w-3.5 h-3.5" /> Vetoed
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 text-emerald-400 font-semibold">
                          <ShieldCheck className="w-3.5 h-3.5" /> Gate Passed
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Title & Company */}
                  <h3 className="text-base font-bold text-white hover:text-blue-400 transition-colors cursor-pointer" onClick={() => onSelectJob(job)}>
                    {job.title}
                  </h3>
                  <div className="flex items-center gap-3 text-xs text-slate-400 mt-1 flex-wrap">
                    <span className="font-semibold text-slate-300">{job.company}</span>
                    <span>•</span>
                    <span className="flex items-center gap-1">
                      <MapPin className="w-3 h-3 text-slate-500" />
                      {job.location} ({job.remoteType})
                    </span>
                    <span>•</span>
                    <span className="text-emerald-400 font-medium flex items-center gap-0.5">
                      <DollarSign className="w-3 h-3" />
                      {job.salaryRange}
                    </span>
                  </div>

                  {/* Veto Reason or Summary */}
                  {isHardVeto ? (
                    <div className="mt-3 p-2.5 rounded-lg bg-rose-950/40 border border-rose-900/40 text-xs text-rose-300">
                      {job.matchResult.gate.reasons[0] || 'Disqualified by hard gate rule.'}
                    </div>
                  ) : (
                    <p className="mt-2.5 text-xs text-slate-300 line-clamp-2 leading-relaxed">
                      {job.matchResult.summary}
                    </p>
                  )}

                  {/* Requirements chips */}
                  <div className="flex flex-wrap gap-1.5 mt-3">
                    {job.extractedRequirements.slice(0, 3).map((req) => (
                      <span
                        key={req.id}
                        className="text-[11px] px-2 py-0.5 rounded bg-slate-950 border border-slate-800 text-slate-300 max-w-[220px] truncate"
                      >
                        {req.text}
                      </span>
                    ))}
                    {job.extractedRequirements.length > 3 && (
                      <span className="text-[11px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">
                        +{job.extractedRequirements.length - 3} more
                      </span>
                    )}
                  </div>
                </div>

                {/* Footer Buttons */}
                <div className="flex items-center justify-between pt-4 mt-4 border-t border-slate-800/80 gap-2">
                  <button
                    onClick={() => onSelectJob(job)}
                    className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1 font-medium cursor-pointer"
                  >
                    <span>Explain Match</span>
                    <ChevronRight className="w-3.5 h-3.5" />
                  </button>

                  <div className="flex items-center gap-2">
                    {job.status !== 'REJECTED' && (
                      <button
                        title="Reject Job"
                        onClick={() => onRejectJob(job.id)}
                        className="p-1.5 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 transition-colors cursor-pointer"
                      >
                        <ThumbsDown className="w-4 h-4" />
                      </button>
                    )}

                    {job.status !== 'ACCEPTED' && !isHardVeto && (
                      <button
                        title="Accept to Review Queue"
                        onClick={() => onAcceptJob(job.id)}
                        className="p-1.5 rounded-lg text-slate-400 hover:text-emerald-400 hover:bg-emerald-500/10 transition-colors cursor-pointer"
                      >
                        <ThumbsUp className="w-4 h-4" />
                      </button>
                    )}

                    <button
                      onClick={() => onApplyJob(job.id)}
                      disabled={isHardVeto || job.status === 'APPLIED'}
                      className={`flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                        job.status === 'APPLIED'
                          ? 'bg-slate-800 text-slate-500 cursor-not-allowed'
                          : isHardVeto
                          ? 'bg-slate-800/80 text-slate-600 cursor-not-allowed'
                          : 'bg-blue-600 hover:bg-blue-500 text-white'
                      }`}
                    >
                      <Send className="w-3 h-3" />
                      {job.status === 'APPLIED'
                        ? 'Applied'
                        : dryRun
                        ? 'Dry Run'
                        : 'Apply'}
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
