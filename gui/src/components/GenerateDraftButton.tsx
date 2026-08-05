"use client";

import { useState, useEffect } from "react";
import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";

import ChannelSelect, { readErrorDetail, useChannels } from "@/components/ChannelSelect";

export default function GenerateDraftButton({
  storyId,
  storyChannelId,
}: {
  storyId: string;
  /**
   * The channel this story was filed under, if any. Used to preselect the
   * picker — it is the story's own value, not a system default. A story with
   * no channel forces an explicit choice before the button will fire.
   */
  storyChannelId?: string | null;
}) {
  const { channels, error: channelsError } = useChannels();
  const [channelId, setChannelId] = useState(storyChannelId ?? "");
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState("");
  const router = useRouter();

  useEffect(() => {
    let interval: NodeJS.Timeout;
    if (loading && !success) {
      // The hyperframes rendering takes about 100 seconds (1m 40s)
      // We fill up 1% every ~1 second to simulate progress.
      interval = setInterval(() => {
        setProgress((p) => (p < 99 ? p + 1 : 99));
      }, 1000);
    }
    return () => clearInterval(interval);
  }, [loading, success]);

  const handleGenerate = async () => {
    if (!channelId) {
      setError("Pick a channel first.");
      return;
    }
    setLoading(true);
    setProgress(0);
    setError("");
    try {
      const res = await fetch("/api/youtube/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          story_id: storyId,
          channel_id: channelId,
          upload_preference: "manual",
        }),
      });
      if (!res.ok) {
        // A rejected channel, a missing story, a failed render: all of these
        // used to vanish here and leave the button looking idle.
        setError(await readErrorDetail(res, "Generation failed"));
        return;
      }
      setProgress(100);
      setSuccess(true);
      router.push("/drafts");
    } catch {
      setError("Could not reach the worker. Is it running on port 8000?");
    } finally {
      // Small delay before turning off loading state if successful,
      // so the 100% is visible for a moment before the success state replaces it.
      setTimeout(() => setLoading(false), 500);
    }
  };

  if (success) {
    return (
      <button disabled className="px-4 py-2 rounded-lg bg-green-500/20 text-green-400 font-medium transition-all">
        Sent to Drafts!
      </button>
    );
  }

  return (
    <div className="flex flex-col items-end space-y-2">
      <div className="flex items-center space-x-2">
        <ChannelSelect
          value={channelId}
          onChange={(id) => {
            setChannelId(id);
            setError("");
          }}
          channels={channels}
          disabled={loading}
        />
        <button
          onClick={handleGenerate}
          disabled={loading || !channelId}
          className="relative overflow-hidden px-4 py-2 rounded-lg bg-foreground/10 text-foreground font-medium hover:bg-primary hover:text-foreground transition-all flex items-center space-x-2 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-foreground/10"
        >
          {loading && (
            <div
              className="absolute left-0 top-0 bottom-0 bg-primary/20 transition-all duration-1000 ease-linear"
              style={{ width: `${progress}%` }}
            />
          )}
          <div className="relative flex items-center space-x-2 z-10">
            {loading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Generating ({progress}%)</span>
              </>
            ) : (
              <span>Generate Draft →</span>
            )}
          </div>
        </button>
      </div>
      {(error || channelsError) && (
        <p className="text-xs text-red-400 max-w-sm text-right">{error || channelsError}</p>
      )}
    </div>
  );
}
