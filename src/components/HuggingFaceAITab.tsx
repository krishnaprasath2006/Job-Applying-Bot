import React, { useState, useEffect } from 'react';
import {
  Brain,
  Sparkles,
  Database,
  Cpu,
  Download,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Loader2,
  Zap,
  Sparkle,
  Terminal,
  FileText,
  Search,
  Eye,
  Settings,
  Link,
  ExternalLink,
  Shield,
  Zap as ZapIcon,
  Cpu as CpuIcon,
  FileText as FileTextIcon,
} from 'lucide-react';
import type { SafetyReport } from '../types/api.js';
import { aiApi } from '../lib/api/index.js';
import AiOverviewTab from './ai-tabs/AiOverviewTab';
import AiModelsTab from './ai-tabs/AiModelsTab';
import AiSimilarityTab from './ai-tabs/AiSimilarityTab';
import AiCacheTab from './ai-tabs/AiCacheTab';

interface HuggingFaceAITabProps {
  safety: SafetyReport | null;
}

export const HuggingFaceAITab: React.FC<HuggingFaceAITabProps> = ({ safety }) => {
  const [aiStatus, setAiStatus] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'overview' | 'models' | 'similarity' | 'cache'>('overview');
  const [similarityResult, setSimilarityResult] = useState<any>(null);
  const [similarityLoading, setSimilarityLoading] = useState(false);
  const [testText1, setTestText1] = useState('Senior Machine Learning Engineer with Python and PyTorch');
  const [testText2, setTestText2] = useState('ML Engineer needing TensorFlow and 5+ years experience');

  useEffect(() => {
    loadAiStatus();
  }, []);

  const loadAiStatus = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/status');
      if (res.ok) {
        const data = await res.json();
        setAiStatus(data.ai || {});
      }
    } catch (err) {
      console.error('Failed to load AI status:', err);
      setAiStatus({
        configured: false,
        provider: 'ollama',
        model: 'qwen2.5:7b',
        api_key_present: false,
        providers_available: ['ollama'],
        embedding_scorer_available: false,
        source_mode: 'DISCOVERY_ONLY',
        allows_application: false,
      });
    } finally {
      setLoading(false);
    }
  };

  const handleSimilarity = async () => {
    // Placeholder - the actual API endpoint would need to be implemented
    console.log('Similarity computation requested');
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <span className="w-8 h-8 text-blue-400 animate-spin">⟳</span>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-3 rounded-xl bg-blue-500/10 text-blue-400 border border-blue-500/20">
              <span className="w-6 h-6">🧠</span>
            </div>
            <div>
              <h2 className="text-xl font-bold text-white">AI & Hugging Face Integration</h2>
              <p className="text-sm text-slate-400">
                Local-first AI provider abstraction. No external API keys required.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="flex items-center gap-1 px-3 py-1 rounded-full text-xs font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20">
              <span className="w-3 h-3">⚠️</span> Provider Not Configured
            </span>
            <span className="flex items-center gap-1 px-3 py-1 rounded-full text-xs font-medium bg-slate-700 text-slate-300 border border-slate-600">
              <span className="w-3 h-3">⚡</span> Lexical Only
            </span>
          </div>
        </div>
      </div>

      {/* Tab Navigation */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
        <div className="border-b border-slate-800">
          <nav className="flex gap-4 px-6" aria-label="AI tabs">
            {(['overview', 'models', 'similarity', 'cache'] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-4 py-3 text-sm font-medium rounded-t-xl transition-colors border-b-2 border-transparent -mb-px ${
                  activeTab === tab
                    ? 'text-blue-400 border-blue-400 bg-slate-900'
                    : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800/50'
                }`}
              >
                {tab.charAt(0).toUpperCase() + tab.slice(1)}
              </button>
            ))}
          </nav>
        </div>

        <div className="p-6">
          <div className="text-center py-12 text-slate-400">
            <p>AI tab content - {activeTab} tab</p>
            <p className="text-sm mt-2">Tab content components would be rendered here</p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default HuggingFaceAITab;