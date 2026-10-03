import React, { useState, useEffect } from 'react';
import {
  HelpCircle,
  Sparkles,
  Search,
  CheckCircle,
  ArrowRight,
  Database,
  Cpu,
  ShieldCheck,
  Send,
} from 'lucide-react';
import type { CustomQuestionRule, QuestionAnswerResponse } from '../types/index.js';

export const QuestionsEngineTab: React.FC = () => {
  const [rules, setRules] = useState<CustomQuestionRule[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  // Simulator state
  const [queryQuestion, setQueryQuestion] = useState(
    'Will you now or in the future require visa sponsorship?'
  );
  const [answerResult, setAnswerResult] = useState<QuestionAnswerResponse | null>(null);
  const [isAnswering, setIsAnswering] = useState(false);

  useEffect(() => {
    fetch('/api/questions')
      .then((r) => r.json())
      .then((data) => {
        setRules(data.rules || []);
        setIsLoading(false);
      })
      .catch((err) => {
        console.error(err);
        setIsLoading(false);
      });
  }, []);

  const handleTestQuestion = async (textToTest?: string) => {
    const q = textToTest || queryQuestion;
    if (!q.trim()) return;

    setIsAnswering(true);
    try {
      const res = await fetch('/api/questions/answer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q }),
      });
      const data = await res.json();
      setAnswerResult(data);
    } catch (err) {
      console.error(err);
    } finally {
      setIsAnswering(false);
    }
  };

  const sampleQuestions = [
    'Will you now or in the future require visa sponsorship?',
    'Are you legally authorized to work in the United States?',
    'How many years of experience do you have with Python?',
    'How many years of experience do you have with React?',
    'What are your annual salary expectations (USD)?',
    'What is your earliest notice period?',
    'Have you completed a Bachelor’s degree in Computer Science?',
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6">
        <div className="flex items-center gap-2">
          <Sparkles className="w-5 h-5 text-blue-400" />
          <h2 className="text-xl font-bold text-white">
            Custom Questions Auto-Answer Engine
          </h2>
          <span className="text-xs px-2.5 py-0.5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20 font-mono">
            additionalQuestions.yaml Matrix
          </span>
        </div>
        <p className="text-sm text-slate-400 mt-1">
          Simulate how the bot responds to common job board screening questions (Easy Apply,
          Workday, Greenhouse). Answers are pulled directly from verified profile facts and your
          configured answer rules.
        </p>
      </div>

      {/* Interactive Simulator Card */}
      <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-6 space-y-4">
        <h3 className="text-base font-bold text-white flex items-center gap-2">
          <Cpu className="w-4 h-4 text-emerald-400" />
          <span>Interactive Answer Simulator</span>
        </h3>

        {/* Quick Sample Questions */}
        <div className="space-y-1.5">
          <div className="text-xs text-slate-400">Click a sample screening question:</div>
          <div className="flex flex-wrap gap-2">
            {sampleQuestions.map((q, i) => (
              <button
                key={i}
                onClick={() => {
                  setQueryQuestion(q);
                  handleTestQuestion(q);
                }}
                className="text-xs px-2.5 py-1 rounded-lg bg-slate-950 border border-slate-800 text-slate-300 hover:text-white hover:border-slate-700 cursor-pointer"
              >
                {q}
              </button>
            ))}
          </div>
        </div>

        {/* Input box */}
        <div className="flex gap-2">
          <input
            type="text"
            value={queryQuestion}
            onChange={(e) => setQueryQuestion(e.target.value)}
            placeholder="Type any screening question (e.g. Years of experience with Docker?)"
            className="flex-1 bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-hidden"
          />
          <button
            onClick={() => handleTestQuestion()}
            disabled={isAnswering}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold bg-blue-600 hover:bg-blue-500 text-white shadow-md shadow-blue-500/20 cursor-pointer disabled:opacity-50"
          >
            <Send className="w-4 h-4" />
            <span>{isAnswering ? 'Resolving...' : 'Solve'}</span>
          </button>
        </div>

        {/* Response Card */}
        {answerResult && (
          <div className="bg-slate-950 border border-slate-800 rounded-xl p-4 mt-3 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Generated Answer
              </span>
              <span
                className={`text-xs px-2.5 py-0.5 rounded-full font-bold border ${
                  answerResult.confidence === 'HIGH'
                    ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                    : 'bg-amber-500/10 text-amber-400 border-amber-500/20'
                }`}
              >
                {answerResult.confidence} CONFIDENCE
              </span>
            </div>

            <div className="text-lg font-bold text-emerald-300 bg-slate-900/60 p-3 rounded-lg border border-slate-800/80">
              &quot;{answerResult.suggestedAnswer}&quot;
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs text-slate-400 pt-2 border-t border-slate-800/60">
              <div>
                <span className="text-slate-500">Reasoning: </span>
                <span className="text-slate-300">{answerResult.reasoning}</span>
              </div>
              <div>
                <span className="text-slate-500">Source: </span>
                <span className="text-blue-400 font-mono">{answerResult.source}</span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Rules Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2">
            <Database className="w-4 h-4 text-blue-400" />
            <h3 className="font-bold text-white text-base">Active Question Rules Matrix</h3>
          </div>
          <span className="text-xs text-slate-400 font-mono">{rules.length} Rules Loaded</span>
        </div>

        <div className="border border-slate-800 rounded-xl overflow-hidden">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-800/60 text-xs font-semibold text-slate-400 uppercase tracking-wider">
              <tr>
                <th className="px-4 py-3">Category</th>
                <th className="px-4 py-3">Keyword Match</th>
                <th className="px-4 py-3">Target Question Pattern</th>
                <th className="px-4 py-3">Configured Answer</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800 text-slate-300">
              {rules.map((rule) => (
                <tr key={rule.id} className="hover:bg-slate-800/30 transition-colors">
                  <td className="px-4 py-3">
                    <span className="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-mono">
                      {rule.category}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-semibold text-blue-400 font-mono text-xs">
                    {rule.keyword}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-300 max-w-sm">
                    {rule.questionPattern}
                  </td>
                  <td className="px-4 py-3 font-semibold text-emerald-400 font-mono text-xs">
                    {rule.answerValue}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
