"use client";

import { useState, useEffect } from "react";
import { Sliders, Mic, ShieldAlert, Loader2, Save, X } from "lucide-react";

type ChannelConfig = {
  display_name: string;
  voice_key: string;
  script_prompt: string;
  extra_blocklist: string[];
};

type ChannelsConfig = Record<string, ChannelConfig>;

// Mirrors BASE_BLOCKLIST in worker/app/channels.py. Displayed read-only: these
// terms always apply and cannot be edited away from the GUI.
const BASE_BLOCKLIST = [
  "buy",
  "sell",
  "accumulate",
  "target price",
  "multibagger",
  "sure shot",
];

export default function SettingsPage() {
  const [channels, setChannels] = useState<ChannelsConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // Form state for the selected channel
  const [selectedChannel, setSelectedChannel] = useState<string>("");
  const [prompt, setPrompt] = useState("");
  const [blocklist, setBlocklist] = useState<string[]>([]);
  const [newWord, setNewWord] = useState("");

  useEffect(() => {
    fetch("http://localhost:8000/config/channels")
      .then((res) => {
        if (!res.ok) throw new Error("Not found");
        return res.json();
      })
      .then((data: ChannelsConfig) => {
        setChannels(data);
        const firstKey = Object.keys(data)[0] || "";
        setSelectedChannel(firstKey);
        if (firstKey) {
          setPrompt(data[firstKey].script_prompt);
          setBlocklist(data[firstKey].extra_blocklist);
        }
      })
      .catch(() => {
        setChannels({});
      })
      .finally(() => setLoading(false));
  }, []);

  const handleChannelSwitch = (key: string) => {
    if (!channels) return;
    // Save current form state to the old selected channel before switching
    const updatedChannels: ChannelsConfig = {
      ...channels,
      [selectedChannel]: { ...channels[selectedChannel], script_prompt: prompt, extra_blocklist: blocklist },
    };

    const next = updatedChannels[key];
    if (!next) return;

    setChannels(updatedChannels);
    setSelectedChannel(key);
    setPrompt(next.script_prompt);
    setBlocklist(next.extra_blocklist);
  };

  const handleAddWord = (e: React.FormEvent) => {
    e.preventDefault();
    if (newWord.trim() && !blocklist.includes(newWord.trim().toLowerCase())) {
      setBlocklist([...blocklist, newWord.trim().toLowerCase()]);
      setNewWord("");
    }
  };

  const handleRemoveWord = (word: string) => {
    setBlocklist(blocklist.filter((w) => w !== word));
  };

  const handleSave = async () => {
    if (!channels || !selectedChannel) return;
    setSaving(true);

    const payload: ChannelsConfig = {
      ...channels,
      [selectedChannel]: { ...channels[selectedChannel], script_prompt: prompt, extra_blocklist: blocklist },
    };

    try {
      await fetch("http://localhost:8000/config/channels", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setChannels(payload);
    } catch (err) {
      console.error(err);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-5xl">
      <header className="pb-4 border-b border-foreground/5 flex justify-between items-end">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-foreground">Voice & Config</h1>
          <p className="text-foreground/60 mt-1">Manage your channels' voice, prompts, and compliance settings.</p>
        </div>
        <button
          onClick={handleSave}
          disabled={saving}
          className="premium-hover flex items-center space-x-2 px-6 py-2 bg-primary/20 text-primary rounded-xl font-medium border border-primary/30"
        >
          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
          <span>{saving ? "Saving..." : "Save Configuration"}</span>
        </button>
      </header>

      <div className="grid grid-cols-1 gap-6">
        {/* Channel Card */}
        <div className="glass-panel p-6 rounded-2xl border-foreground/5 relative group">
          <div className="absolute inset-0 border border-primary/0 group-hover:border-primary/20 rounded-2xl transition-colors duration-500 pointer-events-none"></div>

          <div className="flex items-center space-x-3 mb-6">
            <div className="w-10 h-10 rounded-lg bg-primary/20 flex items-center justify-center text-primary">
              <Mic className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-foreground">Channel</h2>
              <p className="text-xs text-foreground/50">Select and tune the personality of the AI scriptwriter per channel.</p>
            </div>
          </div>

          <div className="space-y-6">
            <div>
              <label className="block text-sm font-bold text-foreground/70 mb-2 uppercase tracking-wider">Channel</label>
              <select
                value={selectedChannel}
                onChange={(e) => handleChannelSwitch(e.target.value)}
                className="w-full bg-black/40 border border-foreground/10 rounded-xl px-4 py-3 text-foreground focus:outline-none focus:border-primary/50 transition-colors"
              >
                {channels &&
                  Object.entries(channels).map(([key, c]) => (
                    <option key={key} value={key}>
                      {c.display_name}
                    </option>
                  ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-bold text-foreground/70 mb-2 uppercase tracking-wider">System Prompt Instructions</label>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                className="w-full h-32 bg-black/40 border border-foreground/10 rounded-xl p-4 text-foreground/90 font-mono text-sm leading-relaxed focus:outline-none focus:border-primary/50 transition-colors resize-none"
              />
            </div>
          </div>
        </div>

        {/* Compliance Card */}
        <div className="glass-panel p-6 rounded-2xl border-foreground/5 relative group">
          <div className="absolute inset-0 border border-destructive/0 group-hover:border-destructive/20 rounded-2xl transition-colors duration-500 pointer-events-none"></div>

          <div className="flex items-center space-x-3 mb-6">
            <div className="w-10 h-10 rounded-lg bg-destructive/20 flex items-center justify-center text-destructive">
              <ShieldAlert className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-foreground">Compliance Guardrails</h2>
              <p className="text-xs text-foreground/50">L1 Regex Blocklist Active</p>
            </div>
          </div>

          <div className="space-y-6">
            <div>
              <label className="block text-sm font-bold text-foreground/70 mb-2 uppercase tracking-wider">
                Always blocked (not editable)
              </label>
              <div className="flex flex-wrap gap-2 opacity-70">
                {BASE_BLOCKLIST.map((term) => (
                  <span key={term} className="px-3 py-1 rounded-full bg-foreground/10 border border-foreground/10 text-foreground/60 text-xs font-mono">
                    {term}
                  </span>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-sm font-bold text-foreground/70 mb-2 uppercase tracking-wider">Extra blocked words</label>
              <div className="flex flex-wrap gap-2">
                {blocklist.map((word) => (
                  <span key={word} className="flex items-center space-x-1 px-3 py-1 rounded-full bg-destructive/10 border border-destructive/20 text-destructive text-xs font-mono">
                    <span>{word}</span>
                    <button onClick={() => handleRemoveWord(word)} className="hover:text-foreground transition-colors ml-1" title="Remove word">
                      <X className="w-3 h-3" />
                    </button>
                  </span>
                ))}
                {blocklist.length === 0 && <span className="text-sm text-foreground/40 italic">No extra blocked words.</span>}
              </div>
            </div>

            <form onSubmit={handleAddWord} className="flex space-x-2">
              <input
                type="text"
                value={newWord}
                onChange={(e) => setNewWord(e.target.value)}
                placeholder="Add new word to block..."
                className="flex-1 bg-black/40 border border-foreground/10 rounded-xl px-4 py-2 text-sm text-foreground focus:outline-none focus:border-destructive/50 transition-colors"
              />
              <button type="submit" className="px-4 py-2 bg-foreground/5 hover:bg-foreground/10 border border-foreground/10 rounded-xl text-sm font-medium transition-colors">
                Add Word
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}
