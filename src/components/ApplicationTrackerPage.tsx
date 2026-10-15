import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { API, api } from '../lib/api/index';
import { X, CheckCircle, AlertTriangle, Calendar, ShieldCheck, Edit, Trash, CalendarX, CalendarPlus, Search, Plus, User, UserCheck, Info } from 'lucide-react';

type ApplicationStatus =
  | 'SAVED'
  | 'INTERESTED'
  | 'PREPARING'
  | 'APPLIED'
  | 'ASSESSMENT'
  | 'INTERVIEW'
  | 'OFFER'
  | 'REJECTED'
  | 'WITHDRAWN';

interface ApplicationSummary {
  id: string;
  job_id: string;
  status: ApplicationStatus;
  application_date: string | null;
  created_at: string;
  updated_at: string;
  next_followup: string | null;
  interviewer_name: string | null;
  interviewer_contact: string | null;
  notes: string | null;
  resume_id: string | null;
  cover_letter_draft_id: string | null;
  source_url: string | null;
  source_job_metadata: string | null;
  job: { id: string; title: string; company: string } | null;
}

export const ApplicationTrackerPage = () => {
  const [applications, setApplications] = useState<ApplicationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterStatus, setFilterStatus] = useState<ApplicationStatus | 'all'>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [view, setView] = useState<'board' | 'list'>('list');
  const [selectedApp, setSelectedApp] = useState<ApplicationSummary | null>(null);
  const [editingApp, setEditingApp] = useState(null as any);

  const showToast = (message: string, type: 'success' | 'error' = 'success') => {
    const toastDiv = document.createElement('div');
    toastDiv.className = `fixed bottom-6 right-6 z-50 animate-bounce ${type === 'success' ? 'bg-emerald-950 border-emerald-700 text-emerald-200' : 'bg-rose-950 border-rose-700 text-rose-200'}`;
    toastDiv.innerHTML = `<div className='px-4 py-2.5 rounded-xl text-sm font-semibold shadow-2xl border flex items-center gap-2'><span>${message}</span></div>`;
    document.body.appendChild(toastDiv);
    setTimeout(() => toastDiv.remove(), 4000);
  };

  const statusColor = (status: ApplicationStatus) => {
    const colors: Record<ApplicationStatus, string> = {
      SAVED: 'bg-slate-500/20 text-slate-400',
      INTERESTED: 'bg-blue-500/20 text-blue-300',
      PREPARING: 'bg-emerald-500/20 text-emerald-300',
      APPLIED: 'bg-purple-500/20 text-purple-300',
      ASSESSMENT: 'bg-amber-500/20 text-amber-300',
      INTERVIEW: 'bg-cyan-500/20 text-cyan-300',
      OFFER: 'bg-green-500/20 text-green-300',
      REJECTED: 'bg-rose-500/20 text-rose-300',
      WITHDRAWN: 'bg-slate-500/20 text-slate-400',
    };
    return colors[status] || 'bg-slate-500/20 text-slate-400';
  };

  // Application list loaded from API
  const loadApplications = useCallback(async () => {
    setLoading(true);
    try {
      const result: any = await api.get('/applications');
      setApplications(result.applications || result || []);
      setError(null);
    } catch (err: any) {
      console.error('Failed to load applications:', err);
      setError(err.message || 'Failed to load applications');
      showToast('Failed to load applications', 'error');
      // Fallback: try listing via jobs if applications API unavailable
      try {
        const jobsResult: any = await api.get('/jobs?status=SAVED');
        setApplications(jobsResult.jobs || []);
      } catch {}
    } finally {
      setLoading(false);
    }
  }, []);

  const filteredApplications = useMemo(() => {
    return applications.filter(app =>
      filterStatus === 'all' || app.status === filterStatus
    );
  }, [applications, filterStatus]);

  const searchFilteredApplications = useMemo(() => {
    return filteredApplications.filter(app =>
      (app.job?.title?.toLowerCase().includes(searchQuery.toLowerCase()) ||
       app.job?.company?.toLowerCase().includes(searchQuery.toLowerCase()))
    );
  }, [filteredApplications, searchQuery]);

  const openAppDetail = useCallback((app: ApplicationSummary) => {
    setSelectedApp(app as ApplicationSummary | null);
  }, []);

  const setEditApp = useCallback((appId: string, data: { status: ApplicationStatus; notes: string; application_date: string | null; next_followup: string | null; interviewer_name: string | null; interviewer_contact: string | null }) => {
    setEditingApp({ id: appId, data });
  }, []);

  const deleteApp = useCallback(async (appId: string) => {
    showToast('Application management API not yet available', 'error');
  }, []);

  const createApp = useCallback(async (payload: { job_id: string; status: ApplicationStatus; notes: string }) => {
    showToast('Application management API not yet available', 'error');
  }, []);

  const updateApp = useCallback(async (appId: string, payload: { status: ApplicationStatus; notes: string; application_date: string | null; next_followup: string | null; interviewer_name: string | null; interviewer_contact: string | null }) => {
    showToast('Application management API not yet available', 'error');
  }, [loadApplications]);

  useEffect(() => {
    loadApplications();
  }, [loadApplications]);

  return (
    <div className='min-h-screen p-4 sm:p-6 lg:p-8'>
      <div className='mb-6'>
        <h1 className='text-2xl font-bold text-slate-900 mb-2'>Application Tracker</h1>
        <p className='text-slate-500'>Track your job application lifecycle from SAVED to WITHDRAWN</p>
      </div>
      <div className='mb-4'>
        <select
          value={filterStatus === 'all' ? '' : filterStatus}
          onChange={(e) => setFilterStatus(e.target.value as ApplicationStatus)}
          className='w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-300 focus:outline-none focus:border-blue-500'
        >
          <option value='all'>All Statuses</option>
          <option value='SAVED'>SAVED</option>
          <option value='INTERESTED'>INTERESTED</option>
          <option value='PREPARING'>PREPARING</option>
          <option value='APPLIED'>APPLIED</option>
          <option value='ASSESSMENT'>ASSESSMENT</option>
          <option value='INTERVIEW'>INTERVIEW</option>
          <option value='OFFER'>OFFER</option>
          <option value='REJECTED'>REJECTED</option>
          <option value='WITHDRAWN'>WITHDRAWN</option>
        </select>
      </div>
      <div className='mb-4'>
        <input
          type='text'
          placeholder='Search by company or job title...'
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className='w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 transition-colors'
        />
      </div>
      <div className='mb-4'>Application list not available via API in this release. Use the job analysis or review queue features.</div>
      <div className='mb-4'>Loading applications...</div>
    </div>
  );
};
