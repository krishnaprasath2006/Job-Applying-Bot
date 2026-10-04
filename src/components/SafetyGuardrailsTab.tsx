import React from 'react';
import { HelpCircle, Shield } from 'lucide-react';
import type { SafetyReport } from '../types/api.js';

interface SafetyGuardrailsTabProps {
  safety: SafetyReport | null;
  onUpdateSafety: (updates: Partial<SafetyReport>) => Promise<void>;
}

/**
 * Safety settings are server-controlled and read-only here. The backend's
 * SafetyReport declares exactly four flags; anything else it reports arrives
 * through the open `actions` map, which is rendered generically below.
 */
const FALLBACK_SAFETY: SafetyReport = {
  dry_run: true,
  safe_mode: true,
  require_human_approval: true,
  allow_final_submission: false,
  submission_possible: false,
};

interface GuardrailRow {
  key: string;
  label: string;
  description: string;
  value: boolean;
  required: boolean;
  danger: boolean;
}

export const SafetyGuardrailsTab: React.FC<SafetyGuardrailsTabProps> = ({
  safety,
  onUpdateSafety,
}) => {
  const safetySettings: SafetyReport = safety ?? FALLBACK_SAFETY;

  const guardrails: GuardrailRow[] = [
    {
      key: 'dry_run',
      label: 'Dry Run Mode',
      description: 'All operations are simulated. No real applications submitted.',
      value: safetySettings.dry_run,
      required: true,
      danger: false,
    },
    {
      key: 'safe_mode',
      label: 'Safe Mode',
      description: 'Blocks all privileged actions by default. Explicit allow required.',
      value: safetySettings.safe_mode,
      required: true,
      danger: false,
    },
    {
      key: 'require_human_approval',
      label: 'Human Approval Required',
      description: 'Every application action requires explicit human confirmation.',
      value: safetySettings.require_human_approval,
      required: true,
      danger: false,
    },
    {
      key: 'allow_final_submission',
      label: 'Allow Final Submission',
      description: 'Permits actual submission to employer sites.',
      value: safetySettings.allow_final_submission,
      required: false,
      danger: true,
    },
  ];

  // Anything the server reports beyond the four declared flags.
  const serverActions: GuardrailRow[] = Object.entries(safetySettings.actions ?? {}).map(
    ([key, value]) => ({
      key,
      label: key.replace(/[._]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
      description: 'Reported by the server safety policy.',
      value: Boolean(value),
      required: false,
      danger: false,
    }),
  );

  const sections = [
    {
      title: 'Core Invariants',
      badge: 'NON-NEGOTIABLE',
      rows: guardrails.filter((g) => g.required),
      emptyText: null,
    },
    {
      title: 'Submission Control',
      badge: 'DANGEROUS',
      rows: guardrails.filter((g) => !g.required),
      emptyText: null,
    },
    {
      title: 'Server-Reported Actions',
      badge: 'OPEN MAP',
      rows: serverActions,
      emptyText: 'The server reported no additional safety actions.',
    },
  ];

  const renderState = (row: GuardrailRow) => {
    if (row.required) {
      return (
        <span className="text-xs font-mono text-emerald-300 px-2 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20">
          LOCKED ON
        </span>
      );
    }
    return row.value ? (
      <span className="flex items-center gap-2 px-3 py-1.5 rounded-lg font-mono text-xs bg-emerald-500/10 text-emerald-300 border border-emerald-500/20">
        <span className="w-2 h-2 rounded-full bg-emerald-400" />
        ON
      </span>
    ) : (
      <span className="flex items-center gap-2 px-3 py-1.5 rounded-lg font-mono text-xs bg-slate-800 text-slate-400 border border-slate-700">
        <span className="w-2 h-2 rounded-full bg-slate-500" />
        OFF
      </span>
    );
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <div className="flex items-center gap-2">
              <Shield className="w-5 h-5 text-emerald-400" />
              <h2 className="text-xl font-bold text-white">Safety Guardrails & Policy</h2>
              <span className="text-xs px-2.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-semibold">
                SERVER-CONTROLLED
              </span>
            </div>
            <p className="text-sm text-slate-400 mt-1">
              These settings are enforced by the FastAPI backend. The UI is read-only — safety
              invariants cannot be modified from the frontend.
            </p>
          </div>
          <span className="text-xs font-mono text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
            dry_run={String(safetySettings.dry_run)} • safe_mode={String(safetySettings.safe_mode)} •
            human_approval={String(safetySettings.require_human_approval)} • submission=
            {String(safetySettings.allow_final_submission)}
          </span>
        </div>
      </div>

      {/* Guardrail sections */}
      <div className="space-y-4">
        {sections.map((section) => (
          <div
            key={section.title}
            className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden"
          >
            <div className="px-5 py-3 bg-slate-950 border-b border-slate-800 flex items-center gap-2">
              <h3 className="font-bold text-white">{section.title}</h3>
              <span className="text-xs font-mono text-slate-400 px-2 py-0.5 rounded bg-slate-800">
                {section.badge}
              </span>
            </div>

            {section.rows.length === 0 ? (
              <div className="px-5 py-4 text-xs text-slate-500 font-mono">{section.emptyText}</div>
            ) : (
              <div className="divide-y divide-slate-800">
                {section.rows.map((row) => (
                  <div
                    key={row.key}
                    className={`px-5 py-4 flex items-center justify-between gap-4 ${
                      row.required ? 'bg-slate-950/50' : 'bg-slate-900'
                    }`}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-white">{row.label}</span>
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 font-mono">
                          {row.key}
                        </span>
                        {row.required && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-mono">
                            REQUIRED
                          </span>
                        )}
                        {row.danger && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-300 border border-rose-500/30 font-mono">
                            DANGER
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-slate-400">{row.description}</p>
                    </div>
                    {renderState(row)}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Policy Documentation */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6">
        <h3 className="font-bold text-white mb-4 flex items-center gap-2">
          <HelpCircle className="w-5 h-5 text-blue-400" />
          Policy Documentation
        </h3>
        <div className="space-y-3 text-sm text-slate-300">
          <p>
            <strong>Core Invariants (Non-Negotiable):</strong> <code>dry_run</code>,{' '}
            <code>safe_mode</code>, and <code>require_human_approval</code> are asserted by the
            backend on startup. If any is violated the process refuses to start.
          </p>
          <p>
            <strong>Submission Control:</strong> <code>allow_final_submission</code> governs whether
            a real submission can ever be made. No route writes safety settings.
          </p>
          <p>
            <strong>Server-Reported Actions:</strong> the <code>actions</code> map is rendered
            as-is. This UI does not invent toggles the backend does not report.
          </p>
          <p className="text-amber-300">
            <strong>Immutability:</strong> the React frontend has no write path to any safety
            setting. All configuration is server-side only.
          </p>
        </div>
      </div>
    </div>
  );
};

export default SafetyGuardrailsTab;