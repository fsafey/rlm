import type { SearchSettings } from "@/lib/types";

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

interface SearchSettingsPanelProps {
  settings: SearchSettings;
  onChange: (settings: SearchSettings) => void;
}

export function SearchSettingsPanel({ settings, onChange }: SearchSettingsPanelProps) {
  return (
    <div className="rounded-xl border border-border bg-card p-4 shadow-sm space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-muted-foreground">Model</label>
          <select
            value={settings.model}
            onChange={(e) => onChange({ ...settings, model: e.target.value })}
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
            onChange={(e) => onChange({ ...settings, sub_model: e.target.value })}
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
            onChange={(e) => onChange({ ...settings, backend: e.target.value })}
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
              onChange({
                ...settings,
                max_iterations: Math.max(1, Math.min(50, Number(e.target.value) || 1)),
              })
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
              onChange({
                ...settings,
                max_depth: Math.max(1, Math.min(5, Number(e.target.value) || 1)),
              })
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
              onChange({
                ...settings,
                sub_iterations: Math.max(1, Math.min(10, Number(e.target.value) || 1)),
              })
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
              onChange({
                ...settings,
                max_delegation_depth: Math.max(0, Math.min(3, Number(e.target.value) || 0)),
              })
            }
            className="text-xs bg-secondary text-secondary-foreground rounded-lg px-2 py-1.5 outline-none border-none text-center"
          />
          <span className="text-[10px] text-muted-foreground/70">Layers of sub-agents that can be spawned (0 = none)</span>
        </div>
      </div>
    </div>
  );
}
