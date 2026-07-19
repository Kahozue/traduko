import type { ReactNode } from "react";

// Minimal, dependency-free markdown renderer for assistant replies. It emits
// React elements (never dangerouslySetInnerHTML), so untrusted text can never
// inject markup — the worst a crafted reply can do is render plain text. Scope
// is deliberately small: fenced code blocks, headings, unordered/ordered
// lists, blockquotes, pipe tables, horizontal rules, and inline
// bold/italic/code/links. Anything unrecognized falls through as a paragraph.

type Inline = { text: string; bold?: boolean; italic?: boolean; code?: boolean; href?: string };

// Split one line into inline runs. Order matters: code spans are taken first
// so their contents are not re-parsed for bold/italic.
function parseInline(text: string): Inline[] {
  const runs: Inline[] = [];
  let rest = text;
  const pattern =
    /(`[^`]+`)|(\*\*[^*]+\*\*)|(__[^_]+__)|(\*[^*]+\*)|(_[^_]+_)|(\[[^\]]+\]\([^)]+\))/;
  while (rest.length > 0) {
    const match = pattern.exec(rest);
    if (!match) {
      runs.push({ text: rest });
      break;
    }
    if (match.index > 0) runs.push({ text: rest.slice(0, match.index) });
    const token = match[0];
    if (token.startsWith("`")) {
      runs.push({ text: token.slice(1, -1), code: true });
    } else if (token.startsWith("**") || token.startsWith("__")) {
      runs.push({ text: token.slice(2, -2), bold: true });
    } else if (token.startsWith("[")) {
      const linkMatch = /\[([^\]]+)\]\(([^)]+)\)/.exec(token);
      if (linkMatch) runs.push({ text: linkMatch[1], href: linkMatch[2] });
    } else {
      runs.push({ text: token.slice(1, -1), italic: true });
    }
    rest = rest.slice(match.index + token.length);
  }
  return runs;
}

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  return parseInline(text).map((run, index) => {
    const key = `${keyPrefix}-${index}`;
    if (run.href) {
      // Only http(s) links are made clickable; anything else renders as text
      // so a reply cannot smuggle a javascript: or file: URL into an anchor.
      const safe = /^https?:\/\//i.test(run.href);
      return safe ? (
        <a key={key} href={run.href} target="_blank" rel="noopener noreferrer">
          {run.text}
        </a>
      ) : (
        <span key={key}>{run.text}</span>
      );
    }
    if (run.code) return <code key={key}>{run.text}</code>;
    let node: ReactNode = run.text;
    if (run.italic) node = <em key={`${key}-i`}>{node}</em>;
    if (run.bold) node = <strong key={`${key}-b`}>{node}</strong>;
    return <span key={key}>{node}</span>;
  });
}

// A table row is a pipe-delimited line; the header must be followed by a
// dash separator line to count as a table (GitHub style). Escaped pipes are
// out of scope for assistant replies.
const TABLE_ROW_RE = /^\s*\|.*\|\s*$/;
const TABLE_SEP_RE = /^\s*\|?[\s:|-]+\|?\s*$/;
const HR_RE = /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/;

function splitTableRow(line: string): string[] {
  let inner = line.trim();
  if (inner.startsWith("|")) inner = inner.slice(1);
  if (inner.endsWith("|")) inner = inner.slice(0, -1);
  return inner.split("|").map((cell) => cell.trim());
}

export function renderMarkdown(source: string): ReactNode[] {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let paragraph: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  let quote: string[] = [];

  function flushParagraph() {
    if (paragraph.length === 0) return;
    blocks.push(
      <p key={`p-${blocks.length}`}>{renderInline(paragraph.join(" "), `p-${blocks.length}`)}</p>,
    );
    paragraph = [];
  }
  function flushList() {
    if (!list) return;
    const items = list.items.map((item, index) => (
      <li key={index}>{renderInline(item, `li-${blocks.length}-${index}`)}</li>
    ));
    blocks.push(
      list.ordered ? (
        <ol key={`ol-${blocks.length}`}>{items}</ol>
      ) : (
        <ul key={`ul-${blocks.length}`}>{items}</ul>
      ),
    );
    list = null;
  }
  function flushQuote() {
    if (quote.length === 0) return;
    blocks.push(
      <blockquote key={`q-${blocks.length}`}>
        {renderInline(quote.join(" "), `q-${blocks.length}`)}
      </blockquote>,
    );
    quote = [];
  }
  function flushAll() {
    flushParagraph();
    flushList();
    flushQuote();
  }

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const fence = /^```/.test(line);
    if (fence) {
      flushAll();
      const code: string[] = [];
      i += 1;
      while (i < lines.length && !/^```/.test(lines[i])) {
        code.push(lines[i]);
        i += 1;
      }
      // A fence with no content (typically the dangling opener left when a
      // reply was cut at a tool call) renders as an empty gray box — skip it.
      if (code.some((codeLine) => codeLine.trim() !== "")) {
        blocks.push(
          <pre key={`pre-${blocks.length}`}>
            <code>{code.join("\n")}</code>
          </pre>,
        );
      }
      continue;
    }
    if (
      TABLE_ROW_RE.test(line) &&
      i + 1 < lines.length &&
      TABLE_SEP_RE.test(lines[i + 1]) &&
      lines[i + 1].includes("-")
    ) {
      flushAll();
      const header = splitTableRow(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && TABLE_ROW_RE.test(lines[i])) {
        rows.push(splitTableRow(lines[i]));
        i += 1;
      }
      i -= 1;
      const tableKey = `t-${blocks.length}`;
      blocks.push(
        <table key={tableKey}>
          <thead>
            <tr>
              {header.map((cell, col) => (
                <th key={col}>{renderInline(cell, `${tableKey}-h-${col}`)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((cells, rowIndex) => (
              <tr key={rowIndex}>
                {cells.map((cell, col) => (
                  <td key={col}>{renderInline(cell, `${tableKey}-${rowIndex}-${col}`)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>,
      );
      continue;
    }
    if (HR_RE.test(line)) {
      flushAll();
      blocks.push(<hr key={`hr-${blocks.length}`} />);
      continue;
    }
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      flushAll();
      const level = heading[1].length;
      const Tag = `h${Math.min(level + 2, 6)}` as "h3" | "h4" | "h5" | "h6";
      blocks.push(<Tag key={`h-${blocks.length}`}>{renderInline(heading[2], `h-${blocks.length}`)}</Tag>);
      continue;
    }
    const bullet = /^\s*[-*+]\s+(.*)$/.exec(line);
    const numbered = /^\s*\d+\.\s+(.*)$/.exec(line);
    if (bullet || numbered) {
      flushParagraph();
      flushQuote();
      const ordered = numbered !== null;
      const item = (bullet ?? numbered)![1];
      if (!list || list.ordered !== ordered) {
        flushList();
        list = { ordered, items: [] };
      }
      list.items.push(item);
      continue;
    }
    const quoteMatch = /^>\s?(.*)$/.exec(line);
    if (quoteMatch) {
      flushParagraph();
      flushList();
      quote.push(quoteMatch[1]);
      continue;
    }
    if (line.trim() === "") {
      flushAll();
      continue;
    }
    flushList();
    flushQuote();
    paragraph.push(line);
  }
  flushAll();
  return blocks;
}
