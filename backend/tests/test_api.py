from fastapi.testclient import TestClient

from app.main import app


def test_full_dynamic_flow():
    with TestClient(app) as c:
        assert c.get("/api/health").json()["ready"]
        net = c.get("/api/network").json()
        assert net["nodes"] > 0 and net["roads"]
        page = c.get("/api/orders", params={"page_size": 10}).json()
        assert page["total"] == 30 and len(page["items"]) == 10 and page["pages"] == 3
        run = c.post("/api/optimization/run", json={"algorithm": "clarke_wright"}).json()
        assert run["metrics"]["unassigned"] == 0
        assert run["explanation"]["improvement_vs_baseline"]["objective"]["after"] <= \
            run["explanation"]["improvement_vs_baseline"]["objective"]["before"]
        c.post("/api/simulation/start")
        for _ in range(20):
            c.post("/api/simulation/step")
        ev = c.post("/api/simulation/events/new-order", json={"priority": "high"}).json()
        assert ev["order"]["code"] and ev["decisions"]
        assert c.post("/api/simulation/events/congestion", json={}).status_code == 200
        assert c.post("/api/simulation/events/closure", json={}).status_code == 200
        state = c.get("/api/simulation/state").json()
        assert state["dispatched"] and state["vehicles"]
        summary = c.get("/api/analytics/summary").json()
        assert summary["events"]
        path = c.post("/api/network/path", json={"source": 0, "target": net["nodes"] - 1}).json()
        costs = {r["cost"] for r in path["results"].values()}
        assert len(costs) == 1


def test_order_deletion_cancel_and_bulk():
    with TestClient(app) as c:
        c.post("/api/simulation/reset", json={})
        c.post("/api/orders/generate", json={"count": 5})
        total = c.get("/api/orders").json()["total"]
        first = c.get("/api/orders", params={"page_size": 1}).json()["items"][0]
        # cancel keeps the record
        assert c.post(f"/api/orders/{first['id']}/cancel").json()["status"] == "cancelled"
        assert c.get("/api/orders").json()["total"] == total
        # single delete removes it
        assert c.delete(f"/api/orders/{first['id']}").status_code == 200
        assert c.get("/api/orders").json()["total"] == total - 1
        # bulk preview + delete by filter
        prev = c.post("/api/orders/bulk-delete/preview", json={"filter": {"status": "pending"}}).json()
        assert prev["deletable"] == total - 1
        res = c.post("/api/orders/bulk-delete", json={"filter": {"status": "pending"}}).json()
        assert res["deleted"] == total - 1
        assert c.get("/api/orders").json()["total"] == 0
        # server-side search
        c.post("/api/orders", json={"customer_name": "Zyxw Unique Traders"})
        hit = c.get("/api/orders", params={"q": "zyxw"}).json()
        assert hit["total"] == 1 and hit["items"][0]["customer_name"] == "Zyxw Unique Traders"
        assert c.post("/api/orders/clear", json={}).json()["deleted"] == 1


def test_trace_endpoint_returns_exploration_order():
    with TestClient(app) as c:
        net = c.get("/api/network").json()
        tr = c.post("/api/network/path/trace", json={"source": 0, "target": net["nodes"] - 1}).json()
        res = tr["results"]
        assert len({round(r["cost"], 6) for r in res.values()}) == 1
        assert len(res["astar"]["expanded_nodes"]) == res["astar"]["expanded"]
        assert res["astar"]["expanded"] <= res["dijkstra"]["expanded"]
        assert any(p[2] == 1 for p in res["bidirectional_dijkstra"]["expanded_nodes"])
