export interface Citation {
  id: string;
  index: number;
  start: number;
  end: number;
}

const CITATION_RE = /\[Source:\s*([^\]]+)\]/g;

/**
 * Extract all [Source: id] citations from answer text.
 * Returns unique citation objects with their positions.
 */
export function parseCitations(text: string): Citation[] {
  const citations: Citation[] = [];
  const seen = new Set<string>();
  let match: RegExpExecArray | null;

  while ((match = CITATION_RE.exec(text)) !== null) {
    const id = match[1].trim();
    if (!seen.has(id)) {
      seen.add(id);
      citations.push({
        id,
        index: citations.length + 1,
        start: match.index,
        end: match.index + match[0].length,
      });
    }
  }

  return citations;
}

/**
 * Replace [Source: id] markers with markdown footnote-style links
 * that point to anchored source cards.
 * Pre-processes text before Markdown rendering.
 */
export function injectCitationLinks(text: string, citations: Citation[]): string {
  if (citations.length === 0) return text;
  const idToIndex = new Map(citations.map((c) => [c.id, c.index]));
  return text.replace(CITATION_RE, (_match, id: string) => {
    const idx = idToIndex.get(id.trim());
    if (idx === undefined) return _match;
    return `[^${idx}](#source-${id.trim()})`;
  });
}
