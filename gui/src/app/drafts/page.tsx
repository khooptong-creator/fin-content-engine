"use client";

import { useState, useEffect } from "react";
import { Check, Loader2, PlayCircle, Settings2, Share2, Video, FileText, PlaySquare, Download } from "lucide-react";
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export default function DraftsPage() {
  const [drafts, setDrafts] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/drafts", { cache: "no-store" })
      .then((res) => res.json())
      .then((data) => {
        setDrafts(data);
        setLoading(false);
      })
      .catch((err) => {
        console.error(err);
        setLoading(false);
      });
  }, []);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-[50vh] space-y-4">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
        <p className="text-foreground/50 tracking-widest uppercase text-xs font-bold animate-pulse">Syncing Database...</p>
      </div>
    );
  }

  return (
    <div className="space-y-8 max-w-6xl mx-auto">
      <header className="pb-6 border-b border-border flex justify-between items-end">
        <div>
          <h1 className="text-4xl font-black tracking-tight text-foreground">Drafts Queue</h1>
          <p className="text-foreground/50 mt-2 font-medium tracking-wide">Review your AI-generated drafts and rendered videos before publishing.</p>
        </div>
      </header>

      {drafts.length === 0 ? (
        <div className="p-16 text-center flex flex-col items-center justify-center space-y-4 glass-panel rounded-3xl">
          <div className="w-20 h-20 rounded-full bg-foreground/5 flex items-center justify-center">
            <FileText className="w-10 h-10 text-foreground/20" />
          </div>
          <p className="text-foreground/50 font-medium tracking-wide text-lg">No drafts found. Generate a draft from the Inbox first.</p>
        </div>
      ) : (
        <div className="space-y-6 mt-8">
          {drafts.map((draft) => (
            <DraftCard key={draft.id} draft={draft} />
          ))}
        </div>
      )}
    </div>
  );
}

