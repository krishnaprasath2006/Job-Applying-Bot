import React, { useState, useEffect } from 'react';
import { Cpu, AlertCircle, CheckCircle, Info, Download } from 'lucide-react';
import { aiApi } from '../lib/api/index.js';
import type { AiStatusReport } from '../types/api.js';

interface HuggingFaceAITabProps {
  safety: unknown;
}

/**
 * AI provider status, read from `GET /api/status`.
 *
 * Everything shown here comes from that response. The previous version of this
 * tab hardcoded the strings "Provider Not Configured" and "Lexical Only" into
 * the header regardless of the real state, fabricated a plausible-looking
 * status object when the request failed, and mounted four sub-panels that
 * rendered hardcoded JSON. A status display that cannot report a working
 * provider is worse than none: it teaches the reader to distrust the rest of
 * the console.
 *
 * The status endpoint reports *configuration*, not reachability, by design --
 * polling it must never depend on a model being loaded. So "provider
 * configured" here means "selected and registered", and availability of a
 * specific model is not claimed. Use the CLI (`python job_assistant.py ai
 * health`) for a live probe.
 */
export const HuggingFaceAITab: React.FC<HuggingFaceAITabProps> = ({ safety: _safety }) => {
  const [status, setStatus] = useState<AiStatusReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    aiApi
      .getStatus()
      .then((res) => {
        if (!cancelled) setStatus(res);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // Show the failure. Never substitute invented status.
        setError(err instanceof Error ? err.message : 'Could not reach the API.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6">
        <p className="text-sm text-slate-400">Loading AI provider status…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6">
        <div className="flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-rose-400 shrink-0" />
          <div>
            <h2 className="font-bold text-white">AI status unavailable</h2>
            <p className="text-sm text-slate-400 mt-1">{error}</p>
            <p className="text-sm text-slate-500 mt-2">
              Start the API with <code>python job_assistant.py</code> in another terminal, or check
              that it is running on port 8000.
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (!status) return null;

  const rows: Array<{ label: string; value: string; tone?: 'good' | 'warn' }> = [
    {
      label: 'Selected provider',
      value: status.provider,
      tone: status.configured ? 'good' : 'warn',
    },
    { label: 'Configured', value: status.configured ? 'yes' : 'no' },
    { label: 'Model', value: status.model || 'not set' },
    {
      label: 'Registered providers',
      value: status.providers_available?.length ? status.providers_available.join(', ') : 'none',
    },
    {
      label: 'Embedding scorer',
      value: status.embedding_scorer_available
        ? 'declared by the selected provider'
        : 'not available from the selected provider',
      tone: status.embedding_scorer_available ? 'good' : 'warn',
    },
    { label: 'Source mode', value: status.source_mode },
    { label: 'API key present', value: status.api_key_present ? 'yes' : 'no' },
    { label: 'Allows application', value: status.allows_application ? 'yes' : 'no' },
  ];

  return (
    <div className="space-y-6">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6">
        <div className="flex items-center gap-3">
          <div className="p-3 rounded-xl bg-blue-500/10 text-blue-400 border border-blue-500/20">
            <Cpu className="w-6 h-6" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-white">AI Providers</h2>
            <p className="text-sm text-slate-400">
              Local-first provider abstraction. No API key is required for either local provider.
            </p>
          </div>
        </div>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
        <div className="px-5 py-3 bg-slate-950 border-b border-slate-800 flex items-center gap-2">
          <CheckCircle className="w-4 h-4 text-slate-400" />
          <h3 className="font-bold text-white">Reported configuration</h3>
        </div>
        <div className="divide-y divide-slate-800">
          {rows.map((row) => (
            <div
              key={row.label}
              className="px-5 py-3 flex items-center justify-between gap-4 bg-slate-900"
            >
              <span className="text-sm text-slate-400">{row.label}</span>
              <span
                className={`font-mono text-xs px-2 py-0.5 rounded border ${
                  row.tone === 'good'
                    ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20'
                    : row.tone === 'warn'
                      ? 'bg-amber-500/10 text-amber-300 border-amber-500/20'
                      : 'bg-slate-800 text-slate-300 border-slate-700'
                }`}
              >
                {row.value}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6">
        <h3 className="font-bold text-white flex items-center gap-2 mb-3">
          <Info className="w-4 h-4 text-blue-400" />
          What this page does and does not tell you
        </h3>
        <div className="space-y-2 text-sm text-slate-300">
          <p>
            This reads <code>GET /api/status</code>, which reports <em>configuration</em> without
            contacting any model. Polling status must never depend on a model being loaded, so
            &ldquo;configured&rdquo; does not claim a model is currently loaded.
          </p>
          <p>
            For a live probe, use the CLI:{' '}
            <code>python job_assistant.py ai health</code> and{' '}
            <code>python job_assistant.py ai models</code>.
          </p>
          <p>
            Similarity scoring runs server-side during job matching, selected with{' '}
            <code>--scorer lexical</code> or <code>--scorer embedding</code>. There is no HTTP
            endpoint that computes similarity on demand, so this page does not offer a similarity
            playground.
          </p>
        </div>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6">
        <h3 className="font-bold text-white flex items-center gap-2 mb-3">
          <Download className="w-4 h-4 text-emerald-400" />
          Local embedding model
        </h3>
        <div className="space-y-2 text-sm text-slate-300">
          <p>
            The <code>huggingface</code> provider computes sentence embeddings on CPU with no API
            key and no hosted inference. It requires the optional extra:
          </p>
          <pre className="bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs font-mono text-slate-300 overflow-x-auto">
            pip install -e &quot;.[embeddings]&quot;
          </pre>
          <p>
            The checkpoint is <code>sentence-transformers/all-MiniLM-L6-v2</code> (384 dimensions,
            Apache-2.0, about 90&nbsp;MB), downloaded once and then cached on disk. Override it with{' '}
            <code>ASSISTANT_AI__EMBEDDING_MODEL</code>.
          </p>
          <p className="text-amber-300">
            This provider is embedding-only. It cannot generate text — use the{' '}
            <code>ollama</code> provider for generation.
          </p>
        </div>
      </div>
    </div>
  );
};

export default HuggingFaceAITab;