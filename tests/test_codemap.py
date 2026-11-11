"""Tests for the Code Map engine and its MCP server. Run: python -m unittest -v"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
TOOL = KIT / "tools" / "codemap.py"
sys.path.insert(0, str(KIT / "tools"))
import codemap  # noqa: E402  (path set above)

PY_FILES = {
    "app/__init__.py": "",
    "app/models.py": '''"""Data models."""


class Base:
    pass


class Alert(Base):
    """A security alert."""

    def score(self) -> int:
        return self.weight()

    def weight(self) -> int:
        return 3
''',
    "app/service.py": '''from .models import Alert
from app import models


def triage_alert(raw: dict) -> str:
    """Decide what an alert is."""
    alert = Alert()
    if alert.score() > 2:
        return notify(raw)
    return "ignore"


def notify(raw: dict) -> str:
    return helper()


def helper() -> str:
    return "sent"
''',
    "app/broken.py": "def oops(:\n    pass\n",
    "lib/__init__.py": "from .impl import run_job\n",
    "lib/impl.py": "def run_job() -> None:\n    pass\n",
    "app/worker.py": "from lib import run_job\n\n\ndef work() -> None:\n    run_job()\n",
    "tests/test_alerts.py": "from app.models import Alert\n\n\n\ndef test_score():\n    assert Alert().score() == 3\n",
    "app/api.py": '''from fastapi import APIRouter

router = APIRouter(prefix="/api/alerts")


@router.get("")
def list_alerts():
    return []


@router.get("/stats")
def alert_stats():
    return {}


@router.get("/{alert_id}")
def get_alert(alert_id: int):
    return {}


@router.post("/{alert_id}/close")
def close_alert(alert_id: int):
    return {}
''',
}
JS_FILES = {
    "web/src/api/client.ts": """export async function fetchAlerts(page: number): Promise<string[]> {
  const res = await request('/alerts?page=' + page)
  return res
}
function request(url: string) {
  return fetch(url)
}
""",
    "web/src/pages/AlertsPage.tsx": """import { fetchAlerts } from '../api/client'
import AlertRow from './AlertRow'

export default function AlertsPage() {
  const rows = fetchAlerts(1) // fetchAlerts in a comment is not a call to anything else
  return <div><AlertRow /></div>
}
""",
    "web/src/pages/AlertRow.tsx": """export default function AlertRow() {
  return <span>row</span>
}
""",
    "web/src/App.tsx": """import { lazy } from 'react'
import Row from './pages/AlertRow'
const AlertsPage = lazy(() => import('./pages/AlertsPage'))

export default function App() {
  return <main><AlertsPage /><Row /></main>
}
""",
    "web/src/api/alerts.ts": """export function loadAlerts() { return api.get('/api/alerts') }
