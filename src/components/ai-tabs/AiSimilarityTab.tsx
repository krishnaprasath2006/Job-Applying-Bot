import React, { useState } from 'react';
import { Zap, Loader2, Zap as ZapIcon } from 'lucide-react';

interface AiSimilarityTabProps {
  onComputeSimilarity: (text1: string, text2: string) => Promise<void>;
  similarityLoading: boolean;
  similarityResult: any;
  testText1: string;
  testText2: string;
  setTestText1: (text: string) => void;
  setTestText2: (text: string) => void;
}

export const AiSimilarityTab: React.FC<AiSimilarityTabProps> = ({
  onComputeSimilarity,
  similarityLoading,
  similarityResult,
  testText1,
  testText2,
  setTestText1,
  setTestText2,
}) => {
  return (
    <div className="space-y-6">
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <h3 className="font-bold text-white mb-4 flex items-center gap-2">
          <span className="w-5 h-5 text-purple-400">✨</span>
          Semantic Similarity Test
        </h3>
        <p className="text-sm text-slate-400 mb-4">
          Test the backend's similarity scorer. Uses lexical (TF-IDF) by default.
          Embedding scorer only available if provider supports embeddings.
        </p>

        <div className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1">Text 1 (Job Requirement)</label>
            <textarea
              rows={3}
              placeholder="e.g. Senior ML Engineer with Python and PyTorch, 5+ years"
              className="w-full bg-slate-950 border border-slate-800 rounded-lg p-3 text-sm text-white focus:border-blue-500 font-mono"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1">Text 2 (Candidate Skill)</label>
            <textarea
              rows={3}
              placeholder="e.g. ML Engineer with TensorFlow and Python, 3 years"
              className="w-full bg-slate-950 border border-slate-800 rounded-lg p-3 text-sm text-white focus:border-blue-500 font-mono"
            />
          </div>
          <button
            disabled={false}
            className="px-5 py-2 rounded-lg text-sm font-semibold bg-purple-600 hover:bg-purple-500 text-white disabled:opacity-50 flex items-center gap-2"
          >
            <span className="w-4 h-4">⚡</span>
            Compute Similarity
          </button>
        </div>
      </div>
    </div>
  );
};

export default AiSimilarityTab;