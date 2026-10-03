import React, { useState, useEffect } from 'react';
import {
  Shield,
  ShieldCheck,
  ShieldAlert,
  AlertTriangle,
  RotateCcw,
  CheckCircle,
  XCircle,
  Lock,
  Sliders,
  Terminal,
} from 'lucide-react';
import type { SafetySettings } from '../types/index.js';

interface SafetyGuardrailsTabProps {
  safety: SafetySettings | null;
  onUpdateSafety: (updates: Partial<SafetySettings>) => Promise<void>;
  onResetCounter: () => Promise<void>;
}

export const SafetyGuardrailsTab: React.FC<SafetyGuardrailsTabProps> = ({
  safety,
  onUpdateSafety,
  onResetCounter,
}) => {
  const [systemStatus, setSystemStatus] = useState<any>(null);
  const [statusLoading, setStatusLoading] = useState(false);

  const fetchStatus = async () => {
    setStatusLoading(true);
    try {
      const res = await fetch('/api/status');
      const data = await res.json();
      setSystemStatus(data);
    } catch (e) {
      console.error(e);
    } finally {
      setStatusLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus();
  }, []);

  if (!safety) return null;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6">
        <div className="flex items-center gap-2">
          <Shield className="w-5 h-5 text-blue-400" />
          <h2 className="text-xl font-bold text-white">Safety Policy & Invariants Console</h2>
          <span className="text-xs px-2.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono">
            Safety Invariants Guard
          </span>
        </div>
        <p className="text-sm text-slate-400 mt-1">
          The safety system enforces non-negotiable guardrails. In Safe Mode and Dry Run mode, the
          bot validates job forms and requirement fits without performing real third-party submissions.
        </p>
      </div>

      {/* Main Guardrails Toggles */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Safe Mode */}
        <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 space-y-3">
          <div className="flex items-center justify-between">
            <span className="font-bold text-white text-sm">Safe Mode</span>
            <input
              type="checkbox"
              checked={safety.safeMode}
              onChange={(e) => onUpdateSafety({ safeMode: e.target.checked })}
              className="w-4 h-4 rounded text-blue-600 bg-slate-950 border-slate-700"
            />
          </div>
          <p className="text-xs text-slate-400 leading-relaxed">
            Restricts privileged operations. Disallows any submission when disabled.
          </p>
          <div className="text-xs font-semibold text-emerald-400 flex items-center gap-1">
            <ShieldCheck className="w-4 h-4" />
            <span>{safety.safeMode ? 'Active - Invariants Protected' : 'Relaxed'}</span>
          </div>
        </div>

        {/* Dry Run */}
        <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 space-y-3">
          <div className="flex items-center justify-between">
            <span className="font-bold text-white text-sm">Dry Run Mode</span>
            <input
              type="checkbox"
              checked={safety.dryRun}
              onChange={(e) => onUpdateSafety({ dryRun: e.target.checked })}
              className="w-4 h-4 rounded text-blue-600 bg-slate-950 border-slate-700"
            />
          </div>
          <p className="text-xs text-slate-400 leading-relaxed">
            Simulates form filling, checks answers, and audits the apply flow without executing the final submission button.
          </p>
          <div className="text-xs font-semibold text-blue-400 flex items-center gap-1">
            <ShieldCheck className="w-4 h-4" />
            <span>{safety.dryRun ? 'Dry Run Protected' : 'Live Applications Permitted'}</span>
          </div>
        </div>

        {/* Human Approval */}
        <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 space-y-3">
          <div className="flex items-center justify-between">
            <span className="font-bold text-white text-sm">Human Approval Gate</span>
            <input
              type="checkbox"
              checked={safety.requireHumanApproval}
              onChange={(e) => onUpdateSafety({ requireHumanApproval: e.target.checked })}
              className="w-4 h-4 rounded text-blue-600 bg-slate-950 border-slate-700"
            />
          </div>
          <p className="text-xs text-slate-400 leading-relaxed">
            Every prospective application must be explicitly reviewed and accepted by you before the bot can process it.
          </p>
          <div className="text-xs font-semibold text-purple-400 flex items-center gap-1">
            <Lock className="w-4 h-4" />
            <span>{safety.requireHumanApproval ? 'Mandatory Sign-off' : 'Auto Queue'}</span>
          </div>
        </div>
      </div>

      {/* Quota & Submission Guard */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4">
        <h3 className="font-bold text-white text-base flex items-center gap-2">
          <Sliders className="w-4 h-4 text-blue-400" />
          <span>Application Quota & Rate Limit Protection</span>
        </h3>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="p-4 bg-slate-950 rounded-xl border border-slate-800 space-y-2">
            <div className="text-xs font-semibold text-slate-400">Max Applications Per Run</div>
            <div className="flex items-center gap-3">
              <input
                type="number"
                min="1"
                max="100"
                value={safety.maxApplicationsPerRun}
                onChange={(e) =>
                  onUpdateSafety({ maxApplicationsPerRun: parseInt(e.target.value, 10) || 10 })
                }
                className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-white w-28"
              />
              <span className="text-xs text-slate-400">Applications max batch</span>
            </div>
          </div>

          <div className="p-4 bg-slate-950 rounded-xl border border-slate-800 space-y-2 flex items-center justify-between">
            <div>
              <div className="text-xs font-semibold text-slate-400">Applications Run Today</div>
              <div className="text-xl font-bold text-white mt-1">
                {safety.applicationsToday} / {safety.maxApplicationsPerRun}
              </div>
            </div>
            <button
              onClick={onResetCounter}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 cursor-pointer"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>Reset Counter</span>
            </button>
          </div>
        </div>
      </div>

      {/* Permissions Matrix */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4">
        <h3 className="font-bold text-white text-base">Actions Permission Matrix</h3>

        <div className="border border-slate-800 rounded-xl overflow-hidden">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-800/60 text-xs font-semibold text-slate-400 uppercase tracking-wider">
              <tr>
                <th className="px-4 py-3">Action</th>
                <th className="px-4 py-3">Permission State</th>
                <th className="px-4 py-3">Safety Rationalization</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800 text-slate-300">
              <tr>
                <td className="px-4 py-3 font-medium text-white">Browser Navigation</td>
                <td className="px-4 py-3">
                  <span className="text-xs font-semibold text-emerald-400">ALLOWED</span>
                </td>
                <td className="px-4 py-3 text-xs text-slate-400">
                  Read-only navigation to inspect job specifications.
                </td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-white">File Upload (Resumes)</td>
                <td className="px-4 py-3">
                  <span className="text-xs font-semibold text-emerald-400">ALLOWED</span>
                </td>
                <td className="px-4 py-3 text-xs text-slate-400">
                  Attaches verified active resume variant.
                </td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-white">Form Pre-filling</td>
                <td className="px-4 py-3">
                  <span className="text-xs font-semibold text-emerald-400">ALLOWED</span>
                </td>
                <td className="px-4 py-3 text-xs text-slate-400">
                  Fills candidate facts verified from evidence profile.
                </td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-white">Final Privileged Submission</td>
                <td className="px-4 py-3">
                  {safety.allowFinalSubmission ? (
                    <span className="text-xs font-semibold text-emerald-400">ENABLED</span>
                  ) : (
                    <span className="text-xs font-semibold text-rose-400">LOCKED (PROTECTED)</span>
                  )}
                </td>
                <td className="px-4 py-3 text-xs text-slate-400">
                  Simulated under Dry Run to protect candidate from accidental submissions.
                </td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-white">Block on CAPTCHA / MFA</td>
                <td className="px-4 py-3">
                  <span className="text-xs font-semibold text-emerald-400">ENABLED</span>
                </td>
                <td className="px-4 py-3 text-xs text-slate-400">
                  Instantly halts automation when security challenges are encountered.
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* System Status Diagnostic Terminal */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Terminal className="w-4 h-4 text-blue-400" />
            <h3 className="font-bold text-white text-base">System Diagnostic Report</h3>
          </div>
          <button
            onClick={fetchStatus}
            disabled={statusLoading}
            className="text-xs text-blue-400 hover:text-blue-300 cursor-pointer"
          >
            {statusLoading ? 'Refreshing...' : 'Refresh Diagnostic'}
          </button>
        </div>

        {systemStatus && (
          <pre className="bg-slate-950 p-4 rounded-xl border border-slate-800 text-xs text-emerald-400 font-mono overflow-x-auto leading-relaxed">
            {JSON.stringify(systemStatus, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
};
