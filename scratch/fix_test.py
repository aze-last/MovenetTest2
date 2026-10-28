with open('tests/test_live_incident_pipeline.py', 'r', encoding='utf-8') as f:
    text = f.read()

target = """def test_main_app_nav_badge_on_incident_start():"""
replacement = """def test_main_app_nav_badge_on_incident_start(monkeypatch):"""
text = text.replace(target, replacement, 1)

target2 = """    # Switching to Incidents clears the alert badge
    CellWatchApp.switch_screen(mock_app, "Incidents")
    assert mock_app.nav_buttons["Incidents"].text == "Incidents\""""

replacement2 = """    # Mock IncidentsScreen creation so Tk doesn't require display
    monkeypatch.setattr("monitor_app.incidents.IncidentsScreen", lambda *a, **kw: None)
    # Switching to Incidents clears the alert badge
    CellWatchApp.switch_screen(mock_app, "Incidents")
    assert mock_app.nav_buttons["Incidents"].text == "Incidents\""""

text = text.replace(target2, replacement2, 1)

with open('tests/test_live_incident_pipeline.py', 'w', encoding='utf-8') as f:
    f.write(text)
print("Updated test_main_app_nav_badge_on_incident_start")

