"use client";

import { useState, useEffect } from "react";
import { Sliders, Mic, ShieldAlert, Loader2, Save, X } from "lucide-react";

type VoiceProfile = {
  id: string;
  name: string;
  prompt: string;
  blocklist: string[];
};

type ConfigData = {
  activeProfileId: string;
  profiles: VoiceProfile[];
};

const DEFAULT_PROFILES: VoiceProfile[] = [
  {
    id: "teenage_boy",
    name: "Teenage Boy",
    prompt: "You are a humorous and energetic teenage boy. Make the script catchy, informative, and easy to digest. It should be bite-sized but medium length (around 3 to 5 minutes). Explains what happened and why it's interesting — never what the reader should do.",
    blocklist: ["buy", "sell", "accumulate", "target price", "multibagger", "sure shot"]
  },
  {
    id: "teenage_girl",
    name: "Teenage Girl",
    prompt: "You are a humorous and energetic teenage girl. Make the script catchy, informative, and easy to digest. It should be bite-sized but medium length (around 3 to 5 minutes). Explains what happened and why it's interesting — never what the reader should do.",
    blocklist: ["buy", "sell", "accumulate", "target price", "multibagger", "sure shot"]
  },
  {
    id: "adult_male",
    name: "Adult Casual Male",
    prompt: "You are a casual, humorous, and informative adult male. Make the script catchy, informative, and easy to digest. It should be bite-sized but medium length (around 3 to 5 minutes). Explains what happened and why it's interesting — never what the reader should do.",
    blocklist: ["buy", "sell", "accumulate", "target price", "multibagger", "sure shot"]
  },
  {
    id: "adult_female",
    name: "Adult Casual Female",
    prompt: "You are a casual, humorous, and informative adult female. Make the script catchy, informative, and easy to digest. It should be bite-sized but medium length (around 3 to 5 minutes). Explains what happened and why it's interesting — never what the reader should do.",
    blocklist: ["buy", "sell", "accumulate", "target price", "multibagger", "sure shot"]
  },
  {
    id: "baby",
    name: "Baby",
    prompt: "You are a humorous, highly intelligent baby. Make the script catchy, informative, and easy to digest. It should be bite-sized but medium length (around 3 to 5 minutes). Explains what happened and why it's interesting — never what the reader should do.",
    blocklist: ["buy", "sell", "accumulate", "target price", "multibagger", "sure shot"]
  }
];

export default function SettingsPage() {
  const [config, setConfig] = useState<ConfigData | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // Form state for active profile
  const [activeProfileId, setActiveProfileId] = useState<string>("");
  const [prompt, setPrompt] = useState("");
  const [blocklist, setBlocklist] = useState<string[]>([]);
  const [newWord, setNewWord] = useState("");

  useEffect(() => {
    fetch("http://localhost:8000/config/voice_profiles")
      .then(res => {
        if (!res.ok) throw new Error("Not found");
        return res.json();
      })
      .then((data: ConfigData) => {
        setConfig(data);
        const active = data.profiles.find(p => p.id === data.activeProfileId) || data.profiles[0];
        setActiveProfileId(active.id);
        setPrompt(active.prompt);
        setBlocklist(active.blocklist);
      })
      .catch(() => {
        // Init with defaults
        const defaultData = {
          activeProfileId: "adult_male",
          profiles: DEFAULT_PROFILES
        };
        setConfig(defaultData);
        setActiveProfileId("adult_male");
        setPrompt(DEFAULT_PROFILES.find(p => p.id === "adult_male")?.prompt || "");
        setBlocklist(DEFAULT_PROFILES.find(p => p.id === "adult_male")?.blocklist || []);
      })
      .finally(() => setLoading(false));
  }, []);

  const handleProfileSwitch = (id: string) => {
    if (!config) return;
    // Save current form state to the old active profile before switching
    const updatedProfiles = config.profiles.map(p => 
      p.id === activeProfileId ? { ...p, prompt, blocklist } : p
    );
    
    const newActive = updatedProfiles.find(p => p.id === id);
    if (!newActive) return;

    setConfig({ ...config, profiles: updatedProfiles });
    setActiveProfileId(id);
    setPrompt(newActive.prompt);
    setBlocklist(newActive.blocklist);
  };

  const handleAddWord = (e: React.FormEvent) => {
    e.preventDefault();
    if (newWord.trim() && !blocklist.includes(newWord.trim().toLowerCase())) {
      setBlocklist([...blocklist, newWord.trim().toLowerCase()]);
      setNewWord("");
    }
  };

  const handleRemoveWord = (word: string) => {
    setBlocklist(blocklist.filter(w => w !== word));
  };

  const handleSave = async () => {
    if (!config) return;
    setSaving(true);
    
    const updatedProfiles = config.profiles.map(p => 
      p.id === activeProfileId ? { ...p, prompt, blocklist } : p
    );
    
    const payload: ConfigData = {
      activeProfileId,
      profiles: updatedProfiles
    };

    try {
      await fetch("http://localhost:8000/config/voice_profiles", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      setConfig(payload);
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
          <p className="text-foreground/60 mt-1">Manage your brand's voice profiles, prompts, and system settings.</p>
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
        {/* Voice Profile Card */}
        <div className="glass-panel p-6 rounded-2xl border-foreground/5 relative group">
          <div className="absolute inset-0 border border-primary/0 group-hover:border-primary/20 rounded-2xl transition-colors duration-500 pointer-events-none"></div>
          
          <div className="flex items-center space-x-3 mb-6">
            <div className="w-10 h-10 rounded-lg bg-primary/20 flex items-center justify-center text-primary">
              <Mic className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-foreground">Active Voice Profile</h2>
              <p className="text-xs text-foreground/50">Select and tune the personality of the AI scriptwriter.</p>
            </div>
          </div>
          
          <div className="space-y-6">
            <div>
              <label className="block text-sm font-bold text-foreground/70 mb-2 uppercase tracking-wider">Profile Preset</label>
              <select 
                value={activeProfileId}
                onChange={(e) => handleProfileSwitch(e.target.value)}
                className="w-full bg-black/40 border border-foreground/10 rounded-xl px-4 py-3 text-foreground focus:outline-none focus:border-primary/50 transition-colors"
              >
                {config?.profiles.map(p => (
                  <option key={p.id} value={p.id}>{p.name}</option>
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
            <div className="flex flex-wrap gap-2">
              {blocklist.map(word => (
                <span key={word} className="flex items-center space-x-1 px-3 py-1 rounded-full bg-destructive/10 border border-destructive/20 text-destructive text-xs font-mono">
                  <span>{word}</span>
                  <button onClick={() => handleRemoveWord(word)} className="hover:text-foreground transition-colors ml-1" title="Remove word">
                    <X className="w-3 h-3" />
                  </button>
                </span>
              ))}
              {blocklist.length === 0 && <span className="text-sm text-foreground/40 italic">No blocked words.</span>}
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

