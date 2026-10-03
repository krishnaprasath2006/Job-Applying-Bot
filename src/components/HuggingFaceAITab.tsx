import React, { useState } from 'react';
import {
  Brain,
  Cpu,
  CheckCircle2,
  AlertTriangle,
  ArrowRight,
  ShieldCheck,
  Zap,
  Search,
  RefreshCw,
  Sparkles,
  BookOpen
} from 'lucide-react';

export const HuggingFaceAITab: React.FC = () => {
  // Demo 1: Semantic vs Lexical Similarity
  const [textA, setTextA] = useState('Build REST APIs using Python FastAPI');
  const [textB, setTextB] = useState('Built FastAPI backend');
  const [similarityLoading, setSimilarityLoading] = useState(false);
  const [similarityResult, setSimilarityResult] = useState<{
    lexicalScore: number;
    semanticScore: number;
    derivedInterpretation: string;
    model: string;
    runtime: string;
  } | null>({
    lexicalScore: 0.17,
    semanticScore: 0.84,
    derivedInterpretation: 'DERIVED_MATCH',
    model: 'sentence-transformers/all-MiniLM-L6-v2',
    runtime: 'onnx-cpu'
  });

  // Demo 2: Question Intent Classification
  const [questionInput, setQuestionInput] = useState('Will you now or in the future require visa sponsorship?');
  const [intentLoading, setIntentLoading] = useState(false);
  const [intentResult, setIntentResult] = useState<any>({
    category: 'SPONSORSHIP',
    confidence: 0.98,
    targetProfilePath: 'work_authorization.requires_sponsorship',
    explanation: 'Deterministic match on sponsorship keyword',
    method: 'DETERMINISTIC_RULE'
  });

  const handleRunSimilarity = async () => {
    setSimilarityLoading(true);
    try {
      const res = await fetch('/api/ai/similarity', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ textA, textB })
      });
      const data = await res.json();
      setSimilarityResult(data);
    } catch (err) {
      console.error('Failed to compute similarity:', err);
    } finally {
      setSimilarityLoading(false);
    }
  };

  const handleRunIntent = async () => {
    setIntentLoading(true);
    try {
      const res = await fetch('/api/ai/question-intent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: questionInput })
      });
      const data = await res.json();
      setIntentResult(data);
    } catch (err) {
      console.error('Failed to classify question:', err);
    } finally {
      setIntentLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="bg-slate-800/80 rounded-xl p-6 border border-slate-700/60 shadow-lg">
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-xl bg-purple-600/20 border border-purple-500/30 flex items-center justify-center text-purple-400">
              <Brain className="w-6 h-6" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-xl font-bold text-white">Hugging Face Local Embedding Provider</h2>
                <span className="text-xs px-2.5 py-0.5 rounded-full font-mono bg-purple-500/10 text-purple-300 border border-purple-500/30">
                  Milestone HF-1 Active
                </span>
              </div>
              <p className="text-sm text-slate-400 mt-1">
                Zero-cost local embeddings for requirement matching, resume relevance, and question taxonomy intent.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 bg-slate-900/80 px-4 py-2 rounded-lg border border-slate-700 text-xs">
            <Cpu className="w-4 h-4 text-emerald-400" />
            <span className="text-slate-300">Target Device:</span>
            <span className="font-semibold text-emerald-400">CPU (100% In-Process ONNX)</span>
            <span className="text-slate-600">|</span>
            <span className="text-purple-400 font-semibold">₹0 Cloud Cost</span>
          </div>
        </div>

        {/* Model Spec Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-6 pt-5 border-t border-slate-700/60">
          <div className="bg-slate-900/60 p-3 rounded-lg border border-slate-800">
            <span className="text-xs text-slate-400">Model Target</span>
            <div className="font-mono text-sm font-semibold text-purple-300 truncate">
              all-MiniLM-L6-v2
            </div>
          </div>
          <div className="bg-slate-900/60 p-3 rounded-lg border border-slate-800">
            <span className="text-xs text-slate-400">Vector Dimension</span>
            <div className="font-mono text-sm font-semibold text-white">
              384 Dimensions
            </div>
          </div>
          <div className="bg-slate-900/60 p-3 rounded-lg border border-slate-800">
            <span className="text-xs text-slate-400">License</span>
            <div className="font-mono text-sm font-semibold text-emerald-400">
              Apache 2.0 (Open Source)
            </div>
          </div>
          <div className="bg-slate-900/60 p-3 rounded-lg border border-slate-800">
            <span className="text-xs text-slate-400">Fallback Scorer</span>
            <div className="font-mono text-sm font-semibold text-blue-400">
              Lexical (Token / Jaccard)
            </div>
          </div>
        </div>
      </div>

      {/* Safety Notice Callout */}
      <div className="bg-amber-950/20 border border-amber-500/30 rounded-xl p-4 flex items-start gap-3 text-sm text-amber-200/90">
        <ShieldCheck className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
        <div>
          <span className="font-semibold text-amber-300">Epistemological & Safety Guardrails Enforced:</span>{' '}
          Semantic similarity is a derived distance metric only. It <strong className="text-white">never</strong> mutates candidate verified facts and <strong className="text-white">cannot override a Hard Gate Veto</strong> (such as visa sponsorship restrictions). Real application submission remains strictly disabled.
        </div>
      </div>

      {/* Interactive Tool 1: Semantic vs Lexical Comparator */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-slate-800/80 rounded-xl p-6 border border-slate-700/60 shadow-lg space-y-4">
          <div className="flex items-center gap-2 border-b border-slate-700 pb-3">
            <Zap className="w-5 h-5 text-purple-400" />
            <h3 className="font-semibold text-white">Semantic vs. Lexical Match Simulator</h3>
          </div>

          <p className="text-xs text-slate-400">
            Observe how dense vector embeddings bridge the gap when words differ in phrasing (e.g. "REST APIs" vs "backend").
          </p>

          <div className="space-y-3">
            <div>
              <label className="text-xs text-slate-400 font-medium">Job Requirement Text (Input A):</label>
              <input
                type="text"
                value={textA}
                onChange={(e) => setTextA(e.target.value)}
                className="w-full mt-1 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-purple-500"
              />
            </div>
            <div>
              <label className="text-xs text-slate-400 font-medium">Candidate Evidence / Skill (Input B):</label>
              <input
                type="text"
                value={textB}
                onChange={(e) => setTextB(e.target.value)}
                className="w-full mt-1 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-purple-500"
              />
            </div>

            <button
              onClick={handleRunSimilarity}
              disabled={similarityLoading}
              className="w-full bg-purple-600 hover:bg-purple-500 text-white font-medium py-2 rounded-lg text-sm transition flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50"
            >
              {similarityLoading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
              Compare Signals
            </button>
          </div>

          {similarityResult && (
            <div className="bg-slate-900/90 rounded-lg p-4 border border-slate-700/80 space-y-3 mt-4">
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-400">Derived Interpretation:</span>
                <span className={`px-2 py-0.5 rounded font-mono font-bold text-xs ${
                  similarityResult.derivedInterpretation === 'DERIVED_MATCH'
                    ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                    : 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
                }`}>
                  {similarityResult.derivedInterpretation}
                </span>
              </div>

              <div className="grid grid-cols-2 gap-3 pt-2">
                <div className="bg-slate-800/60 p-2.5 rounded border border-slate-700">
                  <span className="text-xs text-slate-400">Lexical Token Overlap</span>
                  <div className="text-lg font-bold font-mono text-slate-300">
                    {(similarityResult.lexicalScore * 100).toFixed(0)}%
                  </div>
                  <span className="text-[10px] text-slate-500">Jaccard token matching</span>
                </div>
                <div className="bg-slate-800/60 p-2.5 rounded border border-purple-500/30">
                  <span className="text-xs text-purple-400 font-semibold">HF Semantic Embedding</span>
                  <div className="text-lg font-bold font-mono text-purple-300">
                    {(similarityResult.semanticScore * 100).toFixed(0)}%
                  </div>
                  <span className="text-[10px] text-purple-400/70">Cosine similarity (384-d)</span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Interactive Tool 2: Screening Question Intent Classifier */}
        <div className="bg-slate-800/80 rounded-xl p-6 border border-slate-700/60 shadow-lg space-y-4">
          <div className="flex items-center gap-2 border-b border-slate-700 pb-3">
            <Search className="w-5 h-5 text-blue-400" />
            <h3 className="font-semibold text-white">Screening Question Intent Foundation</h3>
          </div>

          <p className="text-xs text-slate-400">
            Maps raw application questions to canonical taxonomy anchors. It classifies intent without inventing answers.
          </p>

          <div className="space-y-3">
            <div>
              <label className="text-xs text-slate-400 font-medium">Screening Question:</label>
              <textarea
                rows={2}
                value={questionInput}
                onChange={(e) => setQuestionInput(e.target.value)}
                className="w-full mt-1 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
              />
            </div>

            <div className="flex flex-wrap gap-1.5">
              <span className="text-xs text-slate-500 mr-1 self-center">Try:</span>
              <button
                type="button"
                onClick={() => setQuestionInput('Will you now or in the future require visa sponsorship?')}
                className="text-[11px] bg-slate-900 hover:bg-slate-700 text-slate-300 px-2 py-1 rounded border border-slate-700 cursor-pointer"
              >
                Sponsorship
              </button>
              <button
                type="button"
                onClick={() => setQuestionInput('How many years of Python and React experience do you have?')}
                className="text-[11px] bg-slate-900 hover:bg-slate-700 text-slate-300 px-2 py-1 rounded border border-slate-700 cursor-pointer"
              >
                Skills
              </button>
              <button
                type="button"
                onClick={() => setQuestionInput('What is your expected annual base salary?')}
                className="text-[11px] bg-slate-900 hover:bg-slate-700 text-slate-300 px-2 py-1 rounded border border-slate-700 cursor-pointer"
              >
                Salary
              </button>
            </div>

            <button
              onClick={handleRunIntent}
              disabled={intentLoading}
              className="w-full bg-blue-600 hover:bg-blue-500 text-white font-medium py-2 rounded-lg text-sm transition flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50"
            >
              {intentLoading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Brain className="w-4 h-4" />}
              Classify Intent
            </button>
          </div>

          {intentResult && (
            <div className="bg-slate-900/90 rounded-lg p-4 border border-slate-700/80 space-y-2 mt-4 text-xs">
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Classified Category:</span>
                <span className="font-mono font-bold text-blue-400 bg-blue-500/10 px-2 py-0.5 rounded border border-blue-500/20">
                  {intentResult.category}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Confidence:</span>
                <span className="font-mono text-emerald-400 font-semibold">
                  {(intentResult.confidence * 100).toFixed(0)}%
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Target Profile Fact:</span>
                <span className="font-mono text-purple-300">
                  {intentResult.targetProfilePath || 'Requires Human Review'}
                </span>
              </div>
              <div className="text-[11px] text-slate-500 pt-1 border-t border-slate-800">
                {intentResult.explanation}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
