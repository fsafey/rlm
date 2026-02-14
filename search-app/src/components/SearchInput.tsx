import { useState, type FormEvent } from "react";
import { Search, Settings, X } from "lucide-react";
import type { SearchSettings } from "@/lib/types";
import { defaultSettings } from "@/lib/types";

const MODEL_OPTIONS = [
  { value: "claude-opus-4-6", label: "Opus 4.6" },
  { value: "claude-sonnet-4-5-20250929", label: "Sonnet 4.5" },
  { value: "claude-haiku-4-5-20251001", label: "Haiku 4.5" },
];

const SUB_MODEL_OPTIONS = [
  { value: "", label: "Same as root" },
  { value: "claude-sonnet-4-5-20250929", label: "Sonnet 4.5" },
  { value: "claude-haiku-4-5-20251001", label: "Haiku 4.5" },
];

const BACKEND_OPTIONS = [
  { value: "anthropic", label: "Anthropic" },
  { value: "openai", label: "OpenAI" },
  { value: "claude_cli", label: "Claude CLI" },
];

interface SearchInputProps {
  onSearch: (query: string, settings: SearchSettings) => void;
  onReset: () => void;
  isSearching: boolean;
  isCancelling?: boolean;
  isFollowUp?: boolean;
}

export function SearchInput({ onSearch, onReset, isSearching, isCancelling, isFollowUp }: SearchInputProps) {
  const [query, setQuery] = useState("");
  const [showSettings, setShowSettings] = useState(false);
  const [settings, setSettings] = useState<SearchSettings>({ ...defaultSettings });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!query.trim() || isSearching) return;
    onSearch(query.trim(), settings);
  }

  return (
    <div className="w-full max-w-3xl mx-auto space-y-2">
      <form onSubmit={handleSubmit}>
        <div className="flex items-center gap-3 rounded-xl border border-border bg-card p-2 shadow-sm focus-within:ring-2 focus-within:ring-ring transition-shadow">
          <Search className="ml-2 h-5 w-5 text-muted-foreground flex-shrink-0" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={isFollowUp ? "Ask a follow-up question..." : "Ask a question about Islamic jurisprudence..."}
            className="flex-1 bg-transparent outline-none text-sm placeholder:text-muted-foreground"
            disabled={isSearching}
          />
          <button
            type="button"
            onClick={() => setShowSettings((s) => !s)}
            className={`p-1.5 rounded-lg transition-colors ${
              showSettings
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground hover:bg-secondary"
            }`}
            title="Settings"
          >
            <Settings className="h-4 w-4" />
          </button>
          {isSearching ? (
            <button
              type="button"
              onClick={onReset}
              disabled={isCancelling}
              className="flex items-center gap-1.5 rounded-lg bg-destructive text-destructive-foreground px-4 py-2 text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              <X className="h-4 w-4" />
              {isCancelling ? "Cancelling..." : "Stop"}
            </button>
          ) : (
            <button
              type="submit"
              disabled={!query.trim()}
              className="flex items-center gap-1.5 rounded-lg bg-primary text-primary-foreground px-4 py-2 text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              <Search className="h-4 w-4" />
              Search
            </button>
          )}
        </div>
      </form>

      {showSettings && (
        <div className="rounded-xl border border-border bg-card p-4 shadow-sm space-y-4">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-muted-foreground">Model</label>
              <select
                value={settings.model}
                onChange={(e) => setSettings((s) => ({ ...s, model: e.target.value }))}
                className="text-xs bg-secondary text-secondary-foreground rounded-lg px-2 py-1.5 outline-none border-none"
              >
                {MODEL_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
              <span className="text-[10px] text-muted-foreground/70">Smarter models give better answers but cost more</span>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-muted-foreground">Sub-Model</label>
              <select
                value={settings.sub_model}
                onChange={(e) => setSettings((s) => ({ ...s, sub_model: e.target.value }))}
                className="text-xs bg-secondary text-secondary-foreground rounded-lg px-2 py-1.5 outline-none border-none"
              >
                {SUB_MODEL_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
              <span className="text-[10px] text-muted-foreground/70">Use a cheaper model for sub-tasks to save cost</span>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-muted-foreground">Backend</label>
              <select
                value={settings.backend}
                onChange={(e) => setSettings((s) => ({ ...s, backend: e.target.value }))}
                className="text-xs bg-secondary text-secondary-foreground rounded-lg px-2 py-1.5 outline-none border-none"
              >
                {BACKEND_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
              <span className="text-[10px] text-muted-foreground/70">Which API provider handles LLM calls</span>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-muted-foreground">Max Iterations</label>
              <input
                type="number"
                min={1}
                max={50}
                value={settings.max_iterations}
                onChange={(e) =>
                  setSettings((s) => ({
                    ...s,
                    max_iterations: Math.max(1, Math.min(50, Number(e.target.value) || 1)),
                  }))
                }
                className="text-xs bg-secondary text-secondary-foreground rounded-lg px-2 py-1.5 outline-none border-none text-center"
              />
              <span className="text-[10px] text-muted-foreground/70">More iterations = deeper research, higher cost</span>
            </div>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-muted-foreground">RLM Recursion</label>
              <input
                type="number"
                min={1}
                max={5}
                value={settings.max_depth}
                onChange={(e) =>
                  setSettings((s) => ({
                    ...s,
                    max_depth: Math.max(1, Math.min(5, Number(e.target.value) || 1)),
                  }))
                }
                className="text-xs bg-secondary text-secondary-foreground rounded-lg px-2 py-1.5 outline-none border-none text-center"
              />
              <span className="text-[10px] text-muted-foreground/70">Self-calls for problem decomposition (1 = no recursion)</span>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-muted-foreground">Sub-Agent Budget</label>
              <input
                type="number"
                min={1}
                max={10}
                value={settings.sub_iterations}
                onChange={(e) =>
                  setSettings((s) => ({
                    ...s,
                    sub_iterations: Math.max(1, Math.min(10, Number(e.target.value) || 1)),
                  }))
                }
                className="text-xs bg-secondary text-secondary-foreground rounded-lg px-2 py-1.5 outline-none border-none text-center"
              />
              <span className="text-[10px] text-muted-foreground/70">Steps each sub-agent gets to research its question</span>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-muted-foreground">Sub-Agent Depth</label>
              <input
                type="number"
                min={0}
                max={3}
                value={settings.max_delegation_depth}
                onChange={(e) =>
                  setSettings((s) => ({
                    ...s,
                    max_delegation_depth: Math.max(0, Math.min(3, Number(e.target.value) || 0)),
                  }))
                }
                className="text-xs bg-secondary text-secondary-foreground rounded-lg px-2 py-1.5 outline-none border-none text-center"
              />
              <span className="text-[10px] text-muted-foreground/70">Layers of sub-agents that can be spawned (0 = none)</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
