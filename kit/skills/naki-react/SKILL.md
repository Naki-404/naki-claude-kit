---
name: naki-react
description: React 18/19 with Vite: component design, hooks discipline, state placement, data fetching, effects, and rendering performance. Use when writing, reviewing, or refactoring React components, custom hooks, state management, or when a page renders slowly or re-renders too often.
---

# React

Practical rules for React 18/19 apps built with Vite. Pair with `naki-typescript` for types,
`naki-frontend-testing` for tests and `naki-accessibility` for UI semantics. Follow the project
rules skill if the project has one (for example `naki-myapp`).

## When to use

- Creating or changing components, hooks, context providers or pages.
- Deciding where state lives, or how data is fetched and cached.
- Debugging stale values, infinite effect loops, flicker or slow renders.
- Reviewing a TSX/JSX diff.

## Core rules

1. **Components are pure functions of props and state.** No side effects during render: no fetches,
   no subscriptions, no writes to module variables, no `Math.random()` that changes output between renders.
2. **Call hooks unconditionally, at the top level.** Never inside `if`, loops, or after an early return.
3. **Derive, do not sync.** If a value can be computed from props or state, compute it during render.
   Do not mirror it into another `useState` with an effect.
4. **Effects are for synchronizing with outside systems** (DOM APIs, timers, sockets, non-React widgets).
   If no outside system is involved, you probably do not need an effect.
5. **Every effect that subscribes must clean up.** Return a function that removes listeners, clears timers
   and aborts requests.
6. **Dependency arrays are honest.** List every reactive value the effect reads. Fix loops by restructuring
   (move the function inside the effect, use a functional update), not by deleting dependencies.
7. **State lives as low as possible and as high as necessary.** Lift only to the nearest common parent
   that needs it. Global stores are for truly cross-cutting state (session, theme, feature flags).
8. **Server data is not UI state.** Use a fetching/caching library (TanStack Query, SWR) or framework
   loaders for remote data. Keep `useState` for local UI state (open, selected, draft input).
9. **Keys are stable identities.** Use record ids, never array indexes for lists that can reorder,
   insert or delete.
10. **Never mutate state.** Create new arrays and objects (`[...items, x]`, `{ ...obj, k: v }`).
11. **Measure before memoizing.** Reach for `memo`, `useMemo`, `useCallback` when the profiler shows a
    real cost, or when a stable reference is required by a dependency array or a memoized child.
12. **Render untrusted HTML only after sanitizing.** Avoid `dangerouslySetInnerHTML`; if unavoidable,
    sanitize with a vetted library and keep it in one wrapper component.

## State placement decision

| Situation | Put state in |
|---|---|
| Used by one component | `useState` in that component |
| Shared by siblings | nearest common parent, pass props |
| Deep tree, rarely changes (theme, user) | context |
| Remote data with caching, refetch, retries | query library |
| URL-shareable (filters, page, tab) | search params |
| Complex transitions with many fields | `useReducer` |
| Form inputs | form library or uncontrolled inputs with `FormData` |

## Workflow

1. Sketch the component tree and mark which component owns each piece of state.
2. Write the component with props typed explicitly; keep it under roughly 150 lines, split by responsibility.
3. Extract logic reused in two or more places into a custom hook named `useX`.
4. Add loading, empty and error states before polishing the happy path.
5. Write behavior tests (`naki-frontend-testing`).
6. Run the dev build, type check and lint; open the React DevTools profiler if anything feels slow.

## Data fetching

- One request owner per resource. Components ask for data via a hook (`useIncidents(filters)`), they do not
  call `fetch` directly.
- Always handle `isLoading`, `isError` and empty results in the UI.
- Abort or ignore stale responses. Query libraries do this; hand-written effects need an `AbortController`.
- Avoid waterfalls: start independent requests in parallel, prefetch on hover or route loaders where it helps.

```tsx
function useIncident(id: string) {
  const [state, setState] = useState<{ data?: Incident; error?: Error }>({});
  useEffect(() => {
    const ctrl = new AbortController();
    fetch(`/api/incidents/${id}`, { signal: ctrl.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((data) => setState({ data }))
      .catch((error) => { if (!ctrl.signal.aborted) setState({ error }); });
    return () => ctrl.abort();
  }, [id]);
  return state;
}
```

Prefer a query library in real code; the example shows the minimum a manual effect needs.

## Performance

- Find the cause first: React DevTools profiler, "Highlight updates", browser Performance tab.
- Common real causes: a context value recreated every render, a parent holding fast-changing state
  (input text, mouse position) above a large subtree, rendering thousands of rows.
- Fixes in order of preference: move state down, split context, pass children as props, virtualize long lists,
  then memoize.
- Use `useTransition` or `useDeferredValue` for expensive updates triggered by typing.
- Lazy-load routes and heavy widgets with `React.lazy` and `Suspense`.
- Check bundle size with `vite build` output; avoid importing whole utility libraries for one function.

## Checklist

- [ ] No side effects in render; hooks at top level.
- [ ] No state that duplicates props or derivable values.
- [ ] Every effect has correct dependencies and a cleanup where needed.
- [ ] Lists use stable keys.
- [ ] Loading, error and empty states exist.
- [ ] Interactive elements are real buttons/links with accessible names.
- [ ] No `dangerouslySetInnerHTML` with unsanitized input.
- [ ] Type check, lint and tests pass.

## Common mistakes

| Mistake | Fix |
|---|---|
| `useEffect(() => setFull(first + last), [first, last])` | `const full = first + last` |
| Fetch in effect without abort, causing race on fast id changes | `AbortController` or query library |
| `onClick={() => setCount(count + 1)}` called twice in one tick | `setCount((c) => c + 1)` |
| Object literal in context `value` every render | `useMemo` the value or split the context |
| `key={index}` on a sortable list | `key={item.id}` |
| Resetting child state with an effect when a prop changes | give the child `key={prop}` |
| `div` with `onClick` as a button | `<button type="button">` |
| Suppressing the exhaustive-deps lint rule | restructure the effect |

## Example: derive and reset instead of syncing

```tsx
function IncidentList({ incidents, query }: { incidents: Incident[]; query: string }) {
  const visible = incidents.filter((i) => i.title.toLowerCase().includes(query.toLowerCase()));
  if (visible.length === 0) return <p>No incidents match "{query}".</p>;
  return (
    <ul>
      {visible.map((i) => <IncidentRow key={i.id} incident={i} />)}
    </ul>
  );
}

// Reset the editor's draft when a different incident is opened.
<IncidentEditor key={selected.id} incident={selected} />
```
