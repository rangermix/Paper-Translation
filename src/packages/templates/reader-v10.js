document.addEventListener('DOMContentLoaded', () => {
  for (const node of document.querySelectorAll('[data-tex]')) {
    if (!window.katex) continue;
    const fallback = node.textContent;
    try {
      window.katex.render(node.dataset.tex, node, {
        output: 'mathml', displayMode: node.dataset.display === 'true',
        throwOnError: true, trust: false, strict: 'ignore', maxExpand: 1000, maxSize: 20,
      });
      node.dataset.mathRendered = 'true';
    } catch (_) {
      node.textContent = fallback;
      node.classList.add('math-error');
      node.setAttribute('title', '此公式暂不能排版，保留识别文字供原文对照。');
    }
  }
});

document.addEventListener('DOMContentLoaded', () => {
  'use strict';
  const root = document.documentElement;
  const notice = document.getElementById('reader-storage-notice');
  const save = (key, value) => { try { localStorage.setItem('reader-v7:' + key, value); } catch (_) { if (notice) notice.hidden = false; } };
  const read = (key) => { try { return localStorage.getItem('reader-v7:' + key); } catch (_) { if (notice) notice.hidden = false; return null; } };
  const theme = read('theme');
  if (theme === 'dark' || theme === 'light') root.dataset.theme = theme;
  const fontSelect = document.querySelector('[data-font-select]');
  const applyFont = value => {
    const font = ['default', 'serif', 'sans', 'monospace', 'fz-song', 'fz-hei',
      'source-han-serif', 'source-han-sans', 'misans', 'harmonyos-sans', 'noto-sans-sc'].includes(value) ? value : 'default';
    root.dataset.font = font;
    if (fontSelect) {
      fontSelect.value = font;
      fontSelect.title = fontSelect.selectedOptions[0].textContent + ' · 使用本机字体；未安装时使用备用字体。';
    }
    return font;
  };
  applyFont(read('font'));
  // Keep anchors visible when the toolbar wraps or its font size changes.
  const toolbar = document.querySelector('.toolbar');
  const blocks = Array.from(document.querySelectorAll('[data-block-id], [data-note-target]'));
  let anchorPinned = Boolean(location.hash);
  let pendingFrame = 0;
  const hashTarget = () => {
    try {
      const id = decodeURIComponent(location.hash.slice(1));
      const target = document.getElementById(id);
      return target?.matches('[data-block-id], [data-note-target]') ? target : null;
    } catch (_) { return null; }
  };
  const updateAnchorMargin = () => {
    const position = toolbar ? getComputedStyle(toolbar).position : '';
    const height = toolbar && (position === 'sticky' || position === 'fixed') ? toolbar.getBoundingClientRect().height : 0;
    blocks.forEach(block => { block.style.scrollMarginTop = Math.ceil(height + 12) + 'px'; });
  };
  const refreshAnchor = () => {
    updateAnchorMargin();
    if (pendingFrame) cancelAnimationFrame(pendingFrame);
    pendingFrame = requestAnimationFrame(() => {
      pendingFrame = 0;
      updateAnchorMargin();
      if (anchorPinned) hashTarget()?.scrollIntoView({ block: 'start', behavior: 'instant' });
    });
  };
  fontSelect?.addEventListener('change', () => {
    save('font', applyFont(fontSelect.value));
    refreshAnchor();
  });
  const referencePanels = new Map();
  let lastPanel = null;
  const closeReference = (state, restoreFocus = true) => {
    state.panel.hidden = true;
    state.origin?.setAttribute('aria-expanded', 'false');
    if (restoreFocus && state.origin?.getClientRects().length) state.origin.focus({ preventScroll: true });
    if (lastPanel === state) lastPanel = null;
  };
  document.querySelectorAll('a[data-reference-targets]').forEach(link => link.setAttribute('aria-expanded', 'false'));
  const openReference = link => {
    const row = link.closest('.reader-block, .reader-header');
    const targets = link.dataset.referenceTargets.split(' ').map(id => {
      const anchor = document.getElementById('b-' + id);
      const content = anchor?.matches('[data-original-only="original_reference"]') ? anchor
        : anchor?.querySelector(':scope > [data-original-only="original_reference"]');
      return { anchor, content };
    });
    if (!row || targets.some(target => !target.content)) return false;
    let state = referencePanels.get(row);
    if (state?.origin === link && !state.panel.hidden) {
      closeReference(state);
      return true;
    }
    if (!state) {
      let margin = Array.from(row.children).find(node => node.classList.contains('reader-notes'));
      if (!margin) {
        margin = document.createElement('aside');
        margin.className = 'reader-notes';
        margin.setAttribute('aria-label', '脚注、参考文献与内容提示');
        row.append(margin);
      }
      const panel = document.createElement('section');
      panel.className = 'reference-card';
      panel.id = 'reference-panel-' + (referencePanels.size + 1);
      panel.setAttribute('role', 'region');
      panel.setAttribute('aria-label', '参考文献详情');
      panel.tabIndex = -1;
      margin.prepend(panel);
      state = { panel, origin: null };
      referencePanels.set(row, state);
    }
    state.origin?.setAttribute('aria-expanded', 'false');
    state.origin = link;
    const heading = document.createElement('div');
    heading.className = 'sidenote-heading';
    const label = document.createElement('span');
    label.textContent = '参考文献 · ' + link.textContent;
    const close = document.createElement('button');
    close.type = 'button';
    close.textContent = '×';
    close.setAttribute('aria-label', '关闭参考文献');
    close.addEventListener('click', () => closeReference(state));
    heading.append(label, close);
    state.panel.replaceChildren(heading);
    for (const target of targets) {
      const entry = document.createElement('div');
      entry.className = 'reference-entry';
      entry.setAttribute('data-original-only', 'original_reference');
      entry.append(...Array.from(target.content.childNodes, node => node.cloneNode(true)));
      for (const node of entry.querySelectorAll('*')) {
        node.removeAttribute('id');
        node.removeAttribute('data-block-id');
        node.removeAttribute('data-kind');
      }
      const source = document.createElement('a');
      source.href = '#' + target.anchor.id;
      source.className = 'reference-source';
      source.textContent = '在参考文献列表中查看';
      entry.append(source);
      state.panel.append(entry);
    }
    state.panel.hidden = false;
    link.setAttribute('aria-controls', state.panel.id);
    link.setAttribute('aria-expanded', 'true');
    lastPanel = state;
    anchorPinned = false;
    if (!matchMedia('(min-width: 1200px)').matches) state.panel.scrollIntoView({ block: 'nearest', behavior: 'instant' });
    state.panel.focus({ preventScroll: true });
    return true;
  };
  document.addEventListener('keydown', event => {
    const focused = event.target instanceof Element ? event.target.closest('.reference-card') : null;
    const state = focused ? Array.from(referencePanels.values()).find(value => value.panel === focused) : lastPanel;
    if (event.key === 'Escape' && state && !state.panel.hidden) {
      event.preventDefault();
      closeReference(state);
    }
  });
  document.addEventListener('click', event => {
    const citation = event.target instanceof Element ? event.target.closest('a[data-reference-targets]') : null;
    if (citation && !event.defaultPrevented && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey && openReference(citation)) {
      event.preventDefault();
      return;
    }
    const link = event.target instanceof Element ? event.target.closest('a[href^="#b-"], a.footnote-link') : null;
    if (link && !event.defaultPrevented && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) {
      anchorPinned = true;
      updateAnchorMargin();
      // Run after the browser applies this link's fragment, including same-hash clicks.
      refreshAnchor();
    }
  });
  window.addEventListener('hashchange', () => { anchorPinned = true; refreshAnchor(); });
  window.addEventListener('resize', refreshAnchor);
  window.addEventListener('load', refreshAnchor, { once: true });
  if (toolbar && typeof ResizeObserver !== 'undefined') new ResizeObserver(refreshAnchor).observe(toolbar);
  const releaseAnchor = () => { anchorPinned = false; };
  window.addEventListener('wheel', releaseAnchor, { passive: true });
  window.addEventListener('touchmove', releaseAnchor, { passive: true });
  window.addEventListener('keydown', event => {
    if (['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' '].includes(event.key)) releaseAnchor();
  });
  refreshAnchor();
  document.querySelectorAll('[data-action]').forEach(button => button.addEventListener('click', () => {
    const action = button.dataset.action;
    if (action !== 'theme') refreshAnchor();
    if (action === 'theme') { const next = root.dataset.theme === 'dark' ? 'light' : 'dark'; root.dataset.theme = next; save('theme', next); }
    if (action === 'smaller' || action === 'larger') { const current = parseFloat(getComputedStyle(root).getPropertyValue('--font-size')) || 18; root.style.setProperty('--font-size', Math.max(14, Math.min(30, current + (action === 'larger' ? 2 : -2))) + 'px'); }
    if (action === 'both' || action === 'source' || action === 'target') {
      root.dataset.view = action;
      document.querySelectorAll('[data-language]').forEach(node => { node.hidden = action !== 'both' && node.dataset.language !== action; });
      document.querySelectorAll('[data-view]').forEach(node => node.setAttribute('aria-pressed', String(node.dataset.action === action)));
    }
  }));
});

document.addEventListener('DOMContentLoaded', () => {
  const controls = Array.from(document.querySelectorAll('[data-issue-filter]'));
  const items = Array.from(document.querySelectorAll('[data-issue]'));
  const filter = () => {
    for (const item of items) item.hidden = controls.some(control => control.value && item.dataset[control.dataset.issueFilter] !== control.value);
    const empty = document.querySelector('[data-issue-empty]');
    if (empty) empty.hidden = items.some(item => !item.hidden);
  };
  controls.forEach(control => control.addEventListener('change', filter));
  document.querySelector('[data-action="both"]')?.click();
});
