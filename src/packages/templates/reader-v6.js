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
  const save = (key, value) => { try { localStorage.setItem('reader-v6:' + key, value); } catch (_) { if (notice) notice.hidden = false; } };
  const read = (key) => { try { return localStorage.getItem('reader-v6:' + key); } catch (_) { if (notice) notice.hidden = false; return null; } };
  const theme = read('theme');
  if (theme === 'dark' || theme === 'light') root.dataset.theme = theme;
  const fontSelect = document.querySelector('[data-font-select]');
  const applyFont = value => {
    const font = ['default', 'serif', 'sans', 'monospace'].includes(value) ? value : 'default';
    root.dataset.font = font;
    if (fontSelect) fontSelect.value = font;
    return font;
  };
  applyFont(read('font'));
  // Keep anchors visible when the toolbar wraps or its font size changes.
  const toolbar = document.querySelector('.toolbar');
  const blocks = Array.from(document.querySelectorAll('[data-block-id]'));
  let anchorPinned = Boolean(location.hash);
  let pendingFrame = 0;
  const hashTarget = () => {
    try {
      const id = decodeURIComponent(location.hash.slice(1));
      const target = id.startsWith('b-') ? document.getElementById(id) : null;
      return target && target.hasAttribute('data-block-id') ? target : null;
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
  document.addEventListener('click', event => {
    const link = event.target instanceof Element ? event.target.closest('a[href^="#b-"]') : null;
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
