import React from 'react';
import { Sparkles, Cpu, Database, ExternalLink, Zap, Shield } from 'lucide-react';

export const AiModelsTab: React.FC = () => {
  return (
    <div className="space-y-6">
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <h3 className="font-bold text-white mb-4 flex items-center gap-2">
          <Sparkles className="w-5 h-5 text-purple-400" />
          Model Management
        </h3>
        <div className="space-y-3 text-sm text-slate-300">
          <p>Models are managed by the Python backend via the AI Provider abstraction.</p>
          <p className="text-amber-300">Frontend does not manage models directly. Configure via <code className="font-mono bg-slate-800 px-1.5 py-0.5 rounded">.env</code> or <code className="font-mono bg-slate-800 px-1.5 py-0.5 rounded">ASSISTANT_AI__PROVIDER</code> / <code className="font-mono bg-slate-800 px-1.5 py-0.5 rounded">ASSISTANT_AI__MODEL</code>.</p>
          <div className="bg-slate-950 p-4 rounded-lg border border-slate-800">
            <h4 className="font-medium text-white mb-2">Current Configuration</h4>
            <pre className="text-xs text-slate-300 font-mono overflow-x-auto">
{JSON.stringify({
  provider: 'ollama',
  model: 'qwen2.5:7b',
  base_url: 'http://localhost:11434',
  embedding_model: null,
  temperature: 0.1,
  timeout_seconds: 60,
}, null, 2)}
            </pre>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AiModelsTab;