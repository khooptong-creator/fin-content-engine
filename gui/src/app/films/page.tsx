"use client";

import { useEffect, useState } from "react";
import { Clapperboard, Loader2, Smartphone } from "lucide-react";

import FilmProgress from "@/components/FilmProgress";

type Story = { id: string; title: string };
type Mode = "short" | "film";

const MODES: { id: Mode; label: string; detail: string; icon: typeof Smartphone }[] = [
  {
    id: "short",
    label: "Short",
    detail: "2D · 1080×1920 portrait",
    icon: Smartphone,
  },
  {
    id: "film",
    label: "Story Film",
    detail: "3D · 1920×1080 landscape",
    icon: Clapperboard,
  },
];

export default function FilmsPage() {
  const [stories, setStories] = useState<Story[]>([]);
  const [storyId, setStoryId] = useState("");
  const [mode, setMode] = useState<Mode>("short");
  const [jobId, setJobId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/api/stories", { cache: "no-store" })
      .then((res) => res.json())
      .then((data) => setStories(Array.isArray(data) ? data : []))
      .catch(() => setStories([]));
  }, []);

  const generate = async () => {
    setBusy(true);
    setError("");
    setJobId("");
    try {
      const res = await fetch("/api/youtube/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ story_id: storyId, channel_id: "default", mode }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail ?? "Could not start the run.");
        return;
      }
      setJobId(data.job_id);
    } catch {
      setError("Could not reach the worker. Is it running on port 8000?");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-8 max-w-4xl mx-auto">
      <header className="pb-6 border-b border-border">
        <h1 className="text-4xl font-black tracking-tight text-foreground">Generate</h1>
        <p className="text-foreground/50 mt-2 font-medium tracking-wide">
          Pick a story, choose a format, and watch the pipeline work.
        </p>
      </header>

      <section className="glass-panel rounded-3xl p-6 space-y-6">
        <div className="space-y-2">
          <label className="text-[10px] font-bold uppercase tracking-[0.2em] text-foreground/40">
            Story
          </label>
          <select
            value={storyId}
            onChange={(e) => setStoryId(e.target.value)}
            className="w-full rounded-xl border border-border bg-background px-4 py-3 text-foreground focus:border-primary/40 focus:outline-none transition-all"
          >
            <option value="">Select a story…</option>
            {stories.map((story) => (
              <option key={story.id} value={story.id}>
                {story.title}
              </option>
            ))}
          </select>
          {stories.length === 0 && (
            <p className="text-xs text-foreground/40">
              No stories yet — ingest some from the Inbox first.
            </p>
          )}
        </div>

        <div className="space-y-2">
          <label className="text-[10px] font-bold uppercase tracking-[0.2em] text-foreground/40">
            Format
          </label>
          <div className="grid grid-cols-2 gap-3">
            {MODES.map((option) => {
              const active = mode === option.id;
              return (
                <button
                  key={option.id}
                  onClick={() => setMode(option.id)}
                  className={`flex items-start space-x-3 rounded-2xl border p-4 text-left transition-all ${
                    active
                      ? "border-primary/30 bg-primary/10"
                      : "border-border bg-foreground/[0.02] hover:bg-foreground/[0.04]"
                  }`}
                >
                  <option.icon
                    className={`w-5 h-5 mt-0.5 ${active ? "text-primary" : "text-foreground/30"}`}
                  />
                  <div>
                    <p className="font-bold tracking-wide text-foreground">{option.label}</p>
                    <p className="text-xs text-foreground/40 font-mono mt-0.5">{option.detail}</p>
                  </div>
                </button>
              );
            })}
          </div>
          {mode === "film" && (
            <p className="text-xs text-amber-400/80">
              The 3D backend is not built yet — this will fail until it lands.
            </p>
          )}
        </div>

        <button
          onClick={generate}
          disabled={!storyId || busy}
          className="flex items-center space-x-2 rounded-xl bg-primary px-5 py-3 font-semibold text-foreground transition-all hover:opacity-90 disabled:opacity-30 disabled:cursor-not-allowed"
        >
          {busy && <Loader2 className="w-4 h-4 animate-spin" />}
          <span>{busy ? "Starting…" : "Generate →"}</span>
        </button>

        {error && <p className="text-sm text-red-400">{error}</p>}
      </section>

      {jobId && <FilmProgress jobId={jobId} />}
    </div>
  );
}
