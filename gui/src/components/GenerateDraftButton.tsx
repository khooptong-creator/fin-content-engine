"use client";

import { useState, useEffect } from "react";
import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";

export default function GenerateDraftButton({ storyId, channelId = "default" }: { storyId: string, channelId?: string }) {
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [success, setSuccess] = useState(false);
  const router = useRouter();

  useEffect(() => {
    let interval: NodeJS.Timeout;
    if (loading && !success) {
      // The hyperframes rendering takes about 100 seconds (1m 40s)
      // We fill up 1% every ~1 second to simulate progress.
      interval = setInterval(() => {
        setProgress(p => (p < 99 ? p + 1 : 99));
      }, 1000);
    }
    return () => clearInterval(interval);
  }, [loading, success]);

  const handleGenerate = async () => {
    setLoading(true);
    setProgress(0);
    try {
      const res = await fetch("/api/youtube/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ story_id: storyId, channel_id: channelId, upload_preference: "manual" }),
      });
      if (res.ok) {
        setProgress(100);
        setSuccess(true);
        router.push("/drafts");
      }
    } catch (err) {
      console.error(err);
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
    <button 
      onClick={handleGenerate}
      disabled={loading}
      className="relative overflow-hidden px-4 py-2 rounded-lg bg-foreground/10 text-foreground font-medium hover:bg-primary hover:text-foreground transition-all flex items-center space-x-2"
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
  );
}
