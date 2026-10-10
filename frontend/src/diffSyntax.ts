import { createLowlight } from 'lowlight';
import type { RootContent } from 'hast';
import bash from 'highlight.js/lib/languages/bash';
import css from 'highlight.js/lib/languages/css';
import dockerfile from 'highlight.js/lib/languages/dockerfile';
import ini from 'highlight.js/lib/languages/ini';
import javascript from 'highlight.js/lib/languages/javascript';
import json from 'highlight.js/lib/languages/json';
import python from 'highlight.js/lib/languages/python';
import typescript from 'highlight.js/lib/languages/typescript';
import xml from 'highlight.js/lib/languages/xml';
import yaml from 'highlight.js/lib/languages/yaml';
import type { FileDiff } from './unifiedDiff';

const highlighter = createLowlight({ bash, css, dockerfile, ini, javascript, json, python, typescript, xml, yaml });
const extensions: Record<string, string> = {
  py: 'python', pyw: 'python', pyi: 'python',
  js: 'javascript', jsx: 'javascript', mjs: 'javascript', cjs: 'javascript',
  ts: 'typescript', tsx: 'typescript', mts: 'typescript', cts: 'typescript',
  json: 'json', jsonc: 'json', yml: 'yaml', yaml: 'yaml',
  html: 'xml', htm: 'xml', xml: 'xml', svg: 'xml', css: 'css',
  sh: 'bash', bash: 'bash', zsh: 'bash', env: 'bash',
  ini: 'ini', toml: 'ini', dockerfile: 'dockerfile',
};

export type CodeToken = { text: string; className: string };
export type HighlightedDiff = Array<CodeToken[] | undefined>;

export function diffLanguage(path: string): string | undefined {
  const name = path.split('/').at(-1)!.toLowerCase();
  if (/^dockerfile(?:\.|$)/.test(name)) return 'dockerfile';
  if (name === '.env' || name.startsWith('.env.')) return 'bash';
  const extension = name.includes('.') ? name.split('.').at(-1)! : '';
  return Object.hasOwn(extensions, extension) ? extensions[extension] : undefined;
}

function highlightLines(language: string, code: string): CodeToken[][] {
  const tree = highlighter.highlight(language, code);
  const lines: CodeToken[][] = [[]];
  function visit(node: RootContent, classes: string[] = []) {
    if (node.type === 'element') {
      const ownClasses = node.properties.className;
      const nested = Array.isArray(ownClasses) ? [...classes, ...ownClasses.map(String)] : classes;
      node.children.forEach(child => visit(child, nested));
    } else if (node.type === 'text') {
      const parts = node.value.split('\n');
      parts.forEach((text, index) => {
        if (index) lines.push([]);
        if (text) lines[lines.length - 1].push({ text, className: classes.join(' ') });
      });
    }
  }
  tree.children.forEach(node => visit(node));
  return lines;
}

export function highlightDiff(file: FileDiff): HighlightedDiff | null {
  const language = diffLanguage(file.path);
  // Highlighting is optional: keep large/minified patches responsive and readable.
  if (!language || file.lines.length > 1000 || file.lines.some(line => line.text.length > 2000)
    || file.lines.reduce((size, line) => size + line.text.length, 0) > 50_000) return null;
  const result: HighlightedDiff = new Array(file.lines.length);
  let previous: number[] = [];
  let next: number[] = [];
  function flush() {
    // Highlight both versions separately so deleted strings/comments do not leak
    // into the new code. Shared context uses the new version's token colors.
    for (const indices of [previous, next]) {
      if (!indices.length) continue;
      const source = indices.map(index => file.lines[index].text);
      const tokens = highlightLines(language!, source.join('\n'));
      if (tokens.length !== source.length || tokens.some((line, index) => line.map(token => token.text).join('') !== source[index])) {
        throw new Error('Highlighting changed source text');
      }
      indices.forEach((index, offset) => { result[index] = tokens[offset]; });
    }
    previous = []; next = [];
  }
  try {
    file.lines.forEach((line, index) => {
      // The diff omits code between hunks: never carry lexical state across gaps.
      if (line.kind === 'hunk') flush();
      if (line.kind === 'context' || line.kind === 'deletion') previous.push(index);
      if (line.kind === 'context' || line.kind === 'addition') next.push(index);
    });
    flush();
    return result;
  } catch {
    return null;
  }
}
