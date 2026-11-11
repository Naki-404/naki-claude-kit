---
name: naki-frontend-testing
description: Frontend unit and component tests with Vitest and React Testing Library: behavior-focused tests, accessible queries, user-event, network mocking with MSW, hooks, async UI and coverage. Use when writing or fixing tests for React components, hooks or pages, or when tests are flaky, slow or coupled to implementation details.
---

# Frontend testing

Test what the user sees and does, not how the component is built. Pair with `naki-tdd` for the loop,
`naki-e2e-playwright` for full browser flows and `naki-accessibility` for semantics. Follow the project
rules skill if the project has one (for example `naki-myapp`).

## When to use

- New component, hook or page needs tests.
- A test breaks after a refactor that did not change behavior (sign of implementation coupling).
- Tests are flaky, use `waitFor` everywhere, or mock half the app.

## Core rules

1. **Query like a user.** Priority: `getByRole` (with `name`), `getByLabelText`, `getByPlaceholderText`,
   `getByText`, `getByDisplayValue`. Use `getByTestId` only when nothing accessible exists.
2. **Interact with `userEvent`**, not `fireEvent`. Create it with `const user = userEvent.setup()` and await
   every call.
3. **Assert on output**: visible text, roles, form values, calls to a network endpoint. Never assert on state
   variables, hook internals, CSS class names or component instance methods.
4. **Mock the network, not your modules.** Use MSW handlers at the HTTP layer. Mock a module only for true
   outside boundaries (time, random, browser APIs not in jsdom).
5. **Use `findBy*` for things that appear later.** Reserve `waitFor` for assertions that are not a query,
   and never put side effects inside `waitFor`.
6. **One behavior per test**, named as a sentence: `shows an error when the server returns 500`.
7. **Each test sets up its own state.** No order dependence; reset handlers, timers and storage in `afterEach`.
8. **Provide real providers through a `renderWithProviders` helper** (router, query client with retries off,
   theme) instead of mocking them.
9. **Accessibility is testable.** A failing `getByRole("button", { name: "Save" })` often means a real
   accessibility bug. Optionally add `vitest-axe` checks for key screens.
10. **Coverage is a signal, not a goal.** Cover branches that matter: error states, empty states, permissions.

## Query cheatsheet

| Element | Query |
|---|---|
| button | `getByRole("button", { name: /save/i })` |
| link | `getByRole("link", { name: "Docs" })` |
| text input with label | `getByRole("textbox", { name: "Email" })` or `getByLabelText("Email")` |
| checkbox | `getByRole("checkbox", { name: "Remember me" })` |
| heading | `getByRole("heading", { level: 2, name: "Alerts" })` |
| table row | `getAllByRole("row")` then `within(row)` |
| dialog | `getByRole("dialog", { name: "Delete alert" })` |
| absence | `expect(queryByText("Error")).not.toBeInTheDocument()` |

## Workflow

1. List the behaviors: render states (loading, empty, data, error) and interactions.
2. Add MSW handlers for the endpoints the component calls; default to success.
3. Write one test per behavior, overriding handlers with `server.use(...)` for error cases.
4. Run `npx vitest run path/to/file.test.tsx`, then the whole suite.
5. Break the implementation on purpose once (comment out a line) to confirm the test can fail.

## Setup

```ts
// vitest.setup.ts
import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll } from "vitest";
import { cleanup } from "@testing-library/react";
import { server } from "./src/test/server";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => { server.resetHandlers(); cleanup(); });
afterAll(() => server.close());
```

`onUnhandledRequest: "error"` makes a missing handler fail loudly instead of hanging.

## Example

```tsx
import { http, HttpResponse } from "msw";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { server } from "../test/server";
import { AlertList } from "./AlertList";

test("lists alerts and filters by severity", async () => {
  server.use(http.get("/api/alerts", () => HttpResponse.json([
    { id: "a1", title: "Brute force on vpn", severity: "high" },
    { id: "a2", title: "New admin login", severity: "low" },
  ])));
  const user = userEvent.setup();
  render(<AlertList />);

  expect(await screen.findByText("Brute force on vpn")).toBeInTheDocument();
  await user.selectOptions(screen.getByRole("combobox", { name: "Severity" }), "high");
  expect(screen.queryByText("New admin login")).not.toBeInTheDocument();
});

test("shows a retry button when loading fails", async () => {
  server.use(http.get("/api/alerts", () => new HttpResponse(null, { status: 500 })));
  render(<AlertList />);
  expect(await screen.findByRole("button", { name: /retry/i })).toBeInTheDocument();
});
```

## Hooks and time

- Test a hook through a small component that uses it, or with `renderHook` when it has no UI.
- Fake timers: `vi.useFakeTimers()` and `userEvent.setup({ advanceTimers: vi.advanceTimersByTime })`;
  restore with `vi.useRealTimers()` in `afterEach`.
- Freeze dates with `vi.setSystemTime(new Date("2026-01-01T00:00:00Z"))` so snapshots and labels are stable.

## Checklist

- [ ] Queries are role or label based.
- [ ] All `userEvent` calls awaited.
- [ ] Network mocked with MSW; unhandled requests fail.
- [ ] Loading, error and empty states covered.
- [ ] No assertions on internals or class names.
- [ ] Tests pass alone and in any order.
- [ ] No `act(...)` warnings in output.

## Common mistakes

| Mistake | Fix |
|---|---|
| `getByTestId` everywhere | role/label queries; add labels to the component if missing |
| `await waitFor(() => getByText("x"))` | `await findByText("x")` |
| `fireEvent.change` for typing | `await user.type(input, "text")` |
| Mocking `useAlerts` hook directly | mock the HTTP endpoint |
| Large snapshots of whole pages | explicit assertions on what matters |
| Query client with retries on, slow error tests | `retry: false` in the test provider |
| `act` warnings ignored | await the async UI update with `findBy*` |
