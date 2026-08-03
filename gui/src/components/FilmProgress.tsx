"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, Check, Loader2 } from "lucide-react";

// Mirrors STAGES in worker/app/jobs.py. Order is what the bar draws.
const STAGES = ["queued", "script", "narration", "world", "shots", "render", "done"] as const;

// "world" and "shots" only occur for a 3D film. A Short skips them, so they
// render as stages that never light up rather than as an error.
const FILM_ONLY = new Set(["world"]);

type Job = {
  stage: string;
  done: number;
  total: number;
  error: string | null;
  draft_id: string | null;
  kind: string;
};

export default function FilmProgress({ jobId }: { jobId: string }) {
  const [job, setJob] = useState<Job | null>(null);
  const [gone, setGone] = useState(false);

  useEffect(() => {
    if (!jobId) return;
    let stop = false;

    const tick = async () => {
      try {
        const res = await fetch(`/api/youtube/jobs/${jobId}`, { cache: "no-store" });
        if (!res.ok) {
          if (res.status === 404) setGone(true);
          return;
        }
        const next: Job = await res.json();
        if (stop) return;
        setJob(next);
        // Stop polling once the run has settled, either way.
        if (next.stage === "done" || next.error) stop = true;
      } catch {
        // A dropped poll is not a failed render. Keep trying.
      }
    };

    void tick();
    const timer = setInterval(() => {
      if (stop) {
        clearInterval(timer);
        return;
      }
      void tick();
    }, 2000);

    return () => {
      stop = true;
      clearInterval(timer);
    };
  }, [jobId]);

  if (gone) {
    return <p className="text-sm text-red-400">Job not found.</p>;
  }

  if (!job) {
    return (
      <div className="flex items-center space-x-3 text-foreground/50">
        <Loader2 className="w-4 h-4 animate-spin" />
        <span className="text-xs font-bold uppercase tracking-widest">Starting run…</span>
      </div>
    );
  }

  const current = STAGES.indexOf(job.stage as (typeof STAGES)[number]);
  const isFilm = job.kind === "film";
  const failed = Boolean(job.error);

  return (
    <div className="glass-panel rounded-3xl p-6 space-y-5">
      <ol className="flex flex-wrap gap-2">
        {STAGES.map((stage, i) => {
          const skipped = !isFilm && FILM_ONLY.has(stage);
          const complete = i < current && !skipped;
          const active = i === current && !failed;

          return (
            <li
              key={stage}
              className={`flex items-center space-x-2 rounded-xl px-3 py-2 text-xs font-bold uppercase tracking-wider transition-all ${
                complete
                  ? "bg-green-500/10 text-green-400 border border-green-500/20"
                  : active
                    ? "bg-primary/10 text-primary border border-primary/30"
                    : "bg-foreground/[0.03] text-foreground/25 border border-transparent"
              }`}
            >
              {complete && <Check className="w-3 h-3" />}
              {active && <Loader2 className="w-3 h-3 animate-spin" />}
              <span>{stage}</span>
              {active && job.total > 0 && (
                <span className="font-mono normal-case">
                  {job.done}/{job.total}
                </span>
              )}
            </li>
          );
        })}
      </ol>

      {failed && (
        <div className="flex items-start space-x-3 rounded-2xl border border-red-500/20 bg-red-500/5 p-4">
          <AlertTriangle className="w-4 h-4 text-red-400 mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-xs font-bold uppercase tracking-widest text-red-400">
              Stopped at “{job.stage}”
            </p>
            <p className="mt-1 text-sm text-foreground/60">{job.error}</p>
          </div>
        </div>
      )}

      {job.stage === "done" && job.draft_id && (
        <a
          href="/drafts"
          className="inline-flex items-center space-x-2 rounded-xl bg-green-500/10 px-4 py-2 text-sm font-semibold text-green-400 hover:bg-green-500/20 transition-all"
        >
          <Check className="w-4 h-4" />
          <span>Done — open in Drafts Queue</span>
        </a>
      )}
    </div>
  );
}
