import { useLayoutEffect, useRef, useState } from 'react';
import type { Inline } from '../types';
import { editInline, inlineValue, reconcileInline } from './inline-editing';
import './continuous-inline-editor.css';

function selectionOffsets(root: HTMLElement): [number, number] | null {
  const selection = window.getSelection();
  if (!selection?.rangeCount) return null;
  const range = selection.getRangeAt(0);
  if (!root.contains(range.startContainer) || !root.contains(range.endContainer)) return null;
  const prefix = range.cloneRange(); prefix.selectNodeContents(root); prefix.setEnd(range.startContainer, range.startOffset);
  const start = prefix.toString().length;
  return [start, start + range.toString().length];
}
function restoreSelection(root: HTMLElement, offsets: [number, number]) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const texts: Text[] = []; let node;
  while ((node = walker.nextNode())) texts.push(node as Text);
  const at = (position: number): [Node, number] => {
    for (const text of texts) { if (position <= text.length) return [text, position]; position -= text.length; }
    return texts.length ? [texts[texts.length - 1], texts[texts.length - 1].length] : [root, 0];
  };
  const range = document.createRange(); range.setStart(...at(offsets[0])); range.setEnd(...at(offsets[1]));
  const selection = window.getSelection(); selection?.removeAllRanges(); selection?.addRange(range);
}

/** The editable DOM is only a view; saved values always come from the typed AST. */
export function ContinuousInlineEditor({ nodes, atoms = {}, change, label = '译文段落', disabled = false, onCompositionChange }: {
  nodes: Inline[]; atoms?: Record<string, string>; change: (nodes: Inline[]) => void; label?: string; disabled?: boolean; onCompositionChange?: (active: boolean) => void;
}) {
  const ref = useRef<HTMLDivElement>(null), current = useRef(nodes), composing = useRef(false);
  const history = useRef<{ past: Inline[][]; future: Inline[][] }>({ past: [], future: [] });
  const [notice, setNotice] = useState('');
  const draw = (value: Inline[], selection: [number, number] | null = null) => {
    const root = ref.current; if (!root) return;
    const fragment = document.createDocumentFragment();
    for (const node of value) {
      const span = document.createElement('span');
      span.textContent = inlineValue(node, atoms);
      span.className = (node.marks ?? []).map(mark => `inline-${mark}`).join(' ');
      if (node.type === 'protected_ref') {
        span.contentEditable = 'false'; span.classList.add('inline-protected');
        span.title = `保护内容：${span.textContent}`; span.setAttribute('aria-label', span.title);
      } else if (node.type === 'link' || node.type === 'xref') span.classList.add('inline-reference');
      fragment.append(span);
    }
    root.replaceChildren(fragment);
    if (selection && document.activeElement === root) restoreSelection(root, selection);
  };
  useLayoutEffect(() => {
    if (composing.current) return;
    if (JSON.stringify(nodes) !== JSON.stringify(current.current)) history.current = { past: [], future: [] };
    current.current = nodes;
    draw(nodes, ref.current ? selectionOffsets(ref.current) : null);
  }, [nodes, atoms]);
  const apply = (next: Inline[], selection: [number, number] | null, remember = true) => {
    if (remember && JSON.stringify(next) !== JSON.stringify(current.current)) {
      history.current.past.push(current.current); history.current.past = history.current.past.slice(-100); history.current.future = [];
    }
    current.current = next; draw(next, selection); change(next); setNotice('');
  };
  const acceptInput = () => {
    const root = ref.current; if (!root || composing.current) return;
    const offsets = selectionOffsets(root);
    try { apply(reconcileInline(current.current, root.textContent ?? '', atoms), offsets); }
    catch (error) { draw(current.current, offsets); setNotice((error as Error).message); }
  };
  const insert = (text: string) => {
    const selection = ref.current && selectionOffsets(ref.current); if (!selection) return;
    try { const next = editInline(current.current, ...selection, text, atoms); const caret = selection[0] + text.length; apply(next, [caret, caret]); }
    catch (error) { setNotice((error as Error).message); }
  };
  const undo = (redo = false) => {
    const from = redo ? history.current.future : history.current.past;
    const to = redo ? history.current.past : history.current.future;
    const next = from.pop(); if (!next) return;
    to.push(current.current); apply(next, [next.map(n => inlineValue(n, atoms)).join('').length, next.map(n => inlineValue(n, atoms)).join('').length], false);
  };
  return <div className="continuous-inline-field">
    <div ref={ref} role="textbox" aria-label={label} aria-multiline="true" aria-readonly={disabled}
      className="continuous-inline-editor" contentEditable={!disabled} suppressContentEditableWarning spellCheck
      onInput={acceptInput} onCompositionStart={() => { composing.current = true; onCompositionChange?.(true); }}
      onCompositionEnd={() => { composing.current = false; acceptInput(); onCompositionChange?.(false); }}
      onBeforeInput={event => {
        const input = event.nativeEvent as InputEvent;
        if (input.inputType === 'historyUndo' || input.inputType === 'historyRedo') { event.preventDefault(); undo(input.inputType === 'historyRedo'); }
        if (input.inputType === 'insertParagraph' || input.inputType === 'insertLineBreak') { event.preventDefault(); insert('\n'); }
      }}
      onKeyDown={event => {
        if (composing.current) return;
        if ((event.ctrlKey || event.metaKey) && (event.key.toLowerCase() === 'z' || event.key.toLowerCase() === 'y')) {
          event.preventDefault(); undo(event.shiftKey || event.key.toLowerCase() === 'y');
        } else if (event.key === 'Enter') { event.preventDefault(); insert('\n'); }
      }}
      onPaste={event => { event.preventDefault(); insert(event.clipboardData.getData('text/plain')); }}
      onDrop={event => { event.preventDefault(); setNotice('请使用粘贴插入文字；拖放不会修改段落。'); }}/>
    {nodes.some(node => node.type === 'protected_ref') && <small className="muted">带底色的公式或引用受保护，可在两侧连续编辑普通文字。</small>}
    {notice && <p role="status" className="field-note warn">{notice}</p>}
  </div>;
}
