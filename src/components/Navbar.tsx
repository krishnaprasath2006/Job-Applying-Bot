import React from 'react';
import {
  Briefcase,
  CheckCircle2,
  FileText,
  HelpCircle,
  Layers,
  Shield,
  UserCheck,
  Zap,
  Brain,
} from 'lucide-react';

export type TabType = 'jobs' | 'review' | 'profile' | 'resumes' | 'questions' | 'safety' | 'ai';

interface NavbarProps {
  activeTab: TabType;
  setActiveTab: (tab: TabType) => void;
  reviewCount: number;
  safetyMode: boolean;
  dryRun: boolean;
}

export const Navbar: React.FC<NavbarProps> = ({
  activeTab,
  setActiveTab,
  reviewCount,
  safetyMode,
  dryRun,
}) => {
  const tabs: Array<{ id: TabType; label: string; icon: React.ReactNode; badge?: number }> = [
    { id: 'jobs', label: 'Job Matching', icon: <Briefcase className="w-4 h-4" /> },
    {
      id: 'review',
      label: 'Review Queue',
      icon: <Layers className="w-4 h-4" />,
      badge: reviewCount,
    },
    { id: 'profile', label: 'Candidate Profile', icon: <UserCheck className="w-4 h-4" /> },
    { id: 'resumes', label: 'Resume Vault', icon: <FileText className="w-4 h-4" /> },
    { id: 'questions', label: 'Auto-Fill Q&A', icon: <HelpCircle className="w-4 h-4" /> },
    { id: 'ai', label: 'Hugging Face AI', icon: <Brain className="w-4 h-4" /> },
    { id: 'safety', label: 'Safety & Guardrails', icon: <Shield className="w-4 h-4" /> },
  ];

  return (
    <header className="bg-slate-900 border-b border-slate-800 sticky top-0 z-40">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-blue-600 flex items-center justify-center text-white shadow-md shadow-blue-500/20">
              <Zap className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-bold text-lg tracking-tight text-white">Apllie</span>
                <span className="text-xs px-2 py-0.5 rounded font-mono bg-blue-500/10 text-blue-400 border border-blue-500/20">
                  Bot Copilot v2.0
                </span>
              </div>
              <p className="text-xs text-slate-400 hidden sm:block">
                Intelligent Job Discovery, Verification & Safe Applying
              </p>
            </div>
          </div>

          <div className="hidden lg:flex items-center gap-2 bg-slate-950/60 px-3 py-1.5 rounded-full border border-slate-800 text-xs">
            <span className="flex items-center gap-1.5 text-emerald-400 font-medium">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
              {safetyMode ? 'Safe Mode Active' : 'Unrestricted'}
            </span>
            <span className="text-slate-600">•</span>
            <span className="text-slate-300">
              {dryRun ? 'Dry Run (Simulated)' : 'Live Apply'}
            </span>
            <span className="text-slate-600">•</span>
            <span className="text-blue-400 font-mono">Port 3000 Verified</span>
          </div>
        </div>

        {/* Tab Navigation */}
        <nav className="flex space-x-1 sm:space-x-2 overflow-x-auto pb-2 scrollbar-none">
          {tabs.map((tab) => {
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-sm font-medium transition-all whitespace-nowrap cursor-pointer ${
                  isActive
                    ? 'bg-blue-600/15 text-blue-400 border border-blue-500/30 shadow-sm shadow-blue-500/10'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 border border-transparent'
                }`}
              >
                {tab.icon}
                <span>{tab.label}</span>
                {tab.badge !== undefined && tab.badge > 0 && (
                  <span
                    className={`ml-1 text-xs px-1.5 py-0.2 rounded-full font-semibold ${
                      isActive ? 'bg-blue-500 text-white' : 'bg-slate-700 text-slate-300'
                    }`}
                  >
                    {tab.badge}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </div>
    </header>
  );
};
