import { Code2, Server, Terminal, Wrench } from "lucide-react";

export default function DocsPage() {
  return (
    <div className="space-y-8 max-w-5xl pb-10">
      <header className="pb-4 border-b border-foreground/5">
        <h1 className="text-3xl font-bold tracking-tight text-foreground">Documentation & Runbook</h1>
        <p className="text-foreground/60 mt-1">Everything you need to know about The Cockpit and Fin-Content Engine.</p>
      </header>

      <div className="space-y-12">
        {/* Section 1: How to Use */}
        <section className="space-y-4">
          <div className="flex items-center space-x-3 text-primary">
            <Terminal className="w-6 h-6" />
            <h2 className="text-2xl font-bold text-foreground">How to Use the Pipeline</h2>
          </div>
          <div className="glass-panel p-6 rounded-2xl border-foreground/5 space-y-4">
            <p className="text-foreground/80 leading-relaxed">
              The GUI acts as a centralized dashboard to review and trigger video renders. Currently, generation operates in a <strong>manual-first workflow</strong>:
            </p>
            <ol className="list-decimal list-inside space-y-3 text-foreground/80 ml-2">
              <li>
                <strong>Inbox:</strong> View financial stories parsed by the Python worker.
              </li>
              <li>
                <strong>Drafts Queue:</strong> Review the auto-generated scripts and storyboards. The AI uses the <code className="bg-black/10 dark:bg-foreground/10 px-1 py-0.5 rounded text-sm">daisy-days</code> aesthetic profile (minimal, clean, descriptive animations).
              </li>
              <li>
                <strong>Generate YouTube Video:</strong> Clicking this dispatches a job to the local <code className="bg-black/10 dark:bg-foreground/10 px-1 py-0.5 rounded text-sm">/youtube/generate</code> endpoint on the FastAPI worker.
              </li>
              <li>
                <strong>Output:</strong> The worker orchestrates Hyperframes (rendering engine) and outputs an MP4 file into the <code className="bg-black/10 dark:bg-foreground/10 px-1 py-0.5 rounded text-sm">../videos</code> directory on your VPS. You can then download and upload it to YouTube manually.
              </li>
            </ol>
          </div>
        </section>

        {/* Section 2: Architecture & Stack */}
        <section className="space-y-4">
          <div className="flex items-center space-x-3 text-primary">
            <Server className="w-6 h-6" />
            <h2 className="text-2xl font-bold text-foreground">Architecture & Stack</h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="glass-panel p-6 rounded-2xl border-foreground/5">
              <h3 className="text-lg font-bold text-foreground mb-3 flex items-center">
                <Code2 className="w-5 h-5 mr-2 text-accent" />
                Frontend (GUI)
              </h3>
              <ul className="space-y-2 text-sm text-foreground/70">
                <li><strong>Framework:</strong> Next.js 16 (App Router)</li>
                <li><strong>Styling:</strong> Tailwind CSS v4</li>
                <li><strong>Theme:</strong> <code className="bg-black/10 dark:bg-foreground/10 px-1 py-0.5 rounded">next-themes</code> (Light/Dark mode)</li>
                <li><strong>Icons:</strong> Lucide React</li>
              </ul>
            </div>
            <div className="glass-panel p-6 rounded-2xl border-foreground/5">
              <h3 className="text-lg font-bold text-foreground mb-3 flex items-center">
                <Server className="w-5 h-5 mr-2 text-accent" />
                Backend (Worker)
              </h3>
              <ul className="space-y-2 text-sm text-foreground/70">
                <li><strong>Framework:</strong> FastAPI (Python 3.12+)</li>
                <li><strong>Scheduling:</strong> APScheduler</li>
                <li><strong>Database:</strong> SQLite</li>
                <li><strong>Rendering:</strong> Hyperframes CLI (requires Node.js v20+)</li>
              </ul>
            </div>
          </div>
        </section>

        {/* Section 3: Troubleshooting */}
        <section className="space-y-4">
          <div className="flex items-center space-x-3 text-primary">
            <Wrench className="w-6 h-6" />
            <h2 className="text-2xl font-bold text-foreground">Troubleshooting</h2>
          </div>
          <div className="glass-panel p-6 rounded-2xl border-foreground/5 space-y-6">
            
            <div className="space-y-2">
              <h3 className="text-md font-bold text-destructive">Infinite Refresh Loop / ChunkLoadError (GUI)</h3>
              <p className="text-sm text-foreground/70 leading-relaxed">
                If the Next.js development server keeps reloading the page infinitely and throwing a <code className="bg-black/10 dark:bg-foreground/10 px-1 py-0.5 rounded">ChunkLoadError</code> in the console, it is due to a caching bug in Next.js Turbopack.
              </p>
              <div className="p-3 bg-black/5 dark:bg-black/40 rounded-lg border border-foreground/5 font-mono text-xs text-foreground/80">
                1. Stop the Next.js server (Ctrl+C)<br/>
                2. Run: rm -rf .next<br/>
                3. Restart: npm run dev
              </div>
            </div>

            <div className="space-y-2">
              <h3 className="text-md font-bold text-destructive">Hyperframes Rendering Fails (Worker)</h3>
              <p className="text-sm text-foreground/70 leading-relaxed">
                If the backend Python script fails while calling <code className="bg-black/10 dark:bg-foreground/10 px-1 py-0.5 rounded">npx hyperframes render</code>, ensure your VPS is running Node v20+ and Playwright dependencies are installed:
              </p>
              <div className="p-3 bg-black/5 dark:bg-black/40 rounded-lg border border-foreground/5 font-mono text-xs text-foreground/80">
                cd /opt/fce<br/>
                npx playwright install-deps
              </div>
            </div>

          </div>
        </section>

      </div>
    </div>
  );
}

