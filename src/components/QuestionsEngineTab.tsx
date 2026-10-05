import React from 'react';
import { HelpCircle, Ban, FileCode2, CircleSlash } from 'lucide-react';

/**
 * Question intelligence — NOT IMPLEMENTED.
 *
 * This tab previously called `GET /api/questions` and `POST
 * /api/questions/answer`. Neither route exists in the FastAPI application
 * (src/api/routes/ registers status, profile, resumes and jobs only), so both
 * calls 404'd. The old code did not check `res.ok`, which turned those 404s
 * into an empty rules table and an undefined "answer" rather than an error.
 *
 * Rather than stub endpoints or simulate answers, this tab states the real
 * position. Question answering is deferred product work: an answer may only be
 * produced from a verified fact, and there is no answer pipeline yet.
 *
 * See "Application Intelligence" in README.md (NOT IMPLEMENTED) and the
 * Future Roadmap.
 */

interface CapabilityRow {
  label: string;
  state: 'exists-disconnected' | 'not-implemented';
  detail: string;
}

const CAPABILITIES: CapabilityRow[] = [
  {
    label: 'Answer a screening question from candidate evidence',
    state: 'not-implemented',
    detail:
      'No backend route, service, or domain model exists. Nothing in src/ produces an answer.',
  },
  {
    label: 'Store or recall previous answers',
    state: 'not-implemented',
    detail:
      'The question_memory table is deliberately not created by any migration, because there is nothing to remember yet.',
  },
  {
    label: 'Classify question intent',
    state: 'exists-disconnected',
    detail:
      'src/ai/question_intent.py implements a deterministic classifier, but no module imports it and no API route exposes it.',
  },
  {
    label: 'Custom question rules from YAML',
    state: 'exists-disconnected',
    detail:
      'additionalQuestions.yaml exists at the repository root for the legacy bot. Nothing in src/ reads it.',
  },
];

const STATE_STYLE: Record<CapabilityRow['state'], { label: string; className: string }> = {
  'not-implemented': {
    label: 'NOT IMPLEMENTED',
    className: 'bg-slate-700/60 text-slate-300 border-slate-600',
  },
  'exists-disconnected': {
    label: 'DISCONNECTED',
    className: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
  },
};

export const QuestionsEngineTab: React.FC = () => {
  return (
    <div className="space-y-6">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6">
        <div className="flex items-center gap-2">
          <HelpCircle className="w-5 h-5 text-slate-400" />
          <h2 className="text-xl font-bold text-white">Auto-Fill Q&amp;A</h2>
          <span className="text-xs px-2.5 py-0.5 rounded-full bg-slate-700/60 text-slate-300 border border-slate-600 font-semibold">
            NOT IMPLEMENTED
          </span>
        </div>
        <p className="text-sm text-slate-400 mt-1">
          Answering application questions is deferred work. This tab previously called API
          endpoints that do not exist; rather than simulate answers, it reports what is actually
          present in the codebase.
        </p>
      </div>

      {/* Why there is no simulator */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6">
        <div className="flex items-start gap-3">
          <Ban className="w-5 h-5 shrink-0 text-rose-400" />
          <div>
            <h3 className="font-bold text-white">Why there is no question simulator here</h3>
            <p className="text-sm text-slate-300 mt-1">
              In this system an answer may only come from a fact the candidate verified, and a
              fact that is merely <span className="font-mono text-amber-300">INFERRED</span> is
              not application-safe. Answering a question therefore requires an evidence-backed
              resolution pipeline that decides{' '}
              <span className="font-mono">ANSWER</span> or{' '}
              <span className="font-mono">INSUFFICIENT_EVIDENCE</span> — never a guess.
            </p>
            <p className="text-sm text-slate-400 mt-2">
              A simulator that produced plausible answers without that pipeline would misrepresent
              the system&apos;s central guarantee, so it was removed rather than reconnected.
            </p>
          </div>
        </div>
      </div>

      {/* Capability status */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
        <div className="px-5 py-3 bg-slate-950 border-b border-slate-800 flex items-center gap-2">
          <CircleSlash className="w-4 h-4 text-slate-400" />
          <h3 className="font-bold text-white">Capability Status</h3>
        </div>
        <div className="divide-y divide-slate-800">
          {CAPABILITIES.map((capability) => {
            const style = STATE_STYLE[capability.state];
            return (
              <div
                key={capability.label}
                className="px-5 py-4 flex items-start justify-between gap-4 bg-slate-900"
              >
                <div className="min-w-0">
                  <div className="font-medium text-white">{capability.label}</div>
                  <p className="text-xs text-slate-400 mt-0.5">{capability.detail}</p>
                </div>
                <span
                  className={`shrink-0 text-[10px] px-2 py-0.5 rounded border font-mono ${style.className}`}
                >
                  {style.label}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      <p className="text-xs text-slate-500 flex items-center gap-2">
        <FileCode2 className="w-3.5 h-3.5" />
        Tracked as FUTURE work under Application Intelligence in the README roadmap.
      </p>
    </div>
  );
};

export default QuestionsEngineTab;