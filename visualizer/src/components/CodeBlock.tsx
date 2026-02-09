'use client';

import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { cn } from '@/lib/utils';
import { CodeBlock as CodeBlockType, extractTokens } from '@/lib/types';
import { CodeWithLineNumbers } from './CodeWithLineNumbers';

interface CodeBlockProps {
  block: CodeBlockType;
  index: number;
}

export function CodeBlock({ block, index }: CodeBlockProps) {
  const [isOpen, setIsOpen] = useState(true);
  const hasError = block.result?.stderr && block.result.stderr.length > 0;
  const hasOutput = block.result?.stdout && block.result.stdout.length > 0;
  const executionTime = block.result?.execution_time 
    ? block.result.execution_time.toFixed(2) 
    : null;

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <Card className={cn(
        'border overflow-hidden transition-all',
        hasError 
          ? 'border-red-500/40 bg-red-500/5 dark:border-red-400/40 dark:bg-red-400/5' 
          : 'border-emerald-500/30 bg-emerald-500/5 dark:border-emerald-400/30 dark:bg-emerald-400/5'
      )}>
        <CollapsibleTrigger asChild>
          <CardHeader className="py-2 px-4 cursor-pointer hover:bg-muted/30 transition-colors">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-emerald-600 dark:text-emerald-400 font-mono text-sm">
                  {'>'}_
                </span>
                <CardTitle className="text-sm font-medium">
                  Code Block #{index + 1}
                </CardTitle>
              </div>
              <div className="flex items-center gap-2">
                {executionTime && (
                  <Badge variant="outline" className="font-mono text-xs">
                    {executionTime}s
                  </Badge>
                )}
                {hasError && (
                  <Badge variant="destructive" className="text-xs">
                    Error
                  </Badge>
                )}
                {hasOutput && !hasError && (
                  <Badge className="bg-emerald-500 text-white dark:bg-emerald-400 dark:text-emerald-950 text-xs">
                    Output
                  </Badge>
                )}
                <Button variant="ghost" size="sm" className="h-6 w-6 p-0">
                  <span className="text-xs">{isOpen ? '▼' : '▶'}</span>
                </Button>
              </div>
            </div>
          </CardHeader>
        </CollapsibleTrigger>
        
        <CollapsibleContent>
          <CardContent className="p-0">
            {/* Code */}
            <div className="bg-muted border-t border-border">
              <div className="px-3 py-1.5 border-b border-border/50 flex items-center gap-2">
                <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
                  Python
                </span>
              </div>
              <div className="code-block p-4 overflow-x-auto">
                <CodeWithLineNumbers code={block.code} language="python" />
              </div>
            </div>

            {/* Output */}
            {hasOutput && (
              <div className="border-t border-border bg-emerald-500/5 dark:bg-emerald-400/5">
                <div className="px-3 py-1.5 border-b border-border/50 flex items-center gap-2">
                  <span className="text-[10px] uppercase tracking-wider text-emerald-600 dark:text-emerald-400 font-medium">
                    stdout
                  </span>
                </div>
                <pre className="code-block p-4 overflow-x-auto">
                  <code className="text-emerald-700 dark:text-emerald-300">
                    {block.result.stdout}
                  </code>
                </pre>
              </div>
            )}

            {/* Errors */}
            {hasError && (
              <div className="border-t border-border bg-red-500/5 dark:bg-red-400/5">
                <div className="px-3 py-1.5 border-b border-border/50 flex items-center gap-2">
                  <span className="text-[10px] uppercase tracking-wider text-red-600 dark:text-red-400 font-medium">
                    stderr
                  </span>
                </div>
                <pre className="code-block p-4 overflow-x-auto">
                  <code className="text-red-700 dark:text-red-300">
                    {block.result.stderr}
                  </code>
                </pre>
              </div>
            )}

            {/* Locals */}
            {block.result?.locals && Object.keys(block.result.locals).length > 0 && (
              <div className="border-t border-border bg-muted/50">
                <div className="px-3 py-1.5 border-b border-border/50 flex items-center gap-2">
                  <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
                    Variables
                  </span>
                </div>
                <div className="p-4 grid grid-cols-2 md:grid-cols-3 gap-2">
                  {Object.entries(block.result.locals).map(([key, value]) => (
                    <div 
                      key={key} 
                      className="bg-background rounded px-2 py-1.5 font-mono text-xs overflow-hidden border border-border"
                    >
                      <span className="text-sky-600 dark:text-sky-400">{key}</span>
                      <span className="text-muted-foreground mx-1">=</span>
                      <span className="text-amber-600 dark:text-amber-400 truncate">
                        {typeof value === 'string' 
                          ? value.length > 30 ? value.slice(0, 30) + '...' : value
                          : JSON.stringify(value).slice(0, 30)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Sub-LM Calls */}
            {block.result?.rlm_calls && block.result.rlm_calls.length > 0 && (
              <div className="border-t border-border bg-fuchsia-500/5 dark:bg-fuchsia-400/5">
                <div className="px-3 py-1.5 border-b border-border/50 flex items-center gap-2">
                  <span className="text-[10px] uppercase tracking-wider text-fuchsia-600 dark:text-fuchsia-400 font-medium">
                    Sub-LM Calls ({block.result.rlm_calls.length})
                  </span>
                </div>
                <div className="p-4 space-y-3">
                  {block.result.rlm_calls.map((call, i) => {
                    const tokens = extractTokens(call);
                    return (
                    <Collapsible key={i}>
                      <div className="border border-fuchsia-500/30 dark:border-fuchsia-400/30 rounded-lg bg-background overflow-hidden">
                        <CollapsibleTrigger asChild>
                          <div className="flex items-center justify-between p-3 cursor-pointer hover:bg-fuchsia-500/10 dark:hover:bg-fuchsia-400/10 transition-colors">
                            <Badge className="bg-fuchsia-500 text-white dark:bg-fuchsia-400 dark:text-fuchsia-950 text-xs">
                              llm_query #{i + 1}{call.root_model ? ` (${call.root_model})` : ''}
                            </Badge>
                            <div className="flex gap-2 text-xs text-muted-foreground">
                              <span>{tokens.input.toLocaleString()} in</span>
                              <span>•</span>
                              <span>{tokens.output.toLocaleString()} out</span>
                              <span>•</span>
                              <span>{(call.execution_time ?? 0).toFixed(2)}s</span>
                            </div>
                          </div>
                        </CollapsibleTrigger>
                        <CollapsibleContent>
                          <div className="px-3 pb-3 space-y-2 border-t border-fuchsia-500/20 dark:border-fuchsia-400/20">
                            <div className="text-xs text-muted-foreground mt-2">Prompt:</div>
                            <div className="text-sm bg-muted rounded p-2 max-h-40 overflow-y-auto border border-border">
                              {typeof call.prompt === 'string'
                                ? call.prompt
                                : JSON.stringify(call.prompt, null, 2)}
                            </div>
                            <div className="text-xs text-muted-foreground">Response:</div>
                            <div className="text-sm bg-muted rounded p-2 max-h-40 overflow-y-auto border border-border">
                              {call.response}
                            </div>
                          </div>
                        </CollapsibleContent>
                      </div>
                    </Collapsible>
                    );
                  })}
                </div>
              </div>
            )}
          </CardContent>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  );
}
