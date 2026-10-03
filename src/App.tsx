import React, { useState, useEffect } from 'react';
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
import type { Job, CandidateProfile, ResumeVariant, SafetySettings } from './types/index.js';

export function App() {
  const [activeTab, setActiveTab] = useState<TabType>('jobs');
  const [jobs, setJobs] = useState<Job[]>([]);
  const [profile, setProfile] = useState<CandidateProfile | null>(null);
  const [resumes, setResumes] = useState<ResumeVariant[]>([]);
  const [safety, setSafety] = useState<SafetySettings | null>(null);
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' | 'info' } | null>(null);

  const showToast = (message: string, type: 'success' | 'error' | 'info' = 'success') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 4000);
  };

  const loadData = async () => {
    try {
      const [jobsRes, profileRes, resumesRes, safetyRes] = await Promise.all([
        fetch('/api/jobs').then(r => r.json()),
        fetch('/api/profile').then(r => r.json()),
        fetch('/api/resumes').then(r => r.json()),
        fetch('/api/safety').then(r => r.json()),
      ]);

      setJobs(jobsRes || []);
      setProfile(profileRes || null);
      setResumes(resumesRes || []);
      setSafety(safetyRes.settings || null);
    } catch (err) {
      console.error('Failed to load system data:', err);
      showToast('Error loading application data', 'error');
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleAcceptJob = async (jobId: string) => {
    try {
      const res = await fetch(`/api/jobs/${jobId}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision: 'ACCEPTED', notes: 'Approved for application batch' }),
      });
      if (res.ok) {
        const updated = await res.json();
        setJobs(jobs.map(j => j.id === jobId ? updated : j));
        if (selectedJob?.id === jobId) setSelectedJob(updated);
        showToast('Job approved and added to Review Queue');
      }
    } catch {
      showToast('Failed to accept job', 'error');
    }
  };

  const handleRejectJob = async (jobId: string) => {
    try {
      const res = await fetch(`/api/jobs/${jobId}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision: 'REJECTED', notes: 'Declined by candidate' }),
      });
      if (res.ok) {
        const updated = await res.json();
        setJobs(jobs.map(j => j.id === jobId ? updated : j));
        if (selectedJob?.id === jobId) setSelectedJob(updated);
        showToast('Job marked as rejected');
      }
    } catch {
      showToast('Failed to reject job', 'error');
    }
  };

  const handleApplyJob = async (jobId: string) => {
    try {
      const res = await fetch(`/api/jobs/${jobId}/apply`, {
        method: 'POST',
      });
      const data = await res.json();

      if (!res.ok) {
        showToast(data.error || 'Failed to submit application', 'error');
        return;
      }

      setJobs(jobs.map(j => j.id === jobId ? data.job : j));
      if (selectedJob?.id === jobId) setSelectedJob(data.job);
      if (safety) {
        setSafety({ ...safety, applicationsToday: safety.applicationsToday + 1 });
      }
      showToast(data.message || 'Application successfully processed!');
    } catch {
      showToast('Network error while applying', 'error');
    }
  };

  const handleIngestJob = async (newJob: Partial<Job>) => {
    try {
      const res = await fetch('/api/jobs/ingest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newJob),
      });
      if (res.ok) {
        const created = await res.json();
        setJobs([created, ...jobs]);
        showToast('New job posting parsed, verified, and scored!');
      } else {
        showToast('Failed to ingest job', 'error');
      }
    } catch {
      showToast('Error during job ingestion', 'error');
    }
  };

  const handleUpdateProfile = async (updated: CandidateProfile) => {
    try {
      const res = await fetch('/api/profile', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updated),
      });
      if (res.ok) {
        const data = await res.json();
        setProfile(data);
        // Refresh jobs since match scoring changes when facts change!
        const refreshedJobs = await fetch('/api/jobs').then(r => r.json());
        setJobs(refreshedJobs);
        showToast('Candidate facts updated & matches recalculated');
      }
    } catch {
      showToast('Failed to update candidate facts', 'error');
    }
  };

  const handleValidateProfile = async () => {
    const res = await fetch('/api/profile/validate', { method: 'POST' });
    return res.json();
  };

  const handleActivateResume = async (id: string) => {
    try {
      const res = await fetch(`/api/resumes/${id}/activate`, { method: 'POST' });
      if (res.ok) {
        setResumes(resumes.map(r => ({ ...r, isActive: r.id === id })));
        showToast('Active resume variant updated');
      }
    } catch {
      showToast('Failed to activate resume', 'error');
    }
  };

  const handleAddResume = async (newResume: Partial<ResumeVariant>) => {
    try {
      const res = await fetch('/api/resumes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newResume),
      });
      if (res.ok) {
        const data = await res.json();
        setResumes([...resumes, data]);
        showToast('Resume variant saved to vault');
      }
    } catch {
      showToast('Failed to add resume variant', 'error');
    }
  };

  const handleUpdateSafety = async (updates: Partial<SafetySettings>) => {
    try {
      const res = await fetch('/api/safety', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });
      if (res.ok) {
        const data = await res.json();
        setSafety(data.settings);
        showToast('Safety settings updated');
      }
    } catch {
      showToast('Failed to update safety policy', 'error');
    }
  };

  const handleResetCounter = async () => {
    try {
      const res = await fetch('/api/safety/reset-counter', { method: 'POST' });
      if (res.ok) {
        if (safety) setSafety({ ...safety, applicationsToday: 0 });
        showToast('Daily applications counter reset');
      }
    } catch {
      showToast('Failed to reset counter', 'error');
    }
  };

  const reviewBadgeCount = jobs.filter(j => j.status === 'ACCEPTED').length;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      <Navbar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        reviewCount={reviewBadgeCount}
        safetyMode={safety?.safeMode ?? true}
        dryRun={safety?.dryRun ?? true}
      />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 flex-1 w-full">
        <StatusBanner
          profile={profile}
          safety={safety}
          resumes={resumes}
        />

        {/* Tab View Routing */}
        {activeTab === 'jobs' && (
          <JobDiscoveryTab
            jobs={jobs}
            onSelectJob={setSelectedJob}
            onAcceptJob={handleAcceptJob}
            onRejectJob={handleRejectJob}
            onApplyJob={handleApplyJob}
            onIngestJob={handleIngestJob}
            dryRun={safety?.dryRun ?? true}
          />
        )}

        {activeTab === 'review' && (
          <ReviewQueueTab
            jobs={jobs}
            onSelectJob={setSelectedJob}
            onAcceptJob={handleAcceptJob}
            onRejectJob={handleRejectJob}
            onApplyJob={handleApplyJob}
            dryRun={safety?.dryRun ?? true}
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
            onActivateResume={handleActivateResume}
            onAddResume={handleAddResume}
          />
        )}

        {activeTab === 'questions' && (
          <QuestionsEngineTab />
        )}

        {activeTab === 'ai' && (
          <HuggingFaceAITab />
        )}

        {activeTab === 'safety' && (
          <SafetyGuardrailsTab
            safety={safety}
            onUpdateSafety={handleUpdateSafety}
            onResetCounter={handleResetCounter}
          />
        )}
      </main>

      {/* Detail & Evidence Modal */}
      <JobDetailModal
        job={selectedJob}
        onClose={() => setSelectedJob(null)}
        onAccept={handleAcceptJob}
        onReject={handleRejectJob}
        onApply={handleApplyJob}
        dryRun={safety?.dryRun ?? true}
      />

      {/* Floating Toast Notification */}
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
