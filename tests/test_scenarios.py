from demo.scenarios import execute_scenarios


def test_intermittent_and_masked_regressions(root, store):
    reports = execute_scenarios(root, store)
    intermittent = reports["intermittent"]
    case = next(c for c in intermittent["cases"] if c["id"] == "shared-outage")
    assert case["passed"] == 2 and case["total"] == 3
    assert [s["checks"][0]["status"] for s in case["samples"]] == ["pass", "pass", "fail"]
    assert intermittent["verdict"] == "fail"
    assert intermittent["aggregate_delta"] > -5
    masked = reports["masked_critical"]
    assert masked["aggregate_delta"] > 0
    assert masked["verdict"] == "fail"
    assert masked["reason"] == "Critical sample failed"
    assert store.latest("ticket-classifier")["id"] == reports["reference"]["id"]
    assert len(store.alerts()) == 2