export function loadStats() { return api.get(`/api/alerts/stats`) }
export function loadAlert(id: number) { return api.get<Alert>(`/api/alerts/${id}?full=1`) }
export function closeAlert(id: number) { return fetch(`${API}/api/alerts/${id}/close`, { method: 'POST' }) }
// api.delete('/api/alerts/1') is only a comment
""",
    "web/node_modules/lib/index.js": "export function ignored() {}\n",
}


class CodeMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = Path(cls.tmp.name)
        for rel, text in {**PY_FILES, **JS_FILES}.items():
            f = cls.repo / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text, encoding="utf-8")
        (cls.repo / ".git" / "info").mkdir(parents=True)
        cls.result = codemap.build(cls.repo)
        cls.m = codemap.CodeMap(cls.repo)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_build_counts_and_skips_vendor_dirs(self) -> None:
        self.assertEqual(self.result["files"], 14)
        self.assertNotIn("web/node_modules/lib/index", self.m.nodes)
        self.assertIn(".codemap/", (self.repo / ".git" / "info" / "exclude").read_text(encoding="utf-8"))

    def test_python_symbols_and_signature(self) -> None:
        s = self.m.symbol("triage_alert")
        self.assertEqual(s["symbol"], "app.service.triage_alert")
        self.assertEqual(s["signature"], "def triage_alert(raw: dict) -> str")
        self.assertEqual(s["doc"], "Decide what an alert is.")
        callees = " ".join(s["callees"])
        self.assertIn("app.service.notify", callees)
        self.assertIn("app.models.Alert", callees)

    def test_self_method_calls_and_inheritance(self) -> None:
        self.assertIn("app.models.Alert.weight", " ".join(self.m.symbol("app.models.Alert.score")["callees"]))
        self.assertIn("app.models.Base", " ".join(self.m.symbol("Alert")["inherits"]))

    def test_path_through_calls(self) -> None:
        p = self.m.path("triage_alert", "helper")
        self.assertEqual(p["hops"], 2)
        self.assertTrue(p["directed"])

    def test_ts_imports_calls_and_jsx(self) -> None:
        page = self.m.symbol("AlertsPage")
        callees = " ".join(page["callees"])
        self.assertIn("web/src/api/client#fetchAlerts", callees)
        self.assertIn("web/src/pages/AlertRow#AlertRow", callees)
        self.assertIn("web/src/api/client#request", " ".join(self.m.symbol("fetchAlerts")["callees"]))

    def test_python_reexport_through_package_init(self) -> None:
        self.assertIn("lib.impl.run_job", " ".join(self.m.symbol("work")["callees"]))

    def test_lazy_and_renamed_default_imports(self) -> None:
        callees = " ".join(self.m.symbol("web/src/App#App")["callees"])
        self.assertIn("web/src/pages/AlertsPage#AlertsPage", callees)
        self.assertIn("web/src/pages/AlertRow#AlertRow", callees)

    def test_undirected_path_ignores_shared_imports(self) -> None:
        self.assertIsNone(self.m.path("work", "helper")["path"])

    def test_search_skips_tests_unless_asked(self) -> None:
        self.assertTrue(all("/tests/" not in r["where"] for r in self.m.search("alert")["results"]))

    def test_routes_get_router_prefix(self) -> None:
        self.assertEqual(self.m.symbol("get_alert")["route"], "GET /api/alerts/{alert_id}")
        self.assertEqual(self.m.symbol("list_alerts")["route"], "GET /api/alerts")
        self.assertEqual(self.m.routes()["routes"], 4)

    def test_frontend_calls_link_to_handlers(self) -> None:
        def calls(name: str) -> str:
            return " ".join(self.m.symbol(name)["http_calls"])

        self.assertIn("app.api.list_alerts", calls("loadAlerts"))
        self.assertIn("app.api.alert_stats", calls("loadStats"))  # literal /stats beats /{alert_id}
        self.assertIn("app.api.get_alert", calls("loadAlert"))  # template parameter and query string
        self.assertIn("app.api.close_alert", calls("closeAlert"))  # fetch with method POST and a base URL
        self.assertIn("web/src/api/alerts#loadAlert", " ".join(self.m.symbol("get_alert")["http_callers"]))

    def test_http_call_in_comment_is_ignored(self) -> None:
        self.assertEqual(self.m.routes()["frontend_calls_linked"], 4)

    def test_tests_covering_a_symbol(self) -> None:
        direct = self.m.tests("helper")
        self.assertEqual(direct["tests"], [])  # nothing in tests/ calls it yet
        indirect = self.m.tests("app.models.Alert.weight")
        self.assertEqual(indirect["direct"], 0)
        self.assertEqual(indirect["indirect"], 1)
        self.assertEqual(indirect["test_files"], ["tests/test_alerts.py"])
        self.assertEqual(indirect["tests"][0]["via"], ["app.models.Alert.score L11"])
        sym = self.m.symbol("app.models.Alert.score")
        self.assertEqual(sym["tested_by"], ["tests.test_alerts.test_score L5"])
        self.assertNotIn("tests.test_alerts.test_score L5", sym["callers"])

    def test_parse_error_is_recorded_not_fatal(self) -> None:
        self.assertIn("app/broken.py", self.m.stats()["errors"])

    def test_search_and_hubs(self) -> None:
        top = self.m.search("triage alert")["results"][0]["symbol"]
        self.assertEqual(top, "app.service.triage_alert")
        self.assertTrue(self.m.hubs(5)["hubs"])

    def test_file_listing(self) -> None:
        syms = [s["symbol"] for s in self.m.file("app/models.py")["symbols"]]
        self.assertEqual(syms[:2], ["app.models", "app.models.Base"])

    def test_incremental_build_reparses_only_changed(self) -> None:
        f = self.repo / "app" / "service.py"
        f.write_text(f.read_text(encoding="utf-8") + "\n\ndef extra() -> None:\n    helper()\n", encoding="utf-8")
        r = codemap.build(self.repo)
        self.assertEqual(r["parsed"], 1)
        self.assertIn("app.service.extra", codemap.CodeMap(self.repo).nodes)


class CodeMapServerTests(unittest.TestCase):
    def test_mcp_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".claude").mkdir()
            (root / ".claude" / "kit.json").write_text(json.dumps({"codemap": {"dirs": ["."]}}), encoding="utf-8")
            (root / "m.py").write_text("def a():\n    b()\n\n\ndef b():\n    pass\n", encoding="utf-8")
            codemap.build(root)
            msgs = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "codemap_path", "arguments": {"source": "a", "target": "b"}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "nope", "arguments": {}}},
            ]
            env = {k: v for k, v in __import__("os").environ.items() if k != "CLAUDE_PROJECT_DIR"}
            r = subprocess.run([sys.executable, str(TOOL), "serve"], input="".join(json.dumps(m) + "\n" for m in msgs),
                               capture_output=True, text=True, cwd=root, env=env, timeout=60)
            out = [json.loads(x) for x in r.stdout.splitlines()]
            self.assertEqual(out[0]["result"]["serverInfo"]["name"], "naki-codemap")
            self.assertEqual(len(out[1]["result"]["tools"]), 10)
            self.assertEqual(json.loads(out[2]["result"]["content"][0]["text"])["hops"], 1)
            self.assertEqual(out[3]["error"]["code"], -32602)


BACKEND = {
    "src/main/resources/application.properties": (
        "deal.events.topic=${KAFKA_DEAL_TOPIC:DEAL_EVENTS_TEST}\n"
        "notify.url=${NOTIFY_URL:https://gateway.example.com/notify}\n"),
    "src/main/java/com/example/shop/controller/DealController.java": '''package com.example.shop.controller;

import com.example.shop.service.DealService;
import org.springframework.web.bind.annotation.*;

/** Deals API. "class Fake {" in a comment must not count. */
@RestController
@RequestMapping("/deal")
@RequiredArgsConstructor
public class DealController {

    private final DealService dealService;

    @GetMapping("/load/{id}")
    public DealDto load(@PathVariable("id") Long id) {
        return dealService.find(id);
    }

    @GetMapping("/user/image")
    public byte[] image() {
        return null;
    }

    @RequestMapping(value = {"/status", "/state"}, method = RequestMethod.PATCH)
    public void changeStatus(@RequestBody StatusRequest request) {
        String note = "dealService.ghost(1)";
        dealService.changeStatus(request.getId(), request.getStatus());
    }
}
''',
    "src/main/java/com/example/shop/service/DealService.java": '''package com.example.shop.service;

public interface DealService {
    DealDto find(Long id);

    void changeStatus(Long id, String status);
}
''',
    "src/main/java/com/example/shop/service/impl/DealServiceImpl.java": '''package com.example.shop.service.impl;

import com.example.shop.service.DealService;
import com.example.shop.client.NotifyClient;
import com.example.db.tables.Deal;
import com.example.db.tables.AppUser;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.kafka.core.KafkaTemplate;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class DealServiceImpl implements DealService {
    private static final String AUDIT = "DEAL_AUDIT_TEST";
    private static final String EVENT_KEY = "deal-event-key";
    private final DSLContext dsl;
    private final KafkaTemplate<String, String> kafkaTemplate;
    private final NotifyClient notifyClient;
    private final EventKafkaProducer eventProducer;
    private final MailSender mailSender;

    @Value("${deal.events.topic}")
    private String dealTopic;

    @Override
    public DealDto find(Long id) {
        Deal deal = Deal.DEAL;
        AppUser user = AppUser.APP_USER;
        return dsl.selectFrom(deal).leftJoin(user).on(deal.USER_ID.eq(user.ID)).where(deal.ID.eq(id)).fetchOneInto(DealDto.class);
    }

    @Override
    public void changeStatus(Long id, String status) {
        Deal deal = Deal.DEAL;
        dsl.update(deal).set(deal.STATUS, status).where(deal.ID.eq(id)).execute();
        kafkaTemplate.send(dealTopic, String.valueOf(id));
        kafkaTemplate.send(AUDIT, status);
        eventProducer.sendMessage(dealTopic, "key", status);
        eventProducer.sendMessage(status, "key", status);
        eventProducer.sendMessage("just-a-key", status);
        eventProducer.sendMessage(EVENT_KEY, status);
        mailSender.send(dealTopic);
        notifyClient.push(new NotifyRequest(id));
        audit(Map.of("id", id));
    }

    private void audit(Map<String, Object> data) {
        helper().run();
    }

    private Runnable helper() {
        return () -> {};
    }
}
''',
    "src/main/java/com/example/shop/client/NotifyClient.java": '''package com.example.shop.client;

@FeignClient(name = "Notify", url = "${notify.url}")
public interface NotifyClient {
    @PostMapping("/notification/push")
    void push(@RequestBody NotifyRequest request);
}
''',
    "src/test/java/com/example/shop/service/impl/DealServiceImplTest.java": '''package com.example.shop.service.impl;

class DealServiceImplTest {
    private DealServiceImpl service;

    @Test
    void changesStatus() {
        service.changeStatus(1L, "DONE");
        kafkaTemplate.send("test-topic", "x");
    }
}
''',
}

NOTIFY = {
    "src/main/resources/application.yml": "app:\n  kafka:\n    deal-topic: ${KAFKA_DEALS:DEAL_EVENTS_TEST}\n    mdm-topics: mdm_a,mdm_b\n",
    "src/main/java/com/example/notify/NotificationController.java": '''package com.example.notify;

@RestController
public class NotificationController {
    @PostMapping(path = "/notification/push", consumes = "application/json")
    public void push(@RequestBody Object body) {
    }

    @GetMapping("/user/{userId}")
    public Object user(@PathVariable String userId) {
        return null;
    }
}
''',
    "src/main/java/com/example/notify/DealListener.java": '''package com.example.notify;

@Component
public class DealListener {
    @KafkaListener(topics = "${app.kafka.deal-topic}", groupId = "g")
    public void onMessage(ConsumerRecord<String, String> record) {
    }

    @KafkaListener(topics = "#{'${app.kafka.mdm-topics}'.split(',')}")
    public void onMdm(ConsumerRecord<String, String> record) {
    }
}
''',
}

FRONT = {
    "src/api/urls.ts": "export const NOTIFY_BASE = `${notifyServiceUrl}/notification`\n",
    "src/api/user.ts": '''import { NOTIFY_BASE } from "./urls"
const base = `${notifyServiceUrl}/notification`
export function userViaHint(userId: string) {
  return api.get(`${notifyServiceUrl}/user/${userId}`)
}
export function userNoHint(userId: string) {
  return api.get(`/user/${userId}`)
}
export function pushImported(d: object) {
  return api.post(`${NOTIFY_BASE}/push`, d)
}
export function pushTemplateBase(d: object) {
  return api.post(`${base}/push`, d)
}
''',
    "src/api/deal.ts": '''const BASE_URL = "/api/deal"
export function loadDeal(id: number) {
  return api
    .get<Deal>(`${BASE_URL}/load/${id}`)
}
export function changeStatus(data: StatusRequest) {
  return apiRequest().patch(BASE_URL + "/status", data)
}
export function loadOld(id: number) {
  return api.get("/api/deal/load/" + id)
}
''',
}


def write_tree(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    (root / ".git" / "info").mkdir(parents=True, exist_ok=True)


class JavaCodeMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        cls.back, cls.notify, cls.front = base / "shop-backend", base / "notify-service", base / "shop-frontend"
        write_tree(cls.back, BACKEND)
        write_tree(cls.notify, NOTIFY)
        write_tree(cls.front, FRONT)
        for r in (cls.back, cls.notify, cls.front):
            codemap.build(r)
        cls.m = codemap.CodeMap(cls.back)
        cls.ws = codemap.Workspace([cls.back, cls.notify, cls.front])

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_types_methods_and_comment_noise(self) -> None:
        n = self.m.nodes
        self.assertIn("com.example.shop.controller.DealController", n)
        self.assertIn("com.example.shop.controller.DealController.load", n)
        self.assertNotIn("com.example.shop.controller.Fake", n)
        self.assertIn("@RestController", n["com.example.shop.controller.DealController"]["doc"])
        self.assertIn("DealDto load(", n["com.example.shop.controller.DealController.load"]["sig"])
        self.assertEqual(n["com.example.shop.service.DealService"]["doc"], "interface")

    def test_spring_routes_with_class_prefix_and_arrays(self) -> None:
        self.assertEqual(self.m.symbol("DealController.load")["route"], "GET /deal/load/{id}")
        route = self.m.symbol("DealController.changeStatus")["route"]
        self.assertIn("PATCH /deal/status", route)
        self.assertIn("PATCH /deal/state", route)
        self.assertEqual(self.m.routes()["routes"], 3)

    def test_calls_through_field_type_and_interface(self) -> None:
        s = self.m.symbol("DealController.changeStatus")
        self.assertIn("com.example.shop.service.DealService.changeStatus L6", s["callees"])
        self.assertNotIn("ghost", json.dumps(s))
        impl = self.m.symbol("com.example.shop.service.impl.DealServiceImpl.changeStatus")
        self.assertIn("com.example.shop.service.DealService.changeStatus L6", impl["implements"])
        self.assertIn("com.example.shop.controller.DealController.changeStatus L25", impl["callers_via_interface"])
        path = self.m.path("DealController.changeStatus", "DealServiceImpl.audit")
        self.assertEqual(path["hops"], 3)

    def test_jooq_tables_read_and_written(self) -> None:
        self.assertEqual(self.m.symbol("DealServiceImpl.changeStatus")["writes_tables"], ["table:deal"])
        self.assertEqual(sorted(self.m.symbol("DealServiceImpl.find")["reads_tables"]), ["table:app_user", "table:deal"])
        data = self.m.data("table", "deal")
        row = next(r for r in data["shown"] if r["table"] == "deal")
        self.assertEqual(row["writers"], 1)
        self.assertEqual(row["readers"], 1)

    def test_kafka_topics_from_properties_and_constants(self) -> None:
        pubs = self.m.symbol("DealServiceImpl.changeStatus")["publishes"]
        self.assertEqual(sorted(pubs), ["topic:DEAL_AUDIT_TEST", "topic:DEAL_EVENTS_TEST"])
        self.assertEqual(len([e for e in self.m.out["com.example.shop.service.impl.DealServiceImpl.changeStatus"] if e[1] == "publishes"]), 2)

    def test_keys_and_test_code_are_not_topics(self) -> None:
        self.assertNotIn("topic:just-a-key", self.m.nodes)
        self.assertNotIn("topic:deal-event-key", self.m.nodes)
        self.assertNotIn("topic:test-topic", self.m.nodes)

    def test_spel_split_topics(self) -> None:
        notify = codemap.CodeMap(self.notify)
        self.assertEqual(notify.symbol("DealListener.onMdm")["consumes"], ["topic:mdm_a", "topic:mdm_b"])

    def test_tests_reach_through_calls(self) -> None:
        self.assertIn("DealServiceImplTest", json.dumps(self.m.tests("DealServiceImpl.changeStatus")))

    def test_workspace_links_services(self) -> None:
        ws = self.ws
        front = ws.symbol("shop-frontend:src/api/deal#loadDeal")["http_calls"]
        self.assertEqual(front, ["shop-backend:com.example.shop.controller.DealController.load L15"])
        self.assertEqual(ws.symbol("shop-frontend:src/api/deal#changeStatus")["http_calls"],
                         ["shop-backend:com.example.shop.controller.DealController.changeStatus L25"])
        self.assertEqual(ws.symbol("shop-frontend:src/api/deal#loadOld")["http_calls"],
                         ["shop-backend:com.example.shop.controller.DealController.load L15"])
        feign = ws.symbol("shop-backend:com.example.shop.client.NotifyClient.push")["http_calls"]
        self.assertEqual(feign, ["notify-service:com.example.notify.NotificationController.push L6"])
        topic = ws.symbol("topic:DEAL_EVENTS_TEST")
        self.assertIn("notify-service:com.example.notify.DealListener.onMessage L6", topic["consumers"])
        self.assertIn("shop-backend:com.example.shop.service.impl.DealServiceImpl.changeStatus L33", topic["producers"])
        chain = ws.path("shop-frontend:src/api/deal#changeStatus", "notify-service:com.example.notify.DealListener.onMessage")
        self.assertTrue(chain["directed"])
        self.assertIn("topic:DEAL_EVENTS_TEST", chain["path"])

    def test_workspace_picks_the_right_service(self) -> None:
        ws = codemap.Workspace([self.back, self.notify, self.front], {"shop-frontend": ["shop-backend"]})

        def calls(fn: str) -> list[str]:
            return ws.symbol(f"shop-frontend:src/api/user#{fn}")["http_calls"]

        self.assertEqual(calls("userViaHint"), ["notify-service:com.example.notify.NotificationController.user L10"])
        self.assertEqual(calls("userNoHint"), ["notify-service:com.example.notify.NotificationController.user L10"])
        self.assertEqual(calls("pushImported"), ["notify-service:com.example.notify.NotificationController.push L6"])
        self.assertEqual(calls("pushTemplateBase"), ["notify-service:com.example.notify.NotificationController.push L6"])
        self.assertEqual(ws.symbol("shop-frontend:src/api/deal#loadDeal")["http_calls"],
                         ["shop-backend:com.example.shop.controller.DealController.load L15"])

    def test_workspace_reloads_after_rebuild(self) -> None:
        f = self.notify / "src/main/java/com/example/notify/Extra.java"
        f.write_text("package com.example.notify;\n\npublic class Extra {\n    void x() {\n    }\n}\n", encoding="utf-8")
        codemap.build(self.notify)
        self.ws.load()
        self.assertIn("notify-service:com.example.notify.Extra.x", self.ws.nodes)


ROUTES_REPO = {
    "src/main/resources/application.yml": (
        "api:\n  prefix: /v2\nspring:\n  datasource:\n    url: ${DB_URL:jdbc:postgresql://db:5432/queue_db?ssl=false}\n"),
    "src/main/java/com/example/queue/ApiPaths.java": '''package com.example.queue;

public final class ApiPaths {
    public static final String CLIENT = "/client";
    public static final String VERSION = "v1";
}
''',
    "src/main/java/com/example/queue/ClientController.java": '''package com.example.queue;

import static com.example.queue.ApiPaths.VERSION;

@RestController
@RequestMapping(ApiPaths.CLIENT)
public class ClientController {
    private static final String ONE = "/one";

    @GetMapping(ONE)
    public Object one() {
        return null;
    }

    @GetMapping("/api/" + VERSION + "/list")
    public Object list() {
        return null;
    }

    @PostMapping("${api.prefix}/save")
    public Object save() {
        return null;
    }

    @GetMapping(value = UNKNOWN_CONST + "/x")
    public Object unknown() {
        return null;
    }
}
''',
    "src/main/java/com/example/queue/ClientDao.java": '''package com.example.queue;

import org.jooq.*;
import com.example.queue.db.tables.*;

public class ClientDao {
    private final DSLContext dsl;
    private final Mapper mapper;

    public void save(DSLContext ctx, Client client) {
        mapper.update(dsl, client);
        dsl.update(client).set(client.NAME, "x").execute();
    }
}
''',
}


class JavaRoutesAndTablesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = Path(cls.tmp.name) / "queue-service"
        write_tree(cls.repo, ROUTES_REPO)
        codemap.build(cls.repo)
        cls.m = codemap.CodeMap(cls.repo)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_routes_from_constants_concatenation_and_placeholders(self) -> None:
        routes = sorted(r["route"] for r in self.m.routes()["shown"])
        self.assertEqual(routes, ["GET /client/api/v1/list", "GET /client/one", "GET /client/{}/x", "POST /client/v2/save"])

    def test_tables_carry_the_database_and_skip_jooq_api_types(self) -> None:
        self.assertEqual(self.m.symbol("ClientDao.save")["writes_tables"], ["table:queue_db.client"])
        self.assertFalse([n for n in self.m.nodes if n.startswith("table:") and "dsl" in n])


class PropertiesTests(unittest.TestCase):
    def test_yaml_nesting_and_placeholders(self) -> None:
        props = codemap.parse_yaml("a:\n  b:\n    c: ${X:one}  # note\n  d: 'two'\nlist:\n  - x\n")
        self.assertEqual(props, {"a.b.c": "${X:one}", "a.d": "two"})
        self.assertEqual(codemap.expand("${a.b.c}", props), "one")
        self.assertEqual(codemap.expand("${missing}", props), "${missing}")

    def test_sql_noise_does_not_hide_java_strings(self) -> None:
        clean = codemap.strip_java('String s = "a { b"; char c = \'{\'; String t = """\n  x }\n""";')
        self.assertNotIn("{", clean)
        self.assertNotIn("}", clean)


if __name__ == "__main__":
    unittest.main()
