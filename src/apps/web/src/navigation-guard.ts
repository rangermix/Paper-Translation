import { useEffect, useRef, useState } from 'react';

type Guard = { ask: () => Promise<boolean>; active: () => boolean };
const guards = new Set<Guard>();
const hasActiveGuard = () => [...guards].some(guard => guard.active());

/** Ask the mounted form before an action that replaces its current inputs. */
export async function requestNavigation(): Promise<boolean> {
  for (const guard of [...guards].reverse()) {
    if (guards.has(guard) && guard.active() && !await guard.ask()) return false;
  }
  return true;
}

export function useNavigationGuard(active: boolean) {
  const activeRef = useRef(active);
  activeRef.current = active;
  const pending = useRef<{ promise: Promise<boolean>; resolve: (proceed: boolean) => void } | undefined>(undefined);
  const [requested, setRequested] = useState(false);
  const request = () => {
    if (!activeRef.current) return Promise.resolve(true);
    if (!pending.current) {
      let resolve!: (proceed: boolean) => void;
      const promise = new Promise<boolean>(done => { resolve = done; });
      pending.current = { promise, resolve };
      setRequested(true);
    }
    return pending.current.promise;
  };
  useEffect(() => {
    const guard: Guard = { ask: request, active: () => activeRef.current };
    guards.add(guard);
    return () => {
      guards.delete(guard);
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
  return { requested, resolve, request };
}

const positionKey = '__libraryRoutePosition';
type RoutePosition = { index: number; hash: string };

/** Keep the accepted route mounted while a history traversal is being confirmed. */
export function watchGuardedHash(commit: (hash: string) => void) {
  const existing = history.state?.[positionKey] as RoutePosition | undefined;
  let accepted: RoutePosition = existing?.hash === location.hash ? existing : { index: 0, hash: location.hash };
  let current = accepted;
  const entries = new Map<number, string>([[accepted.index, accepted.hash]]);
  const traversals: RoutePosition[] = [];
  const stamp = (position: RoutePosition) => history.replaceState({ ...history.state, [positionKey]: position }, '', location.href);
  stamp(accepted);
  let moving: (() => void) | undefined;
  let pending = false;
  let disposed = false;
  const append = (hash: string) => {
    const position = { index: current.index + 1, hash };
    // A new hash or pushState after Back truncates the browser's forward branch.
    for (const index of entries.keys()) if (index >= position.index) entries.delete(index);
    entries.set(position.index, hash);
    current = position;
    return position;
  };
  const observe = (event: HashChangeEvent) => {
    const hash = new URL(event.newURL).hash;
    const state = history.state?.[positionKey] as RoutePosition | undefined;
    const traversal = traversals.findIndex(position => position.hash === hash);
    const recorded = traversal >= 0 ? traversals.splice(traversal, 1)[0] : hash === location.hash && state?.hash === hash ? state : undefined;
    if (recorded) {
      current = recorded;
      entries.set(recorded.index, recorded.hash);
    } else {
      // More than one direct hash edit can be queued before a hashchange runs.
      // Count each new entry from the last observed browser position.
      append(hash);
      if (hash === location.hash) stamp(current);
    }
  };
  const onPopState = (event: PopStateEvent) => {
    const position = event.state?.[positionKey] as RoutePosition | undefined;
    if (position?.hash !== location.hash) return;
    if (position.hash === current.hash) {
      // Traversing between two entries with the same hash emits no hashchange.
      // Complete that move here so a resolved prompt cannot strand navigation.
      current = position;
      entries.set(position.index, position.hash);
      if (moving) { const done = moving; moving = undefined; done(); }
      else if (!pending && position.hash === accepted.hash) accepted = position;
    } else traversals.push(position);
  };
  const move = (delta: number) => new Promise<void>(resolve => { moving = resolve; history.go(delta); });
  const reach = async (position: RoutePosition): Promise<RoutePosition> => {
    if (current.index === position.index && current.hash === position.hash) return current;
    if (entries.get(position.index) === position.hash) {
      await move(position.index - current.index);
      return current;
    }
    // A user-created branch can remove the accepted entry while the prompt is
    // open. Restore only that route as a new entry; surviving history is kept.
    const restored = append(position.hash);
    history.pushState({ [positionKey]: restored }, '', restored.hash || location.pathname + location.search);
    return restored;
  };
  const onChange = async (event: HashChangeEvent) => {
    if (disposed) return;
    observe(event);
    if (new URL(event.newURL).hash !== location.hash) return;
    if (moving) { const done = moving; moving = undefined; done(); return; }
    if (pending || current.hash === accepted.hash) return;
    const target = current;
    if (!hasActiveGuard()) { accepted = target; commit(target.hash); return; }
    pending = true;
    accepted = await reach(accepted);
    const proceed = await requestNavigation();
    if (disposed) return;
    accepted = await reach(accepted);
    if (proceed && !disposed) {
      accepted = await reach(target);
      commit(accepted.hash);
    }
    pending = false;
  };
  const onClick = (event: MouseEvent) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = (event.target as Element | null)?.closest<HTMLAnchorElement>('a[href]');
    if (!link || link.target && link.target !== '_self' || link.hasAttribute('download')) return;
    const destination = new URL(link.href, location.href);
    if (destination.origin !== location.origin || destination.pathname !== location.pathname || destination.search !== location.search || !destination.hash.startsWith('#/') || destination.hash === accepted.hash || !hasActiveGuard()) return;
    event.preventDefault();
    if (pending) return;
    pending = true;
    void requestNavigation().then(async proceed => {
      if (disposed) return;
      accepted = await reach(accepted);
      pending = false;
      if (proceed && !disposed) location.hash = destination.hash;
    });
  };
  window.addEventListener('hashchange', onChange);
  window.addEventListener('popstate', onPopState);
  document.addEventListener('click', onClick, true);
  return () => {
    disposed = true;
    window.removeEventListener('hashchange', onChange);
    window.removeEventListener('popstate', onPopState);
    document.removeEventListener('click', onClick, true);
    moving?.();
  };
}
