import { useState, type FormEvent } from "react";
import { Search, Settings, X } from "lucide-react";
import type { SearchSettings } from "@/lib/types";
import { defaultSettings } from "@/lib/types";

const MODEL_OPTIONS = [
  { value: "claude-sonnet-4-5-20250929", label: "Sonnet 4.5" },
  { value: "claude-haiku-4-5-20251001", label: "Haiku 4.5" },
  { value: "claude-opus-4-6", label: "Opus 4.6" },
];

interface SearchInputProps {
  onSearch: (query: string, settings: SearchSettings) => void;
  onReset: () => void;
  isSearching: boolean;
}

export function SearchInput({ onSearch, onReset, isSearching }: SearchInputProps) {
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
        <div className="flex items-center gap-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-2 shadow-sm focus-within:ring-2 focus-within:ring-[hsl(var(--ring))] transition-shadow">
          <Search className="ml-2 h-5 w-5 text-[hsl(var(--muted-foreground))] flex-shrink-0" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ask a question about Islamic jurisprudence..."
            className="flex-1 bg-transparent outline-none text-sm placeholder:text-[hsl(var(--muted-foreground))]"
            disabled={isSearching}
          />
          <button
            type="button"
            onClick={() => setShowSettings((s) => !s)}
            className={`p-1.5 rounded-lg transition-colors ${
              showSettings
                ? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
                : "text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] hover:bg-[hsl(var(--secondary))]"
            }`}
            title="Settings"
          >
            <Settings className="h-4 w-4" />
          </button>
          {isSearching ? (
            <button
              type="button"
              onClick={onReset}
              className="flex items-center gap-1.5 rounded-lg bg-[hsl(var(--destructive))] text-[hsl(var(--destructive-foreground))] px-4 py-2 text-sm font-medium hover:opacity-90 transition-opacity"
            >
              <X className="h-4 w-4" />
              Stop
            </button>
          ) : (
            <button
              type="submit"
              disabled={!query.trim()}
              className="flex items-center gap-1.5 rounded-lg bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] px-4 py-2 text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              <Search className="h-4 w-4" />
              Search
            </button>
          )}
        </div>
      </form>

      {showSettings && (
        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 shadow-sm">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2">
              <label className="text-xs font-medium text-[hsl(var(--muted-foreground))]">
                Model
              </label>
              <select
                value={settings.model}
                onChange={(e) => setSettings((s) => ({ ...s, model: e.target.value }))}
                className="text-xs bg-[hsl(var(--secondary))] text-[hsl(var(--secondary-foreground))] rounded-lg px-2 py-1.5 outline-none border-none"
              >
                {MODEL_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex items-center gap-2">
              <label className="text-xs font-medium text-[hsl(var(--muted-foreground))]">
                Max Iterations
              </label>
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
                className="w-16 text-xs bg-[hsl(var(--secondary))] text-[hsl(var(--secondary-foreground))] rounded-lg px-2 py-1.5 outline-none border-none text-center"
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
