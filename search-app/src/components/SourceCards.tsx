import type { SearchSource } from "@/lib/types";
import { FileText } from "lucide-react";

interface SourceCardsProps {
  sources: SearchSource[];
}

const PARENT_CODE_LABELS: Record<string, string> = {
  PT: "Prayer & Tahara",
  WP: "Worship Practices",
  MF: "Marriage & Family",
  FN: "Finance & Transactions",
  BE: "Beliefs & Ethics",
  OT: "Other Topics",
};

export function SourceCards({ sources }: SourceCardsProps) {
  if (sources.length === 0) return null;

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-medium flex items-center gap-2">
        <FileText className="h-4 w-4" />
        Sources ({sources.length})
      </h3>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {sources.map((source) => {
          const parentCode = (source.metadata?.parent_code as string) ?? "";
          const label = PARENT_CODE_LABELS[parentCode] ?? parentCode;

          return (
            <div
              key={source.id}
              className="rounded-lg border border-border bg-card p-4 hover:shadow-sm transition-shadow"
            >
              <div className="flex items-start justify-between gap-2 mb-2">
                <span className="text-xs font-mono text-muted-foreground">
                  {source.id}
                </span>
                {label && (
                  <span className="text-[10px] rounded-full px-2 py-0.5 bg-secondary text-secondary-foreground">
                    {label}
                  </span>
                )}
              </div>
              {source.question && (
                <p className="text-sm font-medium mb-1 line-clamp-2">{source.question}</p>
              )}
              {source.answer && (
                <p className="text-xs text-muted-foreground line-clamp-3">
                  {source.answer}
                </p>
              )}
              {source.score > 0 && (
                <div className="mt-2 text-[10px] text-muted-foreground">
                  Relevance: {(source.score * 100).toFixed(0)}%
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
