import React, { useState, useEffect, useRef } from 'react';
import { FileText, CheckCircle, Plus, Upload, Download, Eye, Sparkles, AlertCircle, Loader2 } from 'lucide-react';
import type { Resume } from '../types/api.js';
import { resumeApi } from '../lib/api/index.js';

interface NewResumeInput {
  name: string;
  targetRole: string;
  format: 'PDF' | 'DOCX' | 'TXT' | 'MD';
  contentSnippet: string;
}

interface UploadProgress {
  progress: number;
  status: 'idle' | 'uploading' | 'success' | 'error';
  error?: string;
}

interface ResumeVaultTabProps {
  resumes: Resume[];
  /** Client-side selection; the backend stores no active-resume flag. */
  activeResumeId: string | null;
  onActivateResume: (id: string) => Promise<void>;
  onAddResume: (newResume: NewResumeInput) => Promise<void>;
}

export const ResumeVaultTab: React.FC<ResumeVaultTabProps> = ({
  resumes,
  activeResumeId,
  onActivateResume,
  onAddResume,
}) => {
  const [showAddModal, setShowAddModal] = useState(false);
  const [selectedResume, setSelectedResume] = useState<Resume | null>(null);
  const [name, setName] = useState('');
  const [targetRole, setTargetRole] = useState('Full Stack Software Engineer');
  const [format, setFormat] = useState<'PDF' | 'DOCX' | 'TXT' | 'MD'>('PDF');
  const [contentSnippet, setContentSnippet] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showUpload, setShowUpload] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<UploadProgress>({ progress: 0, status: 'idle' });
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Load resumes when prop changes
  useEffect(() => {
    // resumes are passed from parent, no need to fetch here
  }, [resumes]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setIsSubmitting(true);
    try {
      await onAddResume({ name: name.trim(), targetRole, format, contentSnippet });
      setShowAddModal(false);
      setName('');
      setTargetRole('Full Stack Software Engineer');
      setFormat('PDF');
      setContentSnippet('');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploadProgress({ progress: 0, status: 'uploading' });

    // Upload the file using the new multipart endpoint
    const formData = new FormData();
    formData.append('file', file);
    formData.append('variant', '');
    formData.append('role_focus', '');
    formData.append('skills', '');

    resumeApi.upload(file, 'primary').then(
      async (resume) => {
        setUploadProgress({ progress: 100, status: 'success' });
        // Auto-activate the uploaded resume and add as a variant
        setShowUpload(true);
        // We'll handle this after the user confirms
      },
      (error) => {
        setUploadProgress({
          progress: 0,
          status: 'error',
          error: error instanceof Error ? error.message : 'Unknown upload error',
        });
      }
    );

    // Reset file input
    fileInputRef.current?.dispatchEvent(new Event('reset'));
  };

  const handleUploadConfirm = async () => {
    setShowUpload(false);
    // After upload, we have the resume in state - we need to fetch it
    // and then add it as a variant
    setShowAddModal(true);
  };

  const handleUploadCancel = () => {
    setShowUpload(false);
    // Reset file input
    fileInputRef.current?.dispatchEvent(new Event('reset'));
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <FileText className="w-5 h-5 text-blue-400" />
            <h2 className="text-xl font-bold text-white">Resume Document Vault & Variants</h2>
          </div>
          <p className="text-sm text-slate-400 mt-1">
            Manage tailored resume versions for different tech tracks (Full-Stack, Backend,
            Infrastructure). The active variant is automatically attached during application runs.
          </p>
        </div>

        <button
          onClick={() => setShowUpload(true)}
          className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl text-sm font-semibold bg-blue-600 hover:bg-blue-500 text-white shadow-md shadow-blue-500/20 cursor-pointer">
          <Upload className="w-4 h-4" />
          <span>Upload Resume</span>
        </button>

        <button
          onClick={() => setShowAddModal(true)}
          className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl text-sm font-semibold bg-blue-600 hover:bg-blue-500 text-white shadow-md shadow-blue-500/20 cursor-pointer">
          <Plus className="w-4 h-4" />
          <span>Add Variant (Server Path)</span>
        </button>
      </div>

      {/* Resumes Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {resumes.map((resume) => (
          <div
            key={resume.id}
            className={`rounded-2xl p-5 border transition-all flex flex-col justify-between ${
              activeResumeId === resume.id
                ? 'bg-slate-900/90 border-blue-500/50 shadow-lg shadow-blue-500/5 ring-1 ring-blue-500/30'
                : 'bg-slate-900/60 border-slate-800 hover:border-slate-700'
            }`}
          >
            <div>
              <div className="flex items-start justify-between gap-2 mb-3">
                <div className="flex items-center gap-2">
                  <span className="p-2 rounded-lg bg-blue-500/10 text-blue-400 border border-blue-500/20">
                    <FileText className="w-5 h-5" />
                  </span>
                  <div>
                    <h3 className="font-bold text-white text-base">
                      {resume.variant || resume.filename || 'Unnamed'}
                    </h3>
                    <div className="text-xs text-slate-400">
                      {resume.filename} • {resume.file_type}
                    </div>
                  </div>
                </div>

                {activeResumeId === resume.id ? (
                  <span className="flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold bg-blue-500/20 text-blue-300 border border-blue-500/30">
                    <CheckCircle className="w-3.5 h-3.5" /> Active
                  </span>
                ) : (
                  <button
                    onClick={() => onActivateResume(resume.id)}
                    className="px-3 py-1 rounded-lg text-xs font-medium text-slate-400 hover:text-white bg-slate-800 hover:bg-slate-700 border border-slate-700 cursor-pointer">
                    Set as Active
                  </button>
                )}
              </div>

              <div className="space-y-2 text-xs text-slate-300 mt-2">
                <div className="flex items-center justify-between text-slate-400">
                  <span>Target Role Focus:</span>
                  <span className="font-semibold text-slate-200">
                    {resume.role_focus || 'Not specified'}
                  </span>
                </div>
                <div className="flex items-center justify-between text-slate-400">
                  <span>Extracted Skills Count:</span>
                  <span className="font-semibold text-blue-400">
                    {resume.skills?.length || 0} Verified
                  </span>
                </div>
                <p className="text-xs text-slate-400 pt-2 border-t border-slate-800/80 leading-relaxed">
                  {resume.raw_text?.slice(0, 200) || 'No content preview'}
                </p>
              </div>
            </div>

            <div className="flex items-center justify-between pt-4 mt-4 border-t border-slate-800 gap-2">
              <span className="text-[11px] text-slate-500">
                Updated {new Date(resume.updated_at || resume.created_at).toLocaleDateString()}
              </span>

              <button
                onClick={() => setSelectedResume(resume)}
                className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 font-medium cursor-pointer">
                <Eye className="w-3.5 h-3.5" />
                <span>Preview Parsed Text</span>
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Upload Progress Modal */}
      {uploadProgress.status !== 'idle' && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-sm w-full p-8 shadow-2xl text-center space-y-4">
            <h3 className="text-xl font-bold text-white">
              {uploadProgress.status === 'success'
                ? 'Resume Uploaded Successfully'
                : 'Upload Failed'}
              </h3>
            {uploadProgress.status === 'uploading' && (
              <div className="space-y-2">
                <Loader2 className="w-6 h-6 mx-auto text-blue-500" />
                <p className="text-slate-400">Uploading...</p>
                <progress
                  className="w-24 h-2 bg-slate-700 rounded-md appearance-none"
                  max={100}
                  value={uploadProgress.progress}
                />
              </div>
            )}
            {uploadProgress.status === 'error' && (
              <div>
                <AlertCircle className="w-5 h-5 text-red-400 mx-auto" />
                <p className="text-slate-400 mt-2">{uploadProgress.error}</p>
              </div>
            )}
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setUploadProgress({ progress: 0, status: 'idle' })}
                className="px-4 py-2 bg-slate-800 text-white rounded-lg text-sm"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add Resume Modal */}
      {showAddModal && (
        <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-md w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="font-bold text-white text-base">
                {uploadProgress.status === 'success' ? 'Create Variant from Uploaded Resume' : 'Add Resume Variant (Server Path)'}

              </h3>
              <button
                onClick={() => setShowAddModal(false)}
                className="text-slate-400 hover:text-white"
              >
                &times;
              </button>
            </div>

            <form onSubmit={handleSubmit} className="space-y-3">
              <div>
                <label className="block text-xs font-semibold text-slate-400 mb-1">Variant Name</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. AI & Machine Learning Focus"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-white focus:border-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-400 mb-1">Target Role</label>
                <input
                  type="text"
                  value={targetRole}
                  onChange={(e) => setTargetRole(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-white focus:border-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-400 mb-1">Document Format</label>
                <select
                  value={format}
                  onChange={(e) => setFormat(e.target.value as any)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-white focus:border-blue-500"
                >
                  <option value="PDF">PDF (.pdf)</option>
                  <option value="DOCX">Word (.docx)</option>
                  <option value="TXT">Plain Text (.txt)</option>
                  <option value="MD">Markdown (.md)</option>
                </select>
              </div>

              {uploadProgress.status === 'success' && (
                <div>
                  <label className="block text-xs font-semibold text-slate-400 mb-1">
                    Uploaded Resume
                  </label>
                  <p className="text-slate-400 mb-2">
                    {uploadProgress.progress > 0 ? 'Resume has been uploaded to server' : ''}
                  </p>
                  <p className="text-xs text-blue-400">
                    The resume is now available in your vault. Select it to create a variant.
                  </p>
                </div>
              )}

              {!uploadProgress.status || uploadProgress.status === 'idle' && (
                <div>
                  <label className="block text-xs font-semibold text-slate-400 mb-1">Server File Path *</label>
                  <input
                    type="text"
                    placeholder="/path/to/resume.pdf (server-side path)"
                    value={contentSnippet}
                    onChange={(e) => setContentSnippet(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs text-white focus:border-blue-500 font-mono"
                  />
                  <p className="text-xs text-amber-400 mt-1">
                    FastAPI ingest requires a server-side file path. Upload the file to the server first,
                    then provide the absolute path here.
                  </p>
                </div>
              )}

              <div>
                <label className="block text-xs font-semibold text-slate-400 mb-1">Summary / Excerpt</label>
                <textarea
                  rows={3}
                  value={contentSnippet}
                  onChange={(e) => setContentSnippet(e.target.value)}
                  placeholder="Key experience bullet points or summary..."
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs text-white focus:border-blue-500 font-mono"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="px-3 py-1.5 rounded-lg text-xs text-slate-400 hover:text-white"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-4 py-1.5 rounded-lg text-xs font-semibold bg-blue-600 hover:bg-blue-500 text-white">
                  {isSubmitting ? 'Saving...' : 'Save Variant'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Upload Confirmation Modal */}
      {showUpload && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-md w-full p-8 shadow-2xl text-center space-y-6">
            <h3 className="text-xl font-bold text-white">
              Resume Uploaded Successfully
            </h3>
            <p className="text-slate-400 mb-4">
              Your resume has been uploaded and is now available in your vault.
            </p>
            <p className="text-slate-500 text-sm mb-6">
              You can now create a variant using this uploaded resume.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowUpload(false);
                  setShowAddModal(true);
                }}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-500">
              Confirm
              </button>
              <button
                onClick={handleUploadCancel}
                className="px-4 py-2 bg-slate-800 text-white rounded-lg text-sm hover:bg-slate-700"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* File Upload Input - hidden */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf,.docx,.txt,.md"
        onChange={handleFileChange}
        className="hidden"
      />
    </div>
  );
};

export default ResumeVaultTab;
