import { useState } from "react";
import type { SearchSource } from "@/lib/types";
import { ChevronDown, ChevronUp, FileText } from "lucide-react";

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
  const [expandedId, setExpandedId] = useState<string | null>(null);

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
          const isExpanded = expandedId === source.id;
          const hasContent = source.question || source.answer;

          return (
            <div
              key={source.id}
              className={`rounded-lg border border-border bg-card p-4 transition-all ${
                hasContent ? "cursor-pointer hover:border-foreground/20" : ""
              } ${isExpanded ? "md:col-span-2" : ""}`}
              onClick={() =>
                hasContent && setExpandedId(isExpanded ? null : source.id)
              }
            >
              {/* Header: ID + category + expand indicator */}
              <div className="flex items-start justify-between gap-2 mb-2">
                <span className="text-xs font-mono text-muted-foreground">
                  {source.id}
                </span>
                <div className="flex items-center gap-1.5">
                  {label && (
                    <span className="text-[10px] rounded-full px-2 py-0.5 bg-secondary text-secondary-foreground">
                      {label}
                    </span>
                  )}
                  {hasContent &&
                    (isExpanded ? (
                      <ChevronUp className="h-3.5 w-3.5 text-muted-foreground" />
                    ) : (
                      <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                    ))}
                </div>
              </div>

              {/* Question */}
              {source.question && (
                <p
                  className={`text-sm font-medium mb-1 ${isExpanded ? "" : "line-clamp-2"}`}
                >
                  {source.question}
                </p>
              )}

              {/* Answer */}
              {source.answer && (
                <p
                  className={`text-xs text-muted-foreground ${isExpanded ? "whitespace-pre-line" : "line-clamp-3"}`}
                >
                  {source.answer}
                </p>
              )}

              {/* Expanded metadata section */}
              {isExpanded && source.metadata && (
                <div className="mt-3 pt-3 border-t border-border space-y-1.5">
                  <MetaRow
                    label="Category"
                    value={
                      source.metadata.parent_category
                        ? `${source.metadata.parent_category} (${parentCode})`
                        : label
                    }
                  />
                  <MetaRow
                    label="Cluster"
                    value={source.metadata.cluster_label as string}
                  />
                  <MetaRow
                    label="Topic"
                    value={source.metadata.primary_topic as string}
                  />
                  {Array.isArray(source.metadata.subtopics) &&
                    source.metadata.subtopics.length > 0 && (
                      <MetaRow
                        label="Subtopics"
                        value={(source.metadata.subtopics as string[]).join(
                          ", ",
                        )}
                      />
                    )}
                </div>
              )}

              {/* Score */}
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

function MetaRow({ label, value }: { label: string; value: unknown }) {
  if (!value) return null;
  return (
    <div className="flex gap-2 text-xs">
      <span className="text-muted-foreground shrink-0">{label}:</span>
      <span className="text-foreground">{String(value)}</span>
    </div>
  );
}
