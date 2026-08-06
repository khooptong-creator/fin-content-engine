"use client";

import { useEffect, useState } from "react";

type Shot = {
  slug: string;
  ok: boolean;
  attempts: number;
  reason: string;
  js: string;
  probe_pngs: string[];
};

export default function ShotInspector({ jobId }: { jobId: string }) {
  const [shots, setShots] = useState<Shot[]>([]);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    const base = process.env.NEXT_PUBLIC_WORKER_URL || "http://127.0.0.1:8000";
    fetch(`${base}/youtube/jobs/${jobId}/shots`)
      .then((r) => r.json())
      .then(setShots)
      .catch(() => setShots([]));
  }, [jobId]);

  if (!shots.length) return null;

  return (
    <section className="space-y-3">
      <h2 className="text-lg font-medium">Shots</h2>
      {shots.map((shot) => (
        <div key={shot.slug} className="rounded border border-neutral-800">
          <button
            onClick={() => setOpen(open === shot.slug ? null : shot.slug)}
            className="flex w-full items-center gap-3 p-3 text-left"
          >
            <span className={shot.ok ? "text-emerald-400" : "text-red-400"}>
              {shot.ok ? "✓" : "✗"}
            </span>
            <span className="font-mono text-sm">{shot.slug}</span>
            {shot.attempts > 1 && (
              <span className="text-xs text-amber-400">
                {shot.attempts} attempts
              </span>
            )}
            {!shot.ok && (
              <span className="text-xs text-red-300">{shot.reason}</span>
            )}
          </button>

          {open === shot.slug && (
            <div className="space-y-3 border-t border-neutral-800 p-3">
              <div className="flex gap-2 overflow-x-auto">
                {shot.probe_pngs.map((png) => (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    key={png}
                    src={`${process.env.NEXT_PUBLIC_WORKER_URL || "http://127.0.0.1:8000"}/videos/${png}`}
                    alt={png}
                    className="h-32 rounded"
                  />
                ))}
              </div>
              <pre className="overflow-x-auto rounded bg-neutral-950 p-3 text-xs">
                <code>
                  {shot.js || "// no code retained for a failed shot"}
                </code>
              </pre>
            </div>
          )}
        </div>
      ))}
    </section>
  );
}
