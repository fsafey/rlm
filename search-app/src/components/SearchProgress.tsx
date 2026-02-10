import { Loader2 } from "lucide-react";
import type { Iteration } from "@/lib/types";

interface SearchProgressProps {
  iterations: Iteration[];
}

function detectPhase(iterations: Iteration[]): string {
  if (iterations.length === 0) return "Initializing...";
  const last = iterations[iterations.length - 1];
  const code = last.code_blocks.map((b) => b.code).join("\n");
  if (code.includes("search(")) return "Searching knowledge base...";
  if (code.includes("browse(")) return "Browsing documents...";
  if (code.includes("llm_query(")) return "Synthesizing findings...";
  if (code.includes("FINAL_VAR(")) return "Preparing answer...";
  return `Analyzing... (iteration ${iterations.length})`;
}

export function SearchProgress({ iterations }: SearchProgressProps) {
  const phase = detectPhase(iterations);

  return (
    <div className="flex items-center gap-3 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" />
      <span>{phase}</span>
      {iterations.length > 0 && (
        <span className="text-xs opacity-70">
          ({iterations.length} iteration{iterations.length !== 1 ? "s" : ""})
        </span>
      )}
    </div>
  );
}
