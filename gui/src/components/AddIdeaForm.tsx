"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";

import ChannelSelect, { readErrorDetail, useChannels } from "@/components/ChannelSelect";

/**
 * Add a manual story idea.
 *
 * A story is filed against a channel at creation, because that is what decides
 * the voice it will eventually be generated in. The worker requires it
 * (`POST /stories/manual` -> 422 without one), and this form used to send the
 * headline alone inside a server action that discarded the response, so every
 * submit failed in silence.
 */
export default function AddIdeaForm() {
  const { channels, error: channelsError } = useChannels();
  const [headline, setHeadline] = useState("");
  const [channelId, setChannelId] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const router = useRouter();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!headline.trim() || !channelId) return;

    setSaving(true);
    setError("");
    try {
      const res = await fetch("/api/stories/manual", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ headline: headline.trim(), channel_id: channelId }),
      });
      if (!res.ok) {
        setError(await readErrorDetail(res, "Could not add the idea"));
        return;
      }
      setHeadline("");
      router.refresh();
    } catch {
      setError("Could not reach the worker. Is it running on port 8000?");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col items-end space-y-2">
      <div className="flex items-center space-x-2">
        <input
          type="text"
          name="headline"
          value={headline}
          onChange={(e) => setHeadline(e.target.value)}
          placeholder="Enter Original Idea..."
          required
          className="px-4 py-2.5 rounded-xl border border-border bg-background text-base text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 w-80 shadow-sm"
        />
        <ChannelSelect
          value={channelId}
          onChange={(id) => {
            setChannelId(id);
            setError("");
          }}
          channels={channels}
          disabled={saving}
          className="py-2.5"
        />
        <button
          type="submit"
          disabled={saving || !channelId || !headline.trim()}
          className="flex items-center space-x-2 px-4 py-2.5 bg-primary/10 text-primary font-bold text-base rounded-xl hover:bg-primary/20 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {saving && <Loader2 className="w-4 h-4 animate-spin" />}
          <span>Add Idea</span>
        </button>
      </div>
      {(error || channelsError) && (
        <p className="text-xs text-red-400 max-w-md text-right">{error || channelsError}</p>
      )}
    </form>
  );
}
