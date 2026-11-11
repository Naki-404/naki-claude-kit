---
name: naki-typescript
description: Strict TypeScript: compiler settings, type design, narrowing, discriminated unions, generics, async and error handling, validation at module boundaries. Use when writing or reviewing TypeScript, designing types for a feature, fixing type errors, or when code relies on `any`, casts or non-null assertions.
---

# TypeScript

Rules for strict, readable TypeScript in frontend and Node code. Pair with `naki-react` for components
and `naki-error-handling` for failure design. Follow the project rules skill if the project has one
(for example `naki-myapp`).

## When to use

- New modules, API clients, shared types, or a refactor that changes data shapes.
- Type errors that tempt you toward `as`, `any` or `!`.
- Reviewing a diff in `.ts`/`.tsx` files.

## Core rules

1. **Strict mode on.** `"strict": true`, plus `noUncheckedIndexedAccess`, `noImplicitOverride`,
   `exactOptionalPropertyTypes` where the codebase allows. Never loosen the config to fix one error.
2. **No `any`.** Use `unknown` for values you have not checked yet, then narrow. If `any` is unavoidable
   (a broken third-party type), isolate it in one adapter with a comment.
3. **Validate at boundaries, trust inside.** Data from the network, `localStorage`, env vars, files or
   `JSON.parse` is `unknown` until a schema (zod, valibot, or a hand-written guard) checks it.
4. **Casts are a last resort.** `x as Foo` silences the compiler, it does not check anything. Prefer
   narrowing, `satisfies`, or a type guard.
5. **Avoid non-null assertions (`!`).** Handle the `undefined` case or restructure so it cannot occur.
6. **Model states with discriminated unions** instead of bags of optional fields.
7. **Make illegal states unrepresentable.** If two fields must appear together, put them in one object.
8. **Exhaustive switches.** End `switch` over a union with an `assertNever` default so new variants
   fail to compile.
9. **Prefer `type` for unions and compositions, `interface` for object contracts meant to be extended.**
   Be consistent within a codebase.
10. **Export narrow public types.** A module exports what callers need; internal helpers stay private.
11. **`readonly` by default** for arrays and object properties that should not change after creation.
12. **Async functions return typed results and never leave promises floating.** Enable the
    `no-floating-promises` lint rule.

## Narrowing toolbox

| Need | Tool |
|---|---|
| primitive check | `typeof x === "string"` |
| class instance | `x instanceof Date` |
| property presence | `"code" in err` |
| union variant | `switch (event.kind)` |
| custom check | `function isUser(x: unknown): x is User` |
| check a literal keeps its type | `const cfg = {...} satisfies Config` |
| invariant | `function assert(c: unknown, msg: string): asserts c` |

## Workflow

1. Write the data types first: inputs, outputs, states. Name them after domain concepts.
2. Write boundary parsers that turn `unknown` into those types.
3. Implement functions against the types; let inference handle locals, annotate exported signatures.
4. Run `tsc --noEmit` (or `npx tsc -p . --noEmit`) and lint. Fix the cause, not the symptom.
5. For tricky generic helpers, add type-level tests (`expectTypeOf` in Vitest, or `// @ts-expect-error` lines).

## Examples

Discriminated union with exhaustive handling:

```ts
type Fetch<T> =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ok"; data: T }
  | { status: "error"; error: string };

function assertNever(x: never): never {
  throw new Error(`Unhandled variant: ${JSON.stringify(x)}`);
}

function label(s: Fetch<unknown>): string {
  switch (s.status) {
    case "idle": return "Waiting";
    case "loading": return "Loading";
    case "ok": return "Loaded";
    case "error": return `Failed: ${s.error}`;
    default: return assertNever(s);
  }
}
```

Parsing at the boundary:

```ts
import { z } from "zod";

const Alert = z.object({
  id: z.string(),
  severity: z.enum(["low", "medium", "high", "critical"]),
  createdAt: z.coerce.date(),
});
export type Alert = z.infer<typeof Alert>;

export async function getAlert(id: string): Promise<Alert> {
  const res = await fetch(`/api/alerts/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`GET alert ${id}: HTTP ${res.status}`);
  return Alert.parse(await res.json());
}
```

A generic with a useful constraint:

```ts
function groupBy<T, K extends PropertyKey>(items: readonly T[], key: (t: T) => K): Record<K, T[]> {
  const out = {} as Record<K, T[]>;
  for (const item of items) (out[key(item)] ??= []).push(item);
  return out;
}
```

## Async and errors

- `catch (e)` gives `unknown`. Narrow with `e instanceof Error` before reading `.message`.
- Run independent awaits in parallel with `Promise.all`; use `Promise.allSettled` when partial failure is fine.
- Pass `AbortSignal` through long-running calls so callers can cancel.
- For expected failures (validation, not found) a result union `{ ok: true; value } | { ok: false; error }`
  is often clearer than throwing.

## Module boundaries

- One responsibility per module; avoid barrel files that re-export everything (they hurt tree shaking and
  create import cycles).
- Keep types shared between client and server in one place generated from, or checked against, the API schema.
- Use path aliases from `tsconfig` consistently; do not mix relative and alias imports for the same module.

## Checklist

- [ ] `tsc --noEmit` passes with strict settings unchanged.
- [ ] No new `any`, `as` casts or `!` without a written reason.
- [ ] External data parsed before use.
- [ ] Unions handled exhaustively.
- [ ] Exported functions have explicit parameter and return types.
- [ ] No floating promises; errors narrowed before use.

## Common mistakes

| Mistake | Fix |
|---|---|
| `const data = await res.json() as User[]` | parse with a schema |
| `user!.name` | handle `undefined` or narrow earlier |
| `{ loading: boolean; data?: T; error?: string }` | discriminated union |
| `// @ts-ignore` to silence an error | fix the type or use `@ts-expect-error` with a reason |
| `enum` with numeric values leaking to the API | string literal union |
| `Object.keys(obj).forEach(k => obj[k])` type errors | typed entries helper or `Record` key type |
| Widening a literal config with an annotation | `satisfies Config` |
