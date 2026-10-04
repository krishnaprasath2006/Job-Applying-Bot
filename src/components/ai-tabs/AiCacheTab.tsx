import React from 'react';
import { FileText, Terminal, Sparkles, Cpu, Database, ExternalLink, Zap, Shield } from 'lucide-react';

export const AiCacheTab: React.FC = () => {
  return (
    <div className="space-y-6">
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <h3 className="font-bold text-white mb-4 flex items-center gap-2">
          <span className="w-5 h-5 text-blue-400">📄</span>
          Embedding Cache Status
        </h3>
        <p className="text-sm text-slate-400 mb-4">
          The backend caches embeddings per (provider, model, text hash). Cache is in-memory and cleared on restart.
        </p>
        <div className="bg-slate-950 p-4 rounded-lg border border-slate-800">
          <p className="text-slate-400 text-center py-8">
            Cache statistics not exposed via API yet.
            <br />
            <span className="text-xs text-amber-400">Use CLI: <code className="font-mono bg-slate-800 px-1.5 py-0.5 rounded">python job_assistant.py status</code></span>
          </p>
        </div>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <h3 className="font-bold text-white mb-4 flex items-center gap-2">
          <Terminal className="w-5 h-5 text-emerald-400" />
          CLI Commands
        </h3>
        <div className="space-y-2 text-sm">
          <div className="bg-slate-950 p-3 rounded-lg border border-slate-800 font-mono text-xs text-emerald-300">
            python job_assistant.py status
          </div>
          <div className="bg-slate-950 p-3 rounded-lg border border-slate-800 font-mono text-xs text-blue-300">
            {`python job_assistant.py job match <job_id> --scorer embedding`}
          </div>
          <div className="bg-slate-950 p-3 rounded-lg border border-slate-800 font-mono text-xs text-amber-300">
            python job_assistant.py profile validate
          </div>
        </div>
      </div>
    </div>
  );
};

export default AiCacheTab;