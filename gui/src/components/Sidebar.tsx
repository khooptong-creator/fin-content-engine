"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Inbox, FileText, Settings, BookOpen, Clapperboard } from "lucide-react";
import { ThemeToggle } from "./ThemeToggle";

export function Sidebar() {
  const pathname = usePathname();

  const navItems = [
    { name: "Inbox", href: "/", icon: Inbox },
    { name: "Generate", href: "/films", icon: Clapperboard },
    { name: "Drafts Queue", href: "/drafts", icon: FileText },
    { name: "Voice & Config", href: "/settings", icon: Settings },
    { name: "Documentation", href: "/docs", icon: BookOpen },
  ];

  return (
    <aside className="w-64 flex-shrink-0 glass-panel border-r border-border flex flex-col h-full sticky top-0 z-40 bg-background/50">
      <div className="p-8">
        <h1 className="text-2xl font-black tracking-tighter bg-clip-text text-transparent bg-gradient-to-r from-primary via-accent to-primary animate-pulse">
          THE COCKPIT
        </h1>
        <p className="text-[10px] text-foreground/40 mt-1 uppercase tracking-[0.3em] font-bold">Mission Control</p>
      </div>

      <nav className="flex-1 px-4 space-y-1 mt-4">
        {navItems.map((item) => {
          const isActive = pathname === item.href;
          return (
            <Link 
              key={item.href}
              href={item.href} 
              className={`flex items-center space-x-3 px-4 py-3 rounded-xl transition-all duration-300 group relative overflow-hidden ${
                isActive 
                  ? "text-foreground bg-primary/10 border border-primary/20 shadow-[inset_0_0_20px_rgba(59,130,246,0.05)]" 
                  : "text-foreground/50 hover:text-foreground hover:bg-foreground/[0.03]"
              }`}
            >
              {isActive && (
                <div className="absolute left-0 top-0 bottom-0 w-1 bg-primary" />
              )}
              <item.icon className={`w-5 h-5 transition-colors ${isActive ? "text-primary" : "group-hover:text-foreground/80"}`} />
              <span className={`font-semibold tracking-wide ${isActive ? "text-foreground" : ""}`}>{item.name}</span>
            </Link>
          );
        })}
      </nav>

      <div className="p-4 m-6 rounded-2xl bg-background border border-border shadow-inner flex flex-col space-y-4">
        <div className="flex items-center space-x-3">
          <div className="relative flex h-2.5 w-2.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.6)]"></span>
          </div>
          <div className="flex-1">
            <p className="text-xs font-bold text-foreground tracking-wide uppercase">System Online</p>
            <p className="text-[10px] text-foreground/40 font-mono mt-0.5">Latency: 14ms</p>
          </div>
        </div>
        <div className="pt-3 border-t border-border flex justify-between items-center">
          <span className="text-[10px] text-foreground/40 font-bold uppercase tracking-wider">Theme</span>
          <ThemeToggle />
        </div>
      </div>
    </aside>
  );
}

