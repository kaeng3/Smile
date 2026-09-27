from pathlib import Path
import unittest


HTML = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")


class NewScannerPageTests(unittest.TestCase):
    def test_lab2_is_replaced_without_changing_other_tabs(self):
        self.assertIn('id="nav-lab2">🔎 김일구 New스캐너</button>', HTML)
        self.assertIn('id="lab-content2"', HTML)
        self.assertIn("🧪 베타 실험실 1", HTML)
        self.assertIn("🧪 베타 실험실 3", HTML)

    def test_page_has_data_contract_and_required_containers(self):
        self.assertIn("new_scanner/results/history.json", HTML)
        self.assertIn('id="new-scanner-status"', HTML)
        self.assertIn('id="new-scanner-dates"', HTML)
        self.assertIn('id="new-scanner-cards"', HTML)
        self.assertIn("async function loadNewScannerData", HTML)
        self.assertIn("function renderNewScannerDates", HTML)
        self.assertIn("function renderNewScannerCards", HTML)

    def test_version_empty_and_error_states_are_explicit(self):
        self.assertIn("payload.version !== 1", HTML)
        self.assertIn("isValidNewScannerSession", HTML)
        self.assertIn("Number.isFinite", HTML)
        self.assertIn("오늘 신규 후보가 없습니다", HTML)
        self.assertIn("스캔 결과를 불러오지 못했습니다", HTML)
        self.assertIn("Array.isArray(payload.sessions)", HTML)

    def test_cards_render_chart_korean_state_and_truncated_numbers(self):
        self.assertIn("function renderNewScannerChart", HTML)
        self.assertIn('IGNITION: \'점화\'', HTML)
        self.assertIn('BREAKOUT: \'돌파\'', HTML)
        self.assertIn("Math.trunc", HTML)
        self.assertIn('class="new-scanner-chart"', HTML)

    def test_chart_renders_candles_moving_averages_axes_and_volume(self):
        self.assertIn('class="new-scanner-candle-body"', HTML)
        self.assertIn('class="new-scanner-candle-wick"', HTML)
        self.assertIn('20일선', HTML)
        self.assertIn('60일선', HTML)
        self.assertIn('120일선', HTML)
        self.assertIn('new-scanner-axis-label', HTML)
        self.assertIn('new-scanner-volume-bar', HTML)
        self.assertIn('grid-template-columns: repeat(2, minmax(0, 1fr))', HTML)


if __name__ == "__main__":
    unittest.main()
