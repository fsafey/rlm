import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { extractTokens } from '@/lib/types';
import type { RLMChatCompletion } from '@/lib/types';

interface SubLMCallCardProps {
  call: RLMChatCompletion;
  index: number;
  blockIndex?: number;
}

export function SubLMCallCard({ call, index, blockIndex }: SubLMCallCardProps) {
  const tokens = extractTokens(call);

  return (
    <Collapsible>
      <Card className="border-fuchsia-500/30 bg-fuchsia-500/5 dark:border-fuchsia-400/30 dark:bg-fuchsia-400/5">
        <CollapsibleTrigger asChild>
          <CardHeader className="py-3 px-4 cursor-pointer hover:bg-fuchsia-500/10 dark:hover:bg-fuchsia-400/10 transition-colors">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-fuchsia-500 dark:bg-fuchsia-400" />
                llm_query() #{index + 1}
                {blockIndex !== undefined && (
                  <span className="text-muted-foreground text-xs font-normal">
                    from Block #{blockIndex + 1}
                  </span>
                )}
                {call.root_model && (
                  <Badge variant="outline" className="text-[10px] font-mono ml-1">
                    {call.root_model}
                  </Badge>
                )}
              </CardTitle>
              <div className="flex gap-2">
                <Badge variant="outline" className="text-[10px] font-mono">
                  {tokens.input.toLocaleString()} in
                </Badge>
                <Badge variant="outline" className="text-[10px] font-mono">
                  {tokens.output.toLocaleString()} out
                </Badge>
                <Badge variant="outline" className="text-[10px] font-mono">
                  {(call.execution_time ?? 0).toFixed(2)}s
                </Badge>
              </div>
            </div>
            {/* Collapsed preview - truncated prompt */}
            <p className="text-[11px] text-muted-foreground truncate mt-1.5 font-mono">
              {(() => {
                const text = typeof call.prompt === 'string' ? call.prompt : JSON.stringify(call.prompt);
                return text.length > 120 ? text.slice(0, 120) + '...' : text;
              })()}
            </p>
          </CardHeader>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <CardContent className="px-4 pb-4 space-y-3 border-t border-fuchsia-500/20 dark:border-fuchsia-400/20">
            <div>
              <p className="text-xs text-muted-foreground mb-1.5 font-medium uppercase tracking-wider">
                Prompt
              </p>
              <div className="bg-muted/50 rounded-lg p-3 max-h-64 overflow-y-auto border border-border">
                <pre className="text-xs whitespace-pre-wrap font-mono">
                  {typeof call.prompt === 'string'
                    ? call.prompt
                    : JSON.stringify(call.prompt, null, 2)}
                </pre>
              </div>
            </div>
            <div>
              <p className="text-xs text-muted-foreground mb-1.5 font-medium uppercase tracking-wider">
                Response
              </p>
              <div className="bg-fuchsia-500/10 dark:bg-fuchsia-400/10 rounded-lg p-3 max-h-80 overflow-y-auto border border-fuchsia-500/20 dark:border-fuchsia-400/20">
                <pre className="text-xs whitespace-pre-wrap font-mono text-fuchsia-700 dark:text-fuchsia-300">
                  {call.response}
                </pre>
              </div>
            </div>
          </CardContent>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  );
}
