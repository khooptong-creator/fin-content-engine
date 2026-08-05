"use client";

import { useEffect, useState } from "react";

export type ChannelOption = { id: string; display_name: string };

type ChannelsConfig = Record<string, { display_name?: string }>;

/**
 * Load the configured channels from the worker.
 *
 * There is deliberately no fallback list and no default selection: a video
 * generated under the wrong channel comes out in the wrong voice, and nothing
 * downstream catches it. If the config cannot be read, callers get an empty
 * list and an error to show, not a guess.
 */
export function useChannels() {
  const [channels, setChannels] = useState<ChannelOption[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    fetch("/api/config/channels", { cache: "no-store" })
      .then(async (res) => {
        if (!res.ok) {
          throw new Error(
            res.status === 404
              ? "No channels configured yet — seed them in Settings."
              : `Could not load channels (${res.status}).`,
          );
        }
        return (await res.json()) as ChannelsConfig;
      })
      .then((data) => {
        if (cancelled) return;
        setChannels(
          Object.entries(data ?? {}).map(([id, c]) => ({
            id,
            display_name: c?.display_name || id,
          })),
        );
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Could not load channels.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return { channels, error, loading };
}

/** Read a FastAPI error body into something worth showing a human. */
export async function readErrorDetail(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    const detail = body?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length > 0) {
      // 422 validation errors arrive as a list of {loc, msg}.
      return detail.map((d: { msg?: string }) => d?.msg).filter(Boolean).join("; ") || fallback;
    }
  } catch {
    // Body was not JSON. Fall through.
  }
  return `${fallback} (${res.status})`;
}

export default function ChannelSelect({
  value,
  onChange,
  channels,
  disabled,
  className = "",
}: {
  value: string;
  onChange: (id: string) => void;
  channels: ChannelOption[];
  disabled?: boolean;
  className?: string;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      aria-label="Channel"
      className={`rounded-xl border border-border bg-background px-3 py-2 text-sm text-foreground focus:border-primary/40 focus:outline-none transition-all disabled:opacity-40 ${className}`}
    >
      <option value="">Choose a channel…</option>
      {channels.map((c) => (
        <option key={c.id} value={c.id}>
          {c.display_name}
        </option>
      ))}
    </select>
  );
}
