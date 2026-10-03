import React, { useState } from 'react';
import { FileText, CheckCircle, Plus, Upload, Download, Eye, Sparkles } from 'lucide-react';
import type { ResumeVariant } from '../types/index.js';

interface ResumeVaultTabProps {
  resumes: ResumeVariant[];
  onActivateResume: (id: string) => Promise<void>;
  onAddResume: (resume: Partial<ResumeVariant>) => Promise<void>;
}

export const ResumeVaultTab: React.FC<ResumeVaultTabProps> = ({
  resumes,
  onActivateResume,
  onAddResume,
}) => {
  const [showAddModal, setShowAddModal] = useState(false);
  const [selectedResume, setSelectedResume] = useState<ResumeVariant | null>(null);

  const [name, setName] = useState('');
  const [targetRole, setTargetRole] = useState('Full Stack Software Engineer');
  const [format, setFormat] = useState<'pdf' | 'docx' | 'txt'>('pdf');
  const [contentSnippet, setContentSnippet] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setIsSubmitting(true);
    try {
      await onAddResume({
        name,
        targetRole,
        format,
        contentSnippet,
      });
      setShowAddModal(false);
      setName('');
      setContentSnippet('');
    } finally {
      setIsSubmitting(false);
    }
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
          onClick={() => setShowAddModal(true)}
          className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl text-sm font-semibold bg-blue-600 hover:bg-blue-500 text-white shadow-md shadow-blue-500/20 cursor-pointer"
        >
          <Plus className="w-4 h-4" />
          <span>Upload Variant</span>
        </button>
      </div>

      {/* Resumes Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {resumes.map((resume) => (
          <div
            key={resume.id}
            className={`rounded-2xl p-5 border transition-all flex flex-col justify-between ${
              resume.isActive
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
                    <h3 className="font-bold text-white text-base">{resume.name}</h3>
                    <div className="text-xs text-slate-400">
                      {resume.filename} • {resume.format.toUpperCase()}
                    </div>
                  </div>
                </div>

                {resume.isActive ? (
                  <span className="flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold bg-blue-500/20 text-blue-300 border border-blue-500/30">
                    <CheckCircle className="w-3.5 h-3.5" /> Active
                  </span>
                ) : (
                  <button
                    onClick={() => onActivateResume(resume.id)}
                    className="px-3 py-1 rounded-lg text-xs font-medium text-slate-400 hover:text-white bg-slate-800 hover:bg-slate-700 border border-slate-700 cursor-pointer"
                  >
                    Set as Active
                  </button>
                )}
              </div>

              <div className="space-y-2 text-xs text-slate-300 mt-2">
                <div className="flex items-center justify-between text-slate-400">
                  <span>Target Role Focus:</span>
                  <span className="font-semibold text-slate-200">{resume.targetRole}</span>
                </div>
                <div className="flex items-center justify-between text-slate-400">
                  <span>Extracted Skills Count:</span>
                  <span className="font-semibold text-blue-400">{resume.skillsCount} Verified</span>
                </div>
                <p className="text-xs text-slate-400 pt-2 border-t border-slate-800/80 leading-relaxed">
                  {resume.summary}
                </p>
              </div>
            </div>

            <div className="flex items-center justify-between pt-4 mt-4 border-t border-slate-800 gap-2">
              <span className="text-[11px] text-slate-500">
                Updated {new Date(resume.uploadedAt).toLocaleDateString()}
              </span>

              <button
                onClick={() => setSelectedResume(resume)}
                className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 font-medium cursor-pointer"
              >
                <Eye className="w-3.5 h-3.5" />
                <span>Preview Parsed Text</span>
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Preview Modal */}
      {selectedResume && (
        <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-xl w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="font-bold text-white text-base">{selectedResume.name} - Extracted Content</h3>
              <button onClick={() => setSelectedResume(null)} className="text-slate-400 hover:text-white">✕</button>
            </div>
            <div className="bg-slate-950 p-4 rounded-xl border border-slate-800 text-xs text-slate-300 font-mono whitespace-pre-line max-h-80 overflow-y-auto">
              {selectedResume.contentSnippet}
            </div>
            <div className="flex justify-end">
              <button
                onClick={() => setSelectedResume(null)}
                className="px-4 py-2 bg-slate-800 text-white rounded-lg text-xs"
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
              <h3 className="font-bold text-white text-base">Add Resume Variant</h3>
              <button onClick={() => setShowAddModal(false)} className="text-slate-400 hover:text-white">✕</button>
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
                  <option value="pdf">PDF (.pdf)</option>
                  <option value="docx">Word (.docx)</option>
                  <option value="txt">Plain Text (.txt)</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-400 mb-1">Summary / Excerpt</label>
                <textarea
                  rows={4}
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
                  className="px-4 py-1.5 rounded-lg text-xs font-semibold bg-blue-600 hover:bg-blue-500 text-white"
                >
                  {isSubmitting ? 'Saving...' : 'Save Variant'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
