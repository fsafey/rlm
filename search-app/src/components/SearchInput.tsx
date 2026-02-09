import { useState, type FormEvent } from "react";
import { Search, X } from "lucide-react";

interface SearchInputProps {
  onSearch: (query: string, collection: string) => void;
  onReset: () => void;
  isSearching: boolean;
}

export function SearchInput({ onSearch, onReset, isSearching }: SearchInputProps) {
  const [query, setQuery] = useState("");
  const [collection, setCollection] = useState("enriched_gemini");

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!query.trim() || isSearching) return;
    onSearch(query.trim(), collection);
  }

  return (
    <form onSubmit={handleSubmit} className="w-full max-w-3xl mx-auto">
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
        <select
          value={collection}
          onChange={(e) => setCollection(e.target.value)}
          className="text-xs bg-[hsl(var(--secondary))] text-[hsl(var(--secondary-foreground))] rounded-lg px-2 py-1.5 outline-none border-none"
        >
          <option value="enriched_gemini">Enriched (Gemini)</option>
          <option value="enriched_openai">Enriched (OpenAI)</option>
        </select>
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
  );
}
