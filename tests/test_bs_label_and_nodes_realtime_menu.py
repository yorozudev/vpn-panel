"""Регрессии подписи BS-периода и отдельного окна realtime-мониторинга."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "app/dashboard"


def test_bs_table_uses_selected_reset_strategy():
    source = (DASHBOARD / "src/components/UsersTable.tsx").read_text(encoding="utf-8")
    assert 'dataLimitResetStrategy: user.bs_reset_strategy ?? "month"' in source
    assert 'dataLimitResetStrategy: "month" as const' not in source


def test_nodes_realtime_is_opened_from_burger_menu_not_dashboard():
    dashboard = (DASHBOARD / "src/pages/Dashboard.tsx").read_text(encoding="utf-8")
    header = (DASHBOARD / "src/components/Header.tsx").read_text(encoding="utf-8")
    context = (DASHBOARD / "src/contexts/DashboardContext.tsx").read_text(encoding="utf-8")

    assert "<NodesRealtime />" not in dashboard
    assert "<NodesRealtimeModal />" in dashboard
    assert "onShowingNodesRealtime.bind(null, true)" in header
    assert 't("header.nodesRealtime")' in header
    assert "isShowingNodesRealtime: boolean" in context
    assert "onShowingNodesRealtime: (isShowingNodesRealtime: boolean) => void" in context


def test_nodes_realtime_modal_preserves_live_cards_only_while_open():
    source = (DASHBOARD / "src/components/NodesRealtimeModal.tsx").read_text(encoding="utf-8")
    assert 'size="6xl"' in source
    assert 'scrollBehavior="inside"' in source
    assert "isShowingNodesRealtime && <NodesRealtime showHeader={false} />" in source
    assert "onShowingNodesRealtime(false)" in source


def test_nodes_realtime_menu_is_localized():
    for language in ("ru", "en"):
        path = DASHBOARD / f"public/statics/locales/{language}.json"
        translations = json.loads(path.read_text(encoding="utf-8"))
        assert translations["header.nodesRealtime"]
        assert translations["nodesRealtime.title"]
        assert translations["nodesRealtime.interval"]
