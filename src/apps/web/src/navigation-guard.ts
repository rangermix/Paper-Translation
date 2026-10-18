import { useEffect, useRef, useState } from 'react';

type Guard = { ask: () => Promise<boolean>; active: () => boolean };
let currentGuard: Guard | undefined;

/** Ask the mounted form before an action that replaces its current inputs. */
export function requestNavigation(): Promise<boolean> {
  return currentGuard ? currentGuard.ask() : Promise.resolve(true);
}

export function useNavigationGuard(active: boolean) {
  const activeRef = useRef(active);
  activeRef.current = active;
  const pending = useRef<{ promise: Promise<boolean>; resolve: (proceed: boolean) => void } | undefined>(undefined);
  const [requested, setRequested] = useState(false);
  useEffect(() => {
    const ask = () => {
      if (!activeRef.current) return Promise.resolve(true);
      if (!pending.current) {
        let resolve!: (proceed: boolean) => void;
        const promise = new Promise<boolean>(done => { resolve = done; });
        pending.current = { promise, resolve };
        setRequested(true);
      }
      return pending.current.promise;
    };
    const guard: Guard = { ask, active: () => activeRef.current };
    currentGuard = guard;
    return () => {
      if (currentGuard === guard) currentGuard = undefined;
      pending.current?.resolve(false);
      pending.current = undefined;
    };
  }, []);
  useEffect(() => {
    if (!active) return;
    const beforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', beforeUnload);
    return () => window.removeEventListener('beforeunload', beforeUnload);
  }, [active]);
  const resolve = (proceed: boolean) => {
    const request = pending.current;
    pending.current = undefined;
    setRequested(false);
    if (proceed) activeRef.current = false;
    request?.resolve(proceed);
  };
  return { requested, resolve };
}

const positionKey = '__libraryRoutePosition';
type RoutePosition = { index: number; hash: string };

/** Keep the accepted route mounted while a history traversal is being confirmed. */
export function watchGuardedHash(commit: (hash: string) => void) {
  const existing = history.state?.[positionKey] as RoutePosition | undefined;
  let accepted: RoutePosition = existing?.hash === location.hash ? existing : { index: 0, hash: location.hash };
  const stamp = (position: RoutePosition) => history.replaceState({ ...history.state, [positionKey]: position }, '', location.href);
  stamp(accepted);
  let moving: (() => void) | undefined;
  let pending = false;
  let disposed = false;
  const move = (delta: number) => new Promise<void>(resolve => { moving = resolve; history.go(delta); });
  const onChange = async () => {
    if (moving) { const done = moving; moving = undefined; done(); return; }
    if (pending || disposed || location.hash === accepted.hash) return;
    const state = history.state?.[positionKey] as RoutePosition | undefined;
    const target = state?.hash === location.hash ? state : { index: accepted.index + 1, hash: location.hash };
    stamp(target);
    if (!currentGuard?.active()) { accepted = target; commit(target.hash); return; }
    pending = true;
    const delta = target.index - accepted.index;
    // Restore the actual history entry, rather than replacing the destination URL.
    // That preserves both Back and Forward after cancelling a navigation.
    if (delta) await move(-delta);
    const proceed = await requestNavigation();
    if (proceed && !disposed) {
      if (delta) await move(delta);
      accepted = target;
      commit(target.hash);
    }
    pending = false;
  };
  const onClick = (event: MouseEvent) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = (event.target as Element | null)?.closest<HTMLAnchorElement>('a[href]');
    if (!link || link.target && link.target !== '_self' || link.hasAttribute('download')) return;
    const destination = new URL(link.href, location.href);
    if (destination.origin !== location.origin || destination.pathname !== location.pathname || destination.search !== location.search || !destination.hash.startsWith('#/') || destination.hash === accepted.hash || !currentGuard?.active()) return;
    event.preventDefault();
    if (pending) return;
    pending = true;
    void requestNavigation().then(proceed => {
      pending = false;
      if (proceed && !disposed) location.hash = destination.hash;
    });
  };
  window.addEventListener('hashchange', onChange);
  document.addEventListener('click', onClick, true);
  return () => {
    disposed = true;
    window.removeEventListener('hashchange', onChange);
    document.removeEventListener('click', onClick, true);
    moving?.();
  };
}
