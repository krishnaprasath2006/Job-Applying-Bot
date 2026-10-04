import React from 'react';
import {
  Sparkles,
  Cpu,
  Database,
  ExternalLink,
  Zap,
  Shield,
} from 'lucide-react';
import type { AiStatusReport, SafetyReport } from '../../types/api.js';

interface AiOverviewTabProps {
  aiStatus: any;
  safety: any;
}

export const AiOverviewTab: React.FC<AiOverviewTabProps> = ({ aiStatus, safety }) => {
  return (
    <div className="space-y-6">
      {/* Provider Status */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center gap-3">
            <div className="p-3 rounded-xl bg-blue-500/10 text-blue-400 border border-blue-500/20">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <div className="text-xs font-medium text-slate-400">Provider</div>
              <div className="font-bold text-white">{'ollama'}</div>
            </div>
          </div>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center gap-3">
            <div className="p-3 rounded-xl bg-purple-500/10 text-purple-400 border border-purple-500/20">
              <Cpu className="w-5 h-5" />
            </div>
            <div>
              <div className="text-xs font-medium text-slate-400">Model</div>
              <div className="font-bold text-white">{'qwen2.5:7b'}</div>
            </div>
          </div>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center gap-3">
            <div className="p-3 rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              <Zap className="w-5 h-5" />
            </div>
            <div>
              <div className="text-xs font-medium text-slate-400">Embeddings</div>
              <div className="font-bold text-white">Lexical Only</div>
            </div>
          </div>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center gap-3">
            <div className="p-3 rounded-xl bg-amber-500/10 text-amber-400 border border-amber-500/20">
              <ExternalLink className="w-5 h-5" />
            </div>
            <div>
              <div className="text-xs font-medium text-slate-400">API Key</div>
              <div className="font-bold text-white">Not Set</div>
            </div>
          </div>
        </div>
      </div>

      {/* Available Providers */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <h3 className="font-bold text-white mb-3 flex items-center gap-2">
          <Database className="w-5 h-5 text-blue-400" />
          Available Providers
        </h3>
        <div className="flex flex-wrap gap-2">
          <span className="px-3 py-1 rounded-full text-xs font-medium bg-blue-500/10 text-blue-400 border border-blue-500/20 font-mono">
            ollama
          </span>
        </div>
      </div>

      {/* Source Mode & Safety */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <h3 className="font-bold text-white mb-3 flex items-center gap-2">
          <Shield className="w-5 h-5 text-emerald-400" />
          Source Mode & Safety
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
          <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
            <div className="text-xs font-medium text-slate-400">Source Mode</div>
            <div className="font-bold text-white font-mono">DISCOVERY_ONLY</div>
          </div>
          <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
            <div className="text-xs font-medium text-slate-400">Allows Application</div>
            <div className="font-bold text-white">No</div>
          </div>
          <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
            <div className="text-xs font-medium text-slate-400">Safety Mode</div>
            <div className="font-bold text-white">Enabled</div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AiOverviewTab;