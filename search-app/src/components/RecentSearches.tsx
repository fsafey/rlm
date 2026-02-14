import type { LogEntry } from "@/lib/useSearchHistory";
import { Clock, Loader2, X } from "lucide-react";

interface RecentSearchesProps {
  logs: LogEntry[];
  onSelect: (searchId: string) => void;
  onDelete: (searchId: string) => void;
  loading: boolean;
}

export function RecentSearches({
  logs,
  onSelect,
  onDelete,
  loading,
}: RecentSearchesProps) {
  if (logs.length === 0) return null;

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-medium text-muted-foreground flex items-center gap-2">
        {loading ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <Clock className="h-3.5 w-3.5" />
        )}
        Recent Searches
      </h3>
      <div className="space-y-2">
        {logs.map((log) => (
          <div
            key={log.filename}
            className="group relative w-full text-left rounded-lg border border-border bg-card p-3 hover:border-foreground/20 transition-colors"
          >
            <button
              onClick={() => onSelect(log.search_id)}
              disabled={loading}
              className="w-full text-left cursor-pointer disabled:opacity-50"
            >
              <p className="text-sm line-clamp-2 pr-6">{log.query}</p>
              <div className="flex items-center gap-2 mt-1.5">
                <span className="text-[10px] text-muted-foreground font-mono">
                  {log.search_id}
                </span>
                {log.timestamp && (
                  <span className="text-[10px] text-muted-foreground">
                    {formatTimestamp(log.timestamp)}
                  </span>
                )}
                {log.root_model && (
                  <span className="text-[10px] rounded-full px-1.5 py-0.5 bg-secondary text-secondary-foreground">
                    {log.root_model}
                  </span>
                )}
              </div>
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDelete(log.search_id);
              }}
              disabled={loading}
              className="absolute top-2 right-2 p-1 rounded-md opacity-0 group-hover:opacity-100 hover:bg-destructive/10 hover:text-destructive transition-all disabled:opacity-0"
              aria-label="Delete search"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function formatTimestamp(ts: string): string {
  try {
    const d = new Date(ts);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return "just now";
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHrs = Math.floor(diffMins / 60);
    if (diffHrs < 24) return `${diffHrs}h ago`;
    const diffDays = Math.floor(diffHrs / 24);
    return `${diffDays}d ago`;
  } catch {
    return ts;
  }
}
