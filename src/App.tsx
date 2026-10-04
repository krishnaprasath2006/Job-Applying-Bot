import React, { useState, useEffect, useCallback } from 'react';
import { Navbar, TabType } from './components/Navbar.js';
import { StatusBanner } from './components/StatusBanner.js';
import { JobDiscoveryTab } from './components/JobDiscoveryTab.js';
import { ReviewQueueTab } from './components/ReviewQueueTab.js';
import { CandidateProfileTab } from './components/CandidateProfileTab.js';
import { ResumeVaultTab } from './components/ResumeVaultTab.js';
import { QuestionsEngineTab } from './components/QuestionsEngineTab.js';
import { SafetyGuardrailsTab } from './components/SafetyGuardrailsTab.js';
import { HuggingFaceAITab } from './components/HuggingFaceAITab.js';
import { JobDetailModal } from './components/JobDetailModal.js';
import type { Job, CandidateProfile, Resume, SafetyReport, MatchResult } from './types/api.js';
import { API, isApiErrorCode } from './lib/api/index.js';

export function App() {
  const [activeTab, setActiveTab] = useState<TabType>('jobs');
  const [jobs, setJobs] = useState<Job[]>([]);
  const [profile, setProfile] = useState<CandidateProfile | null>(null);
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [safety, setSafety] = useState<SafetyReport | null>(null);
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [selectedMatch, setSelectedMatch] = useState<MatchResult | null>(null);
  // Resume selection is client-side only: the backend has no "active" concept.
  const [activeResumeId, setActiveResumeId] = useState<string | null>(null);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' | 'info' } | null>(null);
  const [loading, setLoading] = useState(false);

  const showToast = useCallback((message: string, type: 'success' | 'error' | 'info' = 'success') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 4000);
  }, []);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [jobsRes, profileRes, resumesRes, statusRes] = await Promise.all([
        API.jobs.list(),
        API.profile.get(),
        API.resumes.list(),
        API.status.status(),
      ]);

      setJobs(jobsRes.jobs || []);
      setProfile(profileRes.exists ? profileRes.profile : null);
      setResumes(resumesRes.resumes || []);
      setSafety(statusRes.safety);
    } catch (err) {
      console.error('Failed to load system data:', err);
      showToast('Error loading application data', 'error');
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleSelectJob = useCallback(async (job: Job) => {
    setSelectedJob(job);
    setSelectedMatch(null);
    try {
      const res = await API.jobs.match(job.id, {});
      setSelectedMatch(res.result ?? null);
    } catch (err) {
      // A job that has not been analysed yet has no match; the modal renders unscored.
      setSelectedMatch(null);
    }
  }, []);

  const handleAcceptJob = useCallback(async (jobId: string) => {
    try {
      const res = await API.jobs.resolveReview(jobId, 'Approved for application batch');
      setJobs(jobs.map(j => j.id === jobId ? { ...j, status: 'READY_FOR_APPLICATION' } : j));
      if (selectedJob?.id === jobId) setSelectedJob({ ...selectedJob, status: 'READY_FOR_APPLICATION' });
      showToast('Job approved and added to Review Queue');
    } catch (err) {
      if (err instanceof Error && 'code' in err && (err as any).code === 'SUBMISSION_DISABLED') {
        showToast('Review actions require safety policy approval', 'error');
      } else {
        showToast('Failed to accept job', 'error');
      }
    }
  }, [jobs, selectedJob, showToast]);

  const handleRejectJob = useCallback(async (jobId: string) => {
    try {
      await API.jobs.resolveReview(jobId, 'Declined by candidate');
      setJobs(jobs.map(j => j.id === jobId ? { ...j, status: 'REJECTED' } : j));
      if (selectedJob?.id === jobId) setSelectedJob({ ...selectedJob, status: 'REJECTED' });
      showToast('Job marked as rejected');
    } catch (err) {
      if (err instanceof Error && 'code' in err && (err as any).code === 'SUBMISSION_DISABLED') {
        showToast('Review actions require safety policy approval', 'error');
      } else {
        showToast('Failed to reject job', 'error');
      }
    }
  }, [jobs, selectedJob, showToast]);

  const handleApplyJob = useCallback(async (jobId: string) => {
    try {
      const res = await API.jobs.apply(jobId);
      showToast(res.reason || 'Application submission is disabled by safety policy', 'error');
    } catch (err) {
      if (err instanceof Error && 'code' in err && (err as any).code === 'SUBMISSION_DISABLED') {
        showToast('Application submission is disabled by safety policy (dry_run/safe_mode)', 'error');
      } else {
        showToast('Application submission is disabled', 'error');
      }
    }
  }, [showToast]);

  const handleIngestJob = useCallback(async (newJob: { html: string; source: string; page_url: string; source_path: string }) => {
    try {
      const res = await API.jobs.ingest(newJob);
      setJobs([res.job, ...jobs]);
      showToast('New job posting parsed and stored!');
    } catch (err) {
      console.error(err);
      showToast('Failed to ingest job', 'error');
    }
  }, [jobs, showToast]);

  const handleUpdateProfile = useCallback(async (updated: CandidateProfile) => {
    try {
      await API.profile.validate();
      const [profileRes, jobsRes] = await Promise.all([
        API.profile.get(),
        API.jobs.list(),
      ]);
      setProfile(profileRes.exists ? profileRes.profile : null);
      setJobs(jobsRes.jobs || []);
      showToast('Candidate facts validated; matches recalculated');
    } catch (err) {
      console.error(err);
      showToast('Failed to update candidate facts', 'error');
    }
  }, [showToast]);

  const handleValidateProfile = useCallback(async () => {
    try {
      const res = await API.profile.validate();
      return res;
    } catch (err) {
      console.error(err);
      throw err;
    }
  }, []);

  const handleActivateResume = useCallback(async (id: string) => {
    try {
      setActiveResumeId(id);
      showToast('Active resume variant updated (local)');
    } catch (err) {
      showToast('Failed to activate resume', 'error');
    }
  }, [showToast]);

  const handleAddResume = useCallback(async (newResume: { name: string; targetRole: string; format: 'PDF' | 'DOCX' | 'TXT' | 'MD'; contentSnippet: string }) => {
    try {
      showToast('Resume ingest requires server-side file path. Use CLI or API directly.', 'info');
    } catch (err) {
      showToast('Failed to add resume variant', 'error');
    }
  }, [showToast]);

const handleUpdateSafety = useCallback(async (updates: Partial<SafetyReport>) => {
    showToast('Safety settings are server-controlled and cannot be modified via UI', 'info');
  }, [showToast]);

  const reviewBadgeCount = jobs.filter(j => j.status === 'READY_FOR_APPLICATION').length;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      <Navbar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        reviewCount={reviewBadgeCount}
        safetyMode={safety?.safe_mode ?? true}
        dryRun={safety?.dry_run ?? true}
      />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 flex-1 w-full">
        <StatusBanner
          profile={profile}
          safety={safety}
          resumes={resumes}
        />

        {activeTab === 'jobs' && (
          <JobDiscoveryTab
            jobs={jobs}
            onSelectJob={handleSelectJob}
            onAcceptJob={handleAcceptJob}
            onRejectJob={handleRejectJob}
            onApplyJob={handleApplyJob}
            onIngestJob={handleIngestJob}
            dryRun={safety?.dry_run ?? true}
          />
        )}

        {activeTab === 'review' && (
          <ReviewQueueTab
            jobs={jobs}
            onSelectJob={handleSelectJob}
            onAcceptJob={handleAcceptJob}
            onRejectJob={handleRejectJob}
            onApplyJob={handleApplyJob}
            dryRun={safety?.dry_run ?? true}
          />
        )}

        {activeTab === 'profile' && (
          <CandidateProfileTab
            profile={profile}
            onUpdateProfile={handleUpdateProfile}
            onValidateProfile={handleValidateProfile}
          />
        )}

        {activeTab === 'resumes' && (
          <ResumeVaultTab
            resumes={resumes}
            activeResumeId={activeResumeId}
            onActivateResume={handleActivateResume}
            onAddResume={handleAddResume}
          />
        )}

        {activeTab === 'questions' && (
          <QuestionsEngineTab />
        )}

        {activeTab === 'ai' && (
          <HuggingFaceAITab safety={safety} />
        )}

        {activeTab === 'safety' && (
          <SafetyGuardrailsTab
            safety={safety}
onUpdateSafety={handleUpdateSafety}
          />
        )}
      </main>

      <JobDetailModal
        job={selectedJob}
        matchResult={selectedMatch}
        onClose={() => setSelectedJob(null)}
        onAccept={handleAcceptJob}
        onReject={handleRejectJob}
        onApply={handleApplyJob}
        dryRun={safety?.dry_run ?? true}
      />

      {toast && (
        <div className="fixed bottom-6 right-6 z-50 animate-bounce">
          <div
            className={`px-4 py-2.5 rounded-xl text-sm font-semibold shadow-2xl border flex items-center gap-2 ${
              toast.type === 'error'
                ? 'bg-rose-950 border-rose-700 text-rose-200'
                : 'bg-emerald-950 border-emerald-700 text-emerald-200'
            }`}
          >
            <span>{toast.message}</span>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;