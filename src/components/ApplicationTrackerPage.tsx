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

interface JobSummary {
  id: string;
  company: string;
  title: string;
}

interface ApplicationFormData {
  status: ApplicationStatus;
  notes: string;
  application_date: string | null;
  next_followup: string | null;
  interviewer_name: string | null;
  interviewer_contact: string | null;
}

export const ApplicationTrackerPage = () => {
  const [applications, setApplications] = useState<ApplicationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterStatus, setFilterStatus] = useState<ApplicationStatus | 'all'>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [view, setView] = useState<'board' | 'list'>('list');
  const [selectedApp, setSelectedApp] = useState<ApplicationSummary | null>(null);
  const [editingApp, setEditingApp] = useState<{ id: string; data: ApplicationFormData } | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState<string | null>(null);
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [selectedJob, setSelectedJob] = useState<JobSummary | null>(null);

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
  }

  const loadApplications = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result: any = await api.get('/applications');
      setApplications(result.applications || result || []);
    } catch (err: any) {
      console.error('Failed to load applications:', err);
      setError(err.message || 'Failed to load applications');
      showToast('Failed to load applications', 'error');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadApplications();
  }, [loadApplications]);

  // Load available jobs from the jobs API
  useEffect(() => {
    api.get('/jobs').then((result: any) => {
      const jobList = result.jobs || [];
      const formatted = jobList.map((j: any) => ({
        id: j.id,
        company: j.company || '',
        title: j.title || '',
      }));
      setJobs(formatted);
    }).catch(() => {
      setJobs([]);
    });
  }, []);

  // Filter applications by status
  const filteredApplications = useMemo(() => {
    return applications.filter(app =>
      filterStatus === 'all' || app.status === filterStatus
    );
  }, [applications, filterStatus]);

  // Search filter
  const searchFilteredApplications = useMemo(() => {
    return filteredApplications.filter(app =>
      (app.job?.title?.toLowerCase().includes(searchQuery.toLowerCase()) ||
       app.job?.company?.toLowerCase().includes(searchQuery.toLowerCase()))
    );
  }, [filteredApplications, searchQuery]);

  const openAppDetail = useCallback((app: ApplicationSummary) => {
    setSelectedApp(app as ApplicationSummary | null);
  }, []);

  const setEditApp = useCallback((appId: string, data: ApplicationFormData) => {
    setEditingApp({ id: appId, data });
  }, []);

  const deleteApp = useCallback(async (appId: string) => {
    if (showDeleteConfirm && showDeleteConfirm !== appId) return;
    setShowDeleteConfirm(null);
    try {
      await api.delete(`/applications/${appId}`);
      showToast('Application deleted successfully', 'success');
      loadApplications();
    } catch (err: any) {
      console.error('Failed to delete application:', err);
      showToast('Failed to delete application: ' + (err.message || 'Unknown error'), 'error');
    }
  }, [showDeleteConfirm, loadApplications]);

  const createApp = useCallback(async (payload: {
    job_id: string;
    status?: ApplicationStatus;
    notes?: string;
  }) => {
    try {
      const result: any = await api.post('/applications', payload);
      showToast('Application created successfully', 'success');
      setSelectedJobId(null);
      loadApplications();
    } catch (err: any) {
      console.error('Failed to create application:', err);
      showToast('Failed to create application: ' + (err.message || 'Unknown error'), 'error');
    }
  }, [loadApplications]);

  const updateApp = useCallback(async (appId: string, payload: {
    status: ApplicationStatus;
    notes: string;
    application_date: string | null;
    next_followup: string | null;
    interviewer_name: string | null;
    interviewer_contact: string | null;
  }) => {
    try {
      const result: any = await api.patch(`/applications/${appId}`, payload);
      showToast('Application updated successfully', 'success');
      setEditingApp(null);
      loadApplications();
    } catch (err: any) {
      console.error('Failed to update application:', err);
      showToast('Failed to update application: ' + (err.message || 'Unknown error'), 'error');
    }
  }, [loadApplications]);

  // Determine which section to render
  const hasContent = applications.length > 0;

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
          className='w-full bg-slate-900 border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-300 focus:outline-none focus-border-blue-500'
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
        </select>
      </div>
      {/* Loading state */}
      {loading && <div data-testid='loading'>Loading applications...</div>}
      {error && (
        <div className='mb-4' role='alert'>
          <span data-testid='error'>Failed to load applications: {error}</span>
          <button onClick={loadApplications} className='mt-2 bg-emerald-600 text-emerald-200 px-3 py-1 rounded-sm text-sm'>Retry</button>
        </div>
      )}
      {applications.length === 0 && <div className='mb-4' role='alert' data-testid='empty-state'>No applications found</div>}
      {applications.length > 0 && (
        <div className='space-y-4'>
          {searchFilteredApplications.map((app) => {
            const statusColorVal = statusColor(app.status);
            return (
              <div key={app.id} className='p-4 rounded-lg bg-slate-800 border border-slate-700'>
                <div className='flex flex-col gap-2'>
                  <h3 className='text-sm font-medium' data-testid='job-title'>{app.job?.title || 'Unknown Job'}</h3>
                  <p className='text-xs text-slate-400' data-testid='job-company'>{app.job?.company || ''}</p>
                  <span className={statusColorVal} data-testid='status-badge'>{app.status}</span>
                  <div className='text-xs text-slate-500'>
                    created {app.created_at && new Date(app.created_at).toLocaleDateString()}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
      {/* Create form button */}
      {editingApp === null && (!loading || applications.length > 0) && (
        <div
          className='mb-4 cursor-pointer text-sm text-blue-400 underline'
          style={{ display: 'inline-block' }}
          onClick={() => setEditingApp({
            id: '',
            data: {
              status: 'SAVED' as ApplicationStatus,
              notes: '',
              application_date: null,
              next_followup: null,
              interviewer_name: '',
              interviewer_contact: '',
            }
          })}
        >
          <button
            data-testid='create-button'
            onClick={() => setEditingApp('new', {})}
            className='underline text-blue-400 cursor-pointer'
          >
            Create new application
          </button>
        </div>
      )}
      {/* Edit form */}
      {editingApp !== null && (
        <div className='fixed inset-0 bg-slate-900/60 backdrop-blur-z flex items-center justify-center z-50' role='dialog' aria-modal='true'>
          <div className='bg-slate-800 rounded-lg p-6 w-full max-w-md border border-slate-700'>
            <h2 className='text-xl font-bold text-slate-100 mb-4'>{editingApp.id ? 'Edit Application' : 'Create Application'}</h2>
            <form>
              <div className='mb-4'>
                <label className='block text-sm font-medium text-slate-300 mb-2'>Status</label>
                <select
                  value={editingApp.data.status}
                  onChange={(e) =>
                    setEditingApp({
                      id: editingApp.data.id,
                      data: { ...editingApp.data, status: e.target.value },
                    })
                  }
                  className='w-full bg-slate-900 border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-300 focus:outline-none focus-border-blue-500'
                >
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
                <label className='block text-sm font-medium text-slate-300 mb-2'>Company</label>
                <input
                  value={editingApp.data.company || ''}
                  onChange={(e) =>
                    setEditingApp({
                      id: editingApp.data.id,
                      data: { ...editingApp.data, company: e.target.value },
                    })
                  }
                  className='w-full bg-slate-900 border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-300 focus:outline-none focus-border-blue-500'
                  placeholder='Company'
                />
              </div>
              <div className='mb-4'>
                <label className='block text-sm font-medium text-slate-300 mb-2'>Title</label>
                <input
                  value={editingApp.data.title || ''}
                  onChange={(e) =>
                    setEditingApp({
                      id: editingApp.data.id,
                      data: { ...editingApp.data, title: e.target.value },
                    })
                  }
                  className='w-full bg-slate-900 border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-300 focus:outline-none focus-border-blue-500'
                  placeholder='Title'
                />
              </div>
              <div className='mb-4'>
                <label className='block text-sm font-medium text-slate-300 mb-2'>
                  Application Date
                </label>
                <input
                  type='date'
                  value={editingApp.data.application_date || ''}
                  onChange={(e) =>
                    setEditingApp({
                      id: editingApp.data.id,
                      data: { ...editingApp.data, application_date: e.target.value },
                    })
                  }
                  className='w-full bg-slate-900 border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-300 focus:outline-none focus-border-blue-500'
                />
              </div>
              <div className='mb-4'>
                <label className='block text-sm font-medium text-slate-300 mb-2'>
                  Next Follow-up
                </label>
                <input
                  type='date'
                  value={editingApp.data.next_followup || ''}
                  onChange={(e) =>
                    setEditingApp({
                      id: editingApp.data.id,
                      data: { ...editingApp.data, next_followup: e.target.value },
                    })
                  }
                  className='w-full bg-slate-900 border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-300 focus:outline-none focus-border-blue-500'
                />
              </div>
              <div className='mb-4'>
                <label className='block text-sm font-medium text-slate-300 mb-2'>
                  Interviewer Name
                </label>
                <input
                  value={editingApp.data.interviewer_name || ''}
                  onChange={(e) =>
                    setEditingApp({
                      id: editingApp.data.id,
                      data: { ...editingApp.data, interviewer_name: e.target.value },
                    })
                  }
                  className='w-full bg-slate-900 border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-300 focus:outline-none focus-border-blue-500'
                  placeholder='Interviewer Name'
                />
              </div>
              <div className='mb-4'>
                <label className='block text-sm font-medium text-slate-300 mb-2'>
                  Interviewer Contact
                </label>
                <input
                  value={editingApp.data.interviewer_contact || ''}
                  onChange={(e) =>
                    setEditingApp({
                      id: editingApp.data.id,
                      data: { ...editingApp.data, interviewer_contact: e.target.value },
                    })
                  }
                  className='w-full bg-slate-900 border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-300 focus:outline-none focus-border-blue-500'
                  placeholder='Interviewer Contact'
                />
              </div>
              <div className='mb-4'>
                <label className='block text-sm font-medium text-slate-300 mb-2'>Notes</label>
                <textarea
                  value={editingApp.data.notes || ''}
                  onChange={(e) =>
                    setEditingApp({
                      id: editingApp.data.id,
                      data: { ...editingApp.data, notes: e.target.value },
                    })
                  }
                  className='w-full bg-slate-900 border-slate-800 rounded-lg h-32 px-3 py-2 text-sm text-slate-300 focus:outline-none focus-border-blue-500'
                  placeholder='Notes'
                />
              </div>
              <div className='flex gap-3'>
                <button
                  type='button'
                  onClick={() => setEditingApp(null)}
                  className='flex-1 bg-slate-600 text-slate-300 px-4 py-2 rounded-sm text-sm hover:bg-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500'
                >
                  Cancel
                </button>
                <button
                  type='button'
                  onClick={() => {
                    updateApp(editingApp.id!, {
                      status: editingApp.data.status,
                      notes: editingApp.data.notes,
                      application_date: editingApp.data.application_date,
                      next_followup: editingApp.data.next_followup,
                      interviewer_name: editingApp.data.interviewer_name,
                      interviewer_contact: editingApp.data.interviewer_contact,
                    });
                    setEditingApp(null);
                  }}
                  className='flex-1 bg-emerald-600 text-emerald-200 px-4 py-2 rounded-sm text-sm hover:bg-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-300'
                >
                  Save
                </button>
              </div>
            </form>
              </div>
            </div>
          </div>
        )

