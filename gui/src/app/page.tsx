import { Calendar, TrendingUp, Users, Video, FileText, Inbox } from "lucide-react";
import AddIdeaForm from "@/components/AddIdeaForm";
import GenerateDraftButton from "@/components/GenerateDraftButton";

export default async function Home() {
  let stories = [];
  let analytics = {};
  
  try {
    const res = await fetch("http://127.0.0.1:8000/stories", { cache: "no-store" });
    if (res.ok) {
      stories = await res.json();
    }
    const analyticsRes = await fetch("http://127.0.0.1:8000/youtube/analytics", { cache: "no-store" });
    if (analyticsRes.ok) {
      analytics = await analyticsRes.json();
    }
  } catch (error) {
    console.error("Failed to fetch data from backend:", error);
  }
  return (
    <div className="space-y-8 max-w-7xl mx-auto">
      <header className="flex justify-between items-end pb-6 border-b border-border">
        <div>
          <h1 className="text-4xl font-black tracking-tight text-foreground">Inbox Overview</h1>
          <p className="text-foreground/50 mt-2 font-medium tracking-wide">Your content queue and analytics for today.</p>
        </div>
        <div className="flex items-center space-x-4">
          <div className="px-5 py-2.5 glass-panel rounded-xl text-sm text-foreground/80 font-medium shadow-inner">
            <span className="text-primary font-bold mr-2 text-lg drop-shadow-[0_0_8px_rgba(59,130,246,0.8)]">{stories.length}</span> 
            Stories pending
          </div>
        </div>
      </header>

      {/* Analytics Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {[
          { title: "Total Impressions", value: "2.4M", icon: Users, trend: "+12%" },
          { title: "Drafts Created", value: "12", icon: FileText, trend: "+3" },
          { title: "Videos Rendered", value: "4", icon: Video, trend: "Steady" },
          { title: "Upcoming (Scheduled)", value: "2", icon: Calendar, trend: "Next: 4pm" },
        ].map((stat, i) => (
          <div key={i} className="glass-panel p-6 rounded-2xl premium-hover cursor-default relative overflow-hidden group">
            <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
              <stat.icon className="w-16 h-16" />
            </div>
            <div className="relative z-10 flex flex-col h-full">
              <div className="flex items-center justify-between text-foreground/50 mb-4">
                <span className="text-[11px] font-bold uppercase tracking-[0.2em]">{stat.title}</span>
                <stat.icon className="w-4 h-4 text-primary" />
              </div>
              <div className="flex items-baseline space-x-3 mt-auto">
                <h2 className="text-4xl font-black text-foreground tracking-tighter drop-shadow-sm">{stat.value}</h2>
                <span className="text-xs text-green-400 font-bold bg-green-400/10 px-2 py-1 rounded-md">{stat.trend}</span>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Inbox Feed */}
      <div className="mt-10 glass-panel rounded-3xl overflow-hidden shadow-2xl">
        <div className="px-6 py-5 border-b border-border bg-foreground/[0.02] flex justify-between items-center">
          <h2 className="text-lg font-bold text-foreground tracking-wide">Pending Stories <span className="text-foreground/40 font-normal ml-2">Needs Draft</span></h2>
          <AddIdeaForm />
        </div>
        
        <div className="divide-y divide-border/50">
          {stories.length === 0 ? (
            <div className="p-12 text-center flex flex-col items-center justify-center space-y-4">
              <div className="w-16 h-16 rounded-full bg-foreground/5 flex items-center justify-center">
                <Inbox className="w-8 h-8 text-foreground/20" />
              </div>
              <p className="text-foreground/50 font-medium tracking-wide">No pending stories found.</p>
            </div>
          ) : (
            stories.map((story: any) => (
              <div key={story.id} className="p-6 hover:bg-foreground/[0.03] transition-colors flex items-center justify-between group">
                <div className="flex-1 pr-8">
                  <h3 className="text-foreground font-semibold text-xl tracking-tight leading-snug group-hover:text-primary transition-colors">{story.headline}</h3>
                  <div className="flex items-center space-x-4 mt-3 text-xs text-foreground/40 font-medium">
                    <span className="px-2.5 py-1 bg-accent/10 text-accent rounded-md border border-accent/20 uppercase tracking-widest text-[10px] font-bold">
                      {story.items && story.items.length > 0 ? story.items[0].source_name : "Unknown Source"}
                    </span>
                    <span className="flex items-center">
                      <Calendar className="w-3 h-3 mr-1.5 opacity-50" />
                      {new Date(story.created_at).toLocaleString()}
                    </span>
                  </div>
                </div>
                <div className="opacity-0 group-hover:opacity-100 transform translate-x-4 group-hover:translate-x-0 transition-all duration-300">
                  <GenerateDraftButton storyId={story.id} storyChannelId={story.channel_id} />
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Analytics Feed */}
      {Object.keys(analytics).length > 0 && (
        <div className="mt-10 glass-panel rounded-3xl overflow-hidden shadow-2xl">
          <div className="px-6 py-5 border-b border-border bg-foreground/[0.02] flex justify-between items-center">
            <h2 className="text-lg font-bold text-foreground tracking-wide">YouTube Analytics <span className="text-foreground/40 font-normal ml-2">Real-time</span></h2>
          </div>
          
          <div className="divide-y divide-border/50">
            {Object.entries(analytics).map(([id, stats]: [string, any]) => (
              <div key={id} className="p-6 hover:bg-foreground/[0.03] transition-colors flex items-center justify-between group">
                <div className="flex-1 pr-8">
                  <h3 className="text-foreground font-semibold text-lg tracking-tight leading-snug group-hover:text-primary transition-colors">{stats.title}</h3>
                  <div className="flex items-center space-x-6 mt-3 text-sm text-foreground/60 font-medium">
                    <span className="flex items-center text-primary/80">
                      <Users className="w-4 h-4 mr-2" />
                      {parseInt(stats.views).toLocaleString()} Views
                    </span>
                    <span className="flex items-center text-green-400">
                      <TrendingUp className="w-4 h-4 mr-2" />
                      {parseInt(stats.likes).toLocaleString()} Likes
                    </span>
                    <span className="flex items-center text-foreground/40">
                      <FileText className="w-4 h-4 mr-2" />
                      {parseInt(stats.comments).toLocaleString()} Comments
                    </span>
                  </div>
                </div>
                <div className="flex-shrink-0 text-right">
                   <a href={`https://youtube.com/watch?v=${id}`} target="_blank" rel="noreferrer" className="px-4 py-2 bg-foreground/5 text-foreground rounded-xl hover:bg-foreground/10 transition-colors text-sm font-bold">Watch</a>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

