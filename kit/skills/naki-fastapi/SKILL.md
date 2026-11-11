---
name: naki-fastapi
description: Building FastAPI services, covering project structure, dependency injection, pydantic v2 schemas, async correctness, authentication, background work and tests with httpx. Use when creating or reviewing FastAPI routers, schemas, dependencies, auth, startup/shutdown logic, or API tests.
---

# FastAPI Services

## When to use

- Adding or reviewing endpoints, routers, schemas or dependencies in a FastAPI app.
- Wiring a database session, auth, settings or external clients into handlers.
- Deciding sync vs async handlers, or where background work should run.
- Writing tests for a FastAPI app.

See `naki-api-design` for URL and status code choices, `naki-postgres` for the data layer, `naki-python-testing` for pytest patterns. Follow the project rules skill if the project has one (for example `naki-myapp`).

## Recommended layout

```text
app/
  main.py            # create_app(), lifespan, router includes
  config.py          # pydantic-settings Settings
  deps.py            # shared dependencies (db session, current user)
  api/
    alerts.py        # APIRouter, thin handlers
  schemas/
    alerts.py        # request/response models
  services/
    alerts.py        # business logic, no FastAPI imports
  db/
    models.py, session.py
tests/
```

Handlers translate HTTP to service calls. Services know nothing about `Request`, `HTTPException` or status codes.

## Core rules

1. **Separate input, output and storage models.** `AlertCreate`, `AlertRead`, ORM `Alert`. Never return ORM objects without a `response_model`; that leaks columns.
2. **Use pydantic v2 idioms:** `model_config = ConfigDict(from_attributes=True, extra="forbid")`, `model_validate`, `model_dump`, `field_validator`. Use `Annotated` for constraints.
3. **Async only when the whole path is async.** An `async def` handler must not call blocking I/O (requests, sync DB drivers, `time.sleep`, heavy CPU). If the library is sync, declare the handler `def` and FastAPI runs it in a threadpool, or wrap with `run_in_threadpool`.
4. **Dependencies for cross-cutting concerns:** session, current user, settings, pagination params. Use `yield` dependencies for setup and teardown.
5. **One app factory and a lifespan.** Create shared clients (httpx, DB engine) in `lifespan`, store on `app.state`, close on shutdown. No module-level connections.
6. **Settings from environment** via `pydantic-settings`; secrets never in code or defaults.
7. **Authorization is per object, not per route only.** Check that the current user owns or may access the specific resource.
8. **Errors:** raise domain exceptions in services, map them to HTTP with exception handlers in one place. Do not leak stack traces or SQL errors to clients.
9. **Background work:** `BackgroundTasks` only for short, losable work (send email, write audit line). Anything that must survive restarts or takes minutes goes to a real queue (Celery, RQ, arq, or a DB-backed job table).
10. **Explicit status codes** on create (`201`) and delete (`204`), and declare error responses in `responses=` for OpenAPI.

## Workflow for a new endpoint

1. Define schemas (create, update, read) with constraints.
2. Write the service function with typed inputs and outputs; unit test it.
3. Add the router handler: dependencies, `response_model`, `status_code`.
4. Map new domain errors to HTTP in the exception handler module.
5. Write API tests with `httpx.AsyncClient` covering success, validation error, auth failure, not found.
6. Check `/docs` renders sensibly; run linters and tests.

## Examples

Schemas and settings:

```python
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings

Severity = Annotated[int, Field(ge=1, le=5)]

class AlertCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Annotated[str, Field(min_length=1, max_length=64)]
    severity: Severity

class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source: str
    severity: int

class Settings(BaseSettings):
    database_url: str
    jwt_secret: str
```

Lifespan, dependencies and a handler:

```python
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, APIRouter, status

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.engine = create_async_engine(get_settings().database_url)
    yield
    await app.state.engine.dispose()

async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with AsyncSession(request.app.state.engine) as session:
        yield session

SessionDep = Annotated[AsyncSession, Depends(get_session)]
UserDep = Annotated[User, Depends(get_current_user)]

router = APIRouter(prefix="/alerts", tags=["alerts"])

@router.post("", response_model=AlertRead, status_code=status.HTTP_201_CREATED)
async def create_alert(body: AlertCreate, session: SessionDep, user: UserDep):
    return await alerts_service.create(session, owner_id=user.id, data=body)
```

Central error mapping:

```python
class NotFound(Exception):
    def __init__(self, what: str) -> None:
        self.what = what

def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotFound)
    async def _not_found(_: Request, exc: NotFound):
        return JSONResponse(status_code=404, content={"error": {"code": "not_found", "message": f"{exc.what} not found"}})
```

Test with dependency override:

```python
import pytest
from httpx import ASGITransport, AsyncClient

@pytest.fixture
async def client(app, session):
    app.dependency_overrides[get_session] = lambda: session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()

async def test_create_alert_rejects_bad_severity(client, auth_headers):
    r = await client.post("/alerts", json={"source": "ids", "severity": 9}, headers=auth_headers)
    assert r.status_code == 422
```

Note: `ASGITransport` does not run lifespan by default; use `asgi-lifespan` or set up state in fixtures.

## Auth notes

- Use OAuth2 bearer with short-lived JWTs or opaque session tokens checked server side. Validate signature, `exp`, `aud`, `iss`; pin the algorithm.
- Hash passwords with argon2 or bcrypt (passlib or `argon2-cffi`), never a plain hash.
- Return `401` for missing or invalid credentials, `403` for authenticated but not allowed, `404` when existence itself is secret.
- Configure CORS with explicit origins; never `allow_origins=["*"]` together with credentials.

## Checklist

- [ ] Every route has `response_model` (or a typed return) and explicit success status.
- [ ] No blocking calls inside `async def`.
- [ ] Object-level authorization checked in service or dependency.
- [ ] Inputs constrained (lengths, ranges, `extra="forbid"`).
- [ ] Shared clients created in lifespan and closed.
- [ ] Domain errors mapped centrally; no stack traces in responses.
- [ ] Tests cover happy path, 422, 401/403, 404.

## Common mistakes

- Using `requests` or a sync SQLAlchemy session inside `async def`, freezing the event loop.
- Creating a new DB engine or httpx client per request.
- Returning ORM objects with relationships that lazy-load outside the session (`MissingGreenlet` in async).
- Putting business logic in handlers so it cannot be tested without HTTP.
- Forgetting to clear `dependency_overrides` between tests.
- Using `BackgroundTasks` for work that must not be lost.
- Catching `Exception` in handlers and returning `200` with an error field.