function DraftCard({ draft }: { draft: any }) {
  const [isPublishing, setIsPublishing] = useState(false);
  const [success, setSuccess] = useState(draft.status === "published");
  const [publishError, setPublishError] = useState<string | null>(null);
  const [publishUrl, setPublishUrl] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"overview" | "youtube">("overview");
  const [markdownContent, setMarkdownContent] = useState<string | null>(null);
  const [loadingMarkdown, setLoadingMarkdown] = useState(false);

  const handlePublish = async () => {
    setIsPublishing(true);
    setPublishError(null);
    try {
      const res = await fetch("/api/youtube/publish", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ draft_id: draft.id }),
      });
      const data = await res.json().catch(() => ({ detail: "Upload failed" }));
      if (!res.ok) {
        throw new Error(data.detail || `Upload failed (${res.status})`);
      }
      setSuccess(true);
      setPublishUrl(data.url || `https://youtube.com/watch?v=${data.video_id}`);
    } catch (err: any) {
      setPublishError(err.message || "Upload failed");
    } finally {
      setIsPublishing(false);
    }
  };

  const loadMarkdown = async () => {
    if (markdownContent) return;
    setLoadingMarkdown(true);
    try {
      const res = await fetch(`/api/videos/story-${draft.story_id}/STORYBOARD.md`);
      if (res.ok) {
        const text = await res.text();
        setMarkdownContent(text);
      } else {
        setMarkdownContent("Failed to load script. Either it hasn't been generated yet or the file is missing.");
      }
    } catch (e) {
      setMarkdownContent("Error fetching script.");
    } finally {
      setLoadingMarkdown(false);
    }
  };

  useEffect(() => {
    if (activeTab === "youtube") {
      loadMarkdown();
    }
  }, [activeTab]);

  const draftBody = draft.body || {};
  const filePath = draftBody.file_path || "Unknown path";

  const audioUrl = `/api/videos/story-${draft.story_id}/audio.mp3`;
  const storyboardUrl = `/api/videos/story-${draft.story_id}/STORYBOARD.md`;

  return (
    <div className="glass-panel rounded-3xl overflow-hidden shadow-2xl border-border transition-all duration-300 hover:border-primary/30 group">
      {/* Card Header */}
      <div className="p-6 md:p-8 border-b border-border bg-foreground/[0.01] flex justify-between items-start relative overflow-hidden">
        <div className="absolute top-0 left-0 w-1 h-full bg-primary/50 group-hover:bg-primary transition-colors" />
        <div>
          <div className="flex items-center space-x-4 mb-3">
            <span className={`px-2.5 py-1 text-[10px] font-black rounded-md uppercase tracking-widest ${
              success ? "bg-green-500/10 text-green-400 border border-green-500/20" : "bg-primary/10 text-primary border border-primary/20 shadow-[0_0_10px_rgba(59,130,246,0.2)]"
            }`}>
              {success ? "Published" : "Approved"}
            </span>
            <span className="text-foreground/40 text-xs font-mono tracking-wider">ID: {draft.id.substring(0, 8)}</span>
          </div>
          <h2 className="text-2xl md:text-3xl font-bold text-foreground tracking-tight leading-snug">{draft.headline || "Untitled Story"}</h2>
        </div>
        <div className="flex space-x-2">
          <button className="p-2.5 rounded-xl bg-foreground/5 hover:bg-foreground/10 text-foreground/50 hover:text-foreground transition-colors border border-transparent hover:border-border">
            <Settings2 className="w-5 h-5" />
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-border px-6 md:px-8 bg-foreground/[0.02]">
        <button 
          onClick={() => setActiveTab("overview")}
          className={`py-4 px-6 text-sm font-bold tracking-wider uppercase border-b-2 transition-colors ${
            activeTab === "overview" ? "border-primary text-primary" : "border-transparent text-foreground/50 hover:text-foreground"
          }`}
        >
          Overview
        </button>
        <button 
          onClick={() => setActiveTab("youtube")}
          className={`py-4 px-6 text-sm font-bold tracking-wider uppercase border-b-2 transition-colors flex items-center space-x-2 ${
            activeTab === "youtube" ? "border-[#ff0000] text-[#ff0000]" : "border-transparent text-foreground/50 hover:text-foreground"
          }`}
        >
          <PlaySquare className="w-4 h-4" />
          <span>YouTube Package</span>
        </button>
      </div>

      {/* Card Body */}
      <div className="p-6 md:p-8">
        {activeTab === "overview" && (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8 md:gap-12">
            {/* Draft Content (Left 2/3) */}
            <div className="md:col-span-2 space-y-6">
              <div>
                <h3 className="text-xs font-black text-foreground/40 uppercase tracking-[0.2em] mb-3">Video Render Details</h3>
                <div className="p-5 rounded-2xl bg-black/60 border border-border shadow-inner text-foreground/80 font-mono text-[13px] leading-relaxed space-y-3">
                  <div className="flex items-start">
                    <span className="text-primary font-bold mr-2 w-24 flex-shrink-0">File:</span> 
                    <span className="break-all text-foreground/60">{filePath}</span>
                  </div>
                  <div className="flex items-start">
                    <span className="text-accent font-bold mr-2 w-24 flex-shrink-0">Config:</span> 
                    <span className="text-foreground/60">{draft.upload_preference}</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Action Panel (Right 1/3) */}
            <div className="space-y-4">
              <h3 className="text-xs font-black text-foreground/40 uppercase tracking-[0.2em] mb-3">Production</h3>
              
              <div className="p-6 rounded-2xl border border-primary/20 bg-primary/5 flex flex-col items-center text-center space-y-4 shadow-[inset_0_0_20px_rgba(59,130,246,0.02)]">
                <div className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center text-primary mb-2 shadow-[0_0_15px_rgba(59,130,246,0.2)]">
                  <Video className="w-7 h-7" />
                </div>
                <div>
                  <h4 className="text-foreground font-bold tracking-wide">Rendered Successfully</h4>
                  <p className="text-[11px] text-foreground/50 mt-1 uppercase tracking-wider font-semibold">Ready for YouTube</p>
                </div>
                
                <button 
                  onClick={handlePublish}
                  disabled={isPublishing || success}
                  className={`w-full mt-4 py-3.5 px-4 rounded-xl font-bold tracking-wide flex items-center justify-center space-x-2 transition-all duration-300 ${
                    success 
                      ? "bg-green-500/10 text-green-400 border border-green-500/20 shadow-none cursor-default" 
                      : isPublishing 
                        ? "bg-foreground/10 text-foreground/50 cursor-not-allowed border border-transparent"
                        : "bg-primary text-white hover:bg-primary/90 hover:shadow-[0_0_20px_rgba(59,130,246,0.4)] hover:-translate-y-0.5"
                  }`}
                >
                  {success ? (
                    <>
                      <Check className="w-5 h-5" />
                      <span>Published Live</span>
                    </>
                  ) : isPublishing ? (
                    <>
                      <Loader2 className="w-5 h-5 animate-spin" />
                      <span>Uploading...</span>
                    </>
                  ) : (
                    <>
                      <Share2 className="w-5 h-5" />
                      <span>Publish to YouTube</span>
                    </>
                  )}
                </button>

                {publishError && (
                  <div className="mt-4 p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm font-medium">
                    {publishError}
                  </div>
                )}

                {success && publishUrl && (
                  <a
                    href={publishUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-4 block w-full py-3 px-4 rounded-xl bg-green-500/10 border border-green-500/20 text-green-400 text-sm font-bold text-center hover:bg-green-500/20 transition-colors"
                  >
                    Open on YouTube →
                  </a>
                )}
              </div>
            </div>
          </div>
        )}

        {activeTab === "youtube" && (
          <div className="space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-500">
            {/* Audio Preview */}
            <div className="p-6 rounded-2xl border border-border bg-foreground/[0.01]">
              <h3 className="text-xs font-black text-foreground/40 uppercase tracking-[0.2em] mb-4 flex items-center">
                <PlayCircle className="w-4 h-4 mr-2" /> Voiceover Preview
              </h3>
              <audio controls className="w-full h-12 rounded-lg bg-background" src={audioUrl}>
                Your browser does not support the audio element.
              </audio>
            </div>

            {/* Download Assets */}
            <div className="flex space-x-4">
              <a href={storyboardUrl} target="_blank" rel="noreferrer" className="flex-1 p-4 rounded-xl border border-primary/20 bg-primary/5 hover:bg-primary/10 transition-colors flex items-center justify-between text-primary font-bold tracking-wide group">
                <span className="flex items-center"><FileText className="w-5 h-5 mr-3" /> Download Script</span>
                <Download className="w-5 h-5 opacity-50 group-hover:opacity-100 transition-opacity" />
              </a>
              <a href={audioUrl} target="_blank" rel="noreferrer" className="flex-1 p-4 rounded-xl border border-accent/20 bg-accent/5 hover:bg-accent/10 transition-colors flex items-center justify-between text-accent font-bold tracking-wide group">
                <span className="flex items-center"><PlayCircle className="w-5 h-5 mr-3" /> Download Audio</span>
                <Download className="w-5 h-5 opacity-50 group-hover:opacity-100 transition-opacity" />
              </a>
            </div>

            {/* Script Display */}
            <div className="space-y-4">
              <h3 className="text-xs font-black text-foreground/40 uppercase tracking-[0.2em]">Storyboard & Script</h3>
              <div className="p-6 md:p-8 rounded-3xl bg-background border border-border shadow-inner max-h-[600px] overflow-y-auto custom-scrollbar">
                {loadingMarkdown ? (
                  <div className="flex flex-col items-center justify-center h-32 space-y-4">
                    <Loader2 className="w-6 h-6 animate-spin text-primary" />
                    <span className="text-foreground/40 text-xs font-bold uppercase tracking-widest">Loading Script...</span>
                  </div>
                ) : (
                  <article className="prose prose-sm md:prose-base dark:prose-invert max-w-none prose-headings:font-black prose-a:text-primary">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {markdownContent || ""}
                    </ReactMarkdown>
                  </article>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
