#!/usr/bin/env python3
"""Offline tests for the trading calendar, schedule windows, and HTML patcher."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import market_update as mu
import nyse_calendar as cal
import status_text as st

ROOT = Path(__file__).resolve().parents[1]
NY = cal.NY


def ny(year, month, day, hour, minute):
    return datetime(year, month, day, hour, minute, tzinfo=NY)


def load_pages():
    return {
        "zh": (ROOT / "zh.html").read_text(encoding="utf-8"),
        "en": (ROOT / "en.html").read_text(encoding="utf-8"),
    }


class CalendarTests(unittest.TestCase):
    def test_weekends_and_2026_holidays(self):
        self.assertFalse(cal.is_trading_day(cal.date(2026, 11, 28)))
        self.assertFalse(cal.is_trading_day(cal.date(2026, 11, 29)))
        self.assertFalse(cal.is_trading_day(cal.date(2026, 11, 26)))
        self.assertEqual(cal.holiday_name(cal.date(2026, 11, 26)), "Thanksgiving Day")
        self.assertFalse(cal.is_trading_day(cal.date(2026, 7, 3)))
        self.assertFalse(cal.is_trading_day(cal.date(2026, 12, 25)))
        self.assertTrue(cal.is_trading_day(cal.date(2026, 11, 27)))
        self.assertTrue(cal.is_early_close(cal.date(2026, 11, 27)))
        self.assertEqual(cal.close_hhmm(cal.date(2026, 11, 27)), "13:00")
        self.assertTrue(cal.is_early_close(cal.date(2026, 12, 24)))
        self.assertEqual(cal.close_hhmm(cal.date(2026, 11, 30)), "16:00")

    def test_2027_and_july_3_when_applicable(self):
        self.assertFalse(cal.is_trading_day(cal.date(2027, 7, 5)))
        self.assertFalse(cal.is_early_close(cal.date(2027, 7, 2)))
        self.assertFalse(cal.is_trading_day(cal.date(2027, 12, 24)))
        self.assertFalse(cal.is_early_close(cal.date(2027, 12, 24)))
        self.assertTrue(cal.is_early_close(cal.date(2027, 11, 26)))
        self.assertTrue(cal.is_early_close(cal.date(2028, 7, 3)))
        self.assertEqual(cal.close_hhmm(cal.date(2028, 7, 3)), "13:00")
        self.assertTrue(cal.is_trading_day(cal.date(2028, 7, 3)))

    def test_previous_trading_day_skips_thanksgiving(self):
        self.assertEqual(cal.previous_trading_day(cal.date(2026, 11, 27)), cal.date(2026, 11, 25))


class WindowTests(unittest.TestCase):
    def test_dst_offsets(self):
        edt = ny(2026, 7, 15, 16, 15)
        est = ny(2026, 12, 15, 16, 15)
        self.assertEqual(edt.utcoffset().total_seconds(), -4 * 3600)
        self.assertEqual(est.utcoffset().total_seconds(), -5 * 3600)
        self.assertTrue(cal.in_post_close_window(edt))
        self.assertTrue(cal.in_post_close_window(est))
        self.assertFalse(cal.in_post_close_window(ny(2026, 7, 15, 17, 15)))
        self.assertFalse(cal.in_post_close_window(ny(2026, 12, 15, 15, 15)))
        self.assertTrue(cal.in_morning_window(ny(2026, 7, 15, 8, 0)))
        self.assertTrue(cal.in_morning_window(ny(2026, 12, 15, 8, 0)))
        self.assertFalse(cal.in_morning_window(ny(2026, 7, 15, 9, 0)))
        self.assertFalse(cal.in_morning_window(ny(2026, 12, 15, 7, 0)))

    def test_auto_job_selection(self):
        post = mu.decide(ny(2026, 11, 30, 16, 15), "auto", False)
        morning = mu.decide(ny(2026, 11, 30, 8, 0), "auto", False)
        late = mu.decide(ny(2026, 11, 30, 17, 15), "auto", False)
        holiday = mu.decide(ny(2026, 11, 26, 16, 15), "auto", False)
        weekend = mu.decide(ny(2026, 11, 28, 16, 15), "auto", False)
        early = mu.decide(ny(2026, 11, 27, 16, 15), "post-close", False)
        still_open = mu.decide(ny(2026, 11, 30, 10, 0), "post-close", False)
        self.assertEqual(post["action"], "post-close")
        self.assertEqual(morning["action"], "morning")
        self.assertEqual(late["action"], "noop")
        self.assertEqual(holiday["action"], "noop")
        self.assertEqual(weekend["action"], "noop")
        self.assertEqual(early["action"], "post-close")
        self.assertEqual(early["close_et"], "13:00")
        self.assertTrue(early["early"])
        self.assertEqual(still_open["action"], "noop")


def quote_for(last, prev, session, status="POST_MKT", settle=None, settle_date=None):
    return {
        "last": Decimal(str(last)),
        "prev": Decimal(str(prev)) if prev is not None else None,
        "change": Decimal(str(last)) - Decimal(str(prev)) if prev is not None else None,
        "status": status,
        "session_date": session,
        "clock": None,
        "settle": Decimal(str(settle)) if settle is not None else None,
        "settle_date": settle_date,
    }


def bumped_quotes(snapshot, session, factor="1.01"):
    factor = Decimal(factor)
    cnbc = {}
    yahoo = {}
    for key, inst in snapshot["instruments"].items():
        last = (Decimal(inst["close"]) * factor).quantize(Decimal("0.0001"))
        prior = Decimal(inst["close"])
        cnbc[inst["cnbc"]] = quote_for(last, prior, session)
        yahoo[inst["yahoo"]] = {"bars": [(session, session, last)], "last": last}
    for key, item in snapshot["crossAsset"].items():
        base = Decimal(item["value"])
        last = (base * factor).quantize(Decimal("0.0001"))
        cnbc[item["cnbc"]] = quote_for(last + Decimal("1"), base, session, settle=last, settle_date=session)
        yahoo[item["yahoo"]] = {"bars": [(session, session, last)], "last": last}
    cnbc["US10Y"] = quote_for("4.950", "4.900", session, status="REG_MKT")
    return {"cnbc": cnbc, "yahoo": yahoo}


class QuoteTests(unittest.TestCase):
    def setUp(self):
        self.snap = mu.load_snapshot(ROOT / "data" / "official-snapshot.json")
        self.session = cal.date(2026, 11, 30)
        self.decision = mu.decide(ny(2026, 11, 30, 16, 20), "post-close", False)

    def test_post_close_rotates_previous_and_appends_vix_without_holiday(self):
        updated, _notes = mu.apply_quotes(self.snap, self.decision, bumped_quotes(self.snap, self.session))
        self.assertEqual(updated["equitySession"]["date"], "2026-11-30")
        self.assertEqual(updated["equitySession"]["closeEt"], "16:00")
        self.assertFalse(updated["equitySession"]["earlyClose"])
        self.assertEqual(updated["instruments"]["spx"]["prevClose"], "7297.49")
        self.assertNotEqual(updated["instruments"]["spx"]["close"], "7297.49")
        self.assertEqual(len(updated["vixPath"]), 14)
        self.assertEqual(updated["vixPath"][-1]["date"], "2026-11-30")
        self.assertNotIn("2026-11-26", [item["date"] for item in updated["vixPath"]])
        self.assertEqual(updated["vixPath"][0]["date"], "2026-11-10")

    def test_rerun_does_not_rotate_twice(self):
        quotes = bumped_quotes(self.snap, self.session)
        once, _notes = mu.apply_quotes(self.snap, self.decision, quotes)
        twice, _notes = mu.apply_quotes(once, self.decision, quotes)
        self.assertEqual(twice["instruments"]["spx"]["prevClose"], once["instruments"]["spx"]["prevClose"])
        self.assertEqual(twice["instruments"]["spx"]["close"], once["instruments"]["spx"]["close"])

    def test_source_disagreement_blocks_official_close(self):
        quotes = bumped_quotes(self.snap, self.session)
        quotes["yahoo"]["^GSPC"]["bars"] = [(self.session, self.session, Decimal("8000"))]
        with self.assertRaises(mu.UpdateError) as caught:
            mu.apply_quotes(self.snap, self.decision, quotes)
        self.assertIn("disagree", str(caught.exception))

    def test_vix_ignores_holiday_previous_print(self):
        quotes = bumped_quotes(self.snap, self.session)
        # CNBC's previous field is a holiday print; the change does not tie to it.
        quotes["cnbc"][".VIX"]["prev"] = Decimal("26.80")
        quotes["cnbc"][".VIX"]["change"] = quotes["cnbc"][".VIX"]["last"] - Decimal("26.80")
        updated, _notes = mu.apply_quotes(self.snap, self.decision, quotes)
        expected_prev = self.snap["instruments"]["vix"]["close"]
        self.assertEqual(updated["instruments"]["vix"]["prevClose"], expected_prev)

    def test_brent_uses_settlement_not_the_live_last(self):
        quotes = bumped_quotes(self.snap, self.session)
        quotes["cnbc"]["@LCO.1"]["last"] = Decimal("99.99")
        quotes["cnbc"]["@LCO.1"]["settle"] = Decimal("95.10")
        quotes["cnbc"]["@LCO.1"]["settle_date"] = self.session
        updated, _notes = mu.apply_quotes(self.snap, self.decision, quotes)
        self.assertEqual(updated["crossAsset"]["brent"]["value"], "95.10")
        self.assertEqual(updated["crossAsset"]["brent"]["displayKind"], "settle")

    def test_morning_does_not_replace_equity_closes(self):
        morning = mu.decide(ny(2026, 11, 30, 8, 0), "morning", False)
        quotes = bumped_quotes(self.snap, self.session, factor="1.05")
        updated, _notes = mu.apply_quotes(self.snap, morning, quotes)
        self.assertEqual(updated["instruments"]["spx"]["close"], self.snap["instruments"]["spx"]["close"])
        self.assertEqual(updated["instruments"]["xlk"]["close"], self.snap["instruments"]["xlk"]["close"])
        self.assertEqual(updated["vixPath"], self.snap["vixPath"])
        self.assertEqual(updated["equitySession"], self.snap["equitySession"])
        self.assertEqual(updated["crossAsset"]["dxy"]["displayKind"], "intraday")
        self.assertNotEqual(updated["crossAsset"]["dxy"]["display"], updated["crossAsset"]["dxy"]["value"])

    def test_early_close_label(self):
        early = mu.decide(ny(2026, 12, 24, 16, 15), "post-close", False)
        self.assertEqual(early["close_et"], "13:00")
        session = {"date": "2026-12-24", "closeEt": "13:00", "earlyClose": True}
        self.assertIn("13:00", mu.phrase(session, "zh"))
        self.assertIn("提早收市", mu.phrase(session, "zh"))
        self.assertNotIn("16:00", mu.phrase(session, "en"))
        self.assertIn("early close", mu.phrase(session, "en"))


class PatchTests(unittest.TestCase):
    def setUp(self):
        self.snap = mu.load_snapshot(ROOT / "data" / "official-snapshot.json")
        self.pages = load_pages()

    def test_render_keeps_protected_content_and_repairs_tiles(self):
        for lang, html in self.pages.items():
            patched = mu.patch_html(html, lang, self.snap, "post-close")
            self.assertEqual(mu.patch_html(patched, lang, self.snap, "post-close"), patched)
            self.assertIn("renderHoldings", patched)
            self.assertIn('id="hold-select"', patched)
            self.assertIn('id="hold-body"', patched)
            self.assertIn('window.MARKET_REFRESH_PROXY = window.MARKET_REFRESH_PROXY || ""', patched)
            self.assertIn('class=\\"num', patched)
            self.assertEqual(patched.count("data:image/png"), 11)
            self.assertIn("+4.3%", patched)
            self.assertIn("20.014808", patched)
            self.check_scripts(patched, lang)
        zh = mu.patch_html(self.pages["zh"], "zh", self.snap, "post-close")
        en = mu.patch_html(self.pages["en"], "en", self.snap, "post-close")
        self.assertIn("11 月 27 日提早收市 160.15", zh)
        self.assertIn("＋2.80%", zh)
        self.assertIn("377 bps", zh)
        self.assertIn("27 November early close 160.15", en)
        self.assertIn(">7,297.49<", en)
        self.assertIn("372 bps", en)
        self.assertIn("4.94%", en)
        self.assertNotIn("official Wednesday 25 November", zh)
        self.assertNotIn("周三 11 月 25 日官方收市", en)

    def test_morning_patch_does_not_change_equity_tile(self):
        base = mu.patch_html(self.pages["zh"], "zh", self.snap, "post-close")
        morning_snap = deepcopy(self.snap)
        morning_snap["crossAsset"]["dxy"]["display"] = "105.50"
        morning_snap["crossAsset"]["dxy"]["displayKind"] = "intraday"
        morning_snap["crossAsset"]["gold"]["display"] = "3700.00"
        morning_snap["crossAsset"]["gold"]["displayKind"] = "intraday"
        patched = mu.patch_html(base, "zh", morning_snap, "morning")
        self.assertIn(">7,297.49<", patched)
        self.assertIn("11 月 27 日提早收市 160.15", patched)
        self.assertIn(">105.50<", patched)
        self.assertIn("非官方結算", patched)
        self.assertIn("3,700.00", patched)
        self.assertIn('data-snapshot-job="morning"', patched)
        official = re.search(r'spx:\s*\{[^}]*official:\s*([0-9.]+)', patched)
        self.assertEqual(official.group(1), "7297.49")
        self.check_scripts(patched, "zh-morning")

    def check_scripts(self, html, label):
        parts = html.split("<script>")[1:]
        for index, part in enumerate(parts, start=1):
            script = part.split("</script>", 1)[0]
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
                handle.write(script)
                path = handle.name
            result = subprocess.run(["node", "--check", path], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, f"{label} script {index}: {result.stderr}")


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.snap = mu.load_snapshot(ROOT / "data" / "official-snapshot.json")
        self.pages = load_pages()

    def test_vix_bands_and_recapture_and_new_high(self):
        self.assertEqual(st.vix_band("18"), "below20")
        self.assertEqual(st.vix_band("23.81"), "below_mid")
        self.assertEqual(st.vix_band("30"), "mid")
        self.assertEqual(st.vix_band("36"), "above_mid")
        self.assertEqual(st.vix_band("41"), "panic")
        below, _css = st.index_status("spx", self.snap, "en")
        self.assertIn("still below the 5 Nov 2026 close", below)
        self.assertIn("Outside a correction", below)
        recaptured = deepcopy(self.snap)
        recaptured["instruments"]["spx"]["close"] = "7400.00"
        text, _css = st.index_status("spx", recaptured, "zh")
        self.assertIn("已收復 11 月 5 日收市", text)
        high = deepcopy(self.snap)
        high["instruments"]["spx"]["close"] = "7900.00"
        high["instruments"]["spx"]["ath"] = "7900.00"
        text, _css = st.index_status("spx", high, "en")
        self.assertIn("New closing high", text)
        self.assertEqual(st.next_streak(4, Decimal("1")), 5)
        self.assertEqual(st.next_streak(4, Decimal("-1")), -1)
        self.assertIn("XLK", st.sector_rank_text(self.snap, "zh"))
        self.assert_qqq_parenthesis_is_the_day_change()
        self.assertIn("XLV", st.sector_rank_text(self.snap, "en"))
        self.assertIn("XLU", st.sector_rank_text(self.snap, "en"))

    def assert_qqq_parenthesis_is_the_day_change(self):
        qqq = self.snap["instruments"]["qqq"]
        day = st.fmt_pct(st.day_pct(qqq["close"], qqq["prevClose"]))
        ath = st.fmt_pct(st.vs_ath(qqq["close"], qqq["ath"]))
        self.assertNotEqual(day, ath)
        for lang, opener, closer in (("zh", "（", "）"), ("en", "(", ")")):
            caption = st.equity_caption("ndx", self.snap, lang)
            match = re.search(
                r"QQQ [\d,]+(?:\.\d+)?\s*" + re.escape(opener) + r"([^" + re.escape(closer) + r"]+)" + re.escape(closer),
                caption,
            )
            self.assertIsNotNone(match, caption)
            self.assertEqual(match.group(1), day)
            self.assertNotEqual(match.group(1), ath)
            self.assertNotIn(opener + ath + closer, caption)
            if ath in caption:
                self.assertIn("ATH", caption)

    def test_pages_get_factual_pills_and_leave_the_call_alone(self):
        patched = {}
        for lang, html in self.pages.items():
            patched[lang] = mu.patch_html(html, lang, self.snap, "post-close")
            self.assertEqual(mu.patch_html(patched[lang], lang, self.snap, "post-close"), patched[lang])
            self.check_scripts(patched[lang], lang)
        self.assertIn("尚未見底", patched["zh"])
        self.assertIn("Not yet a confirmed bottom", patched["en"])
        self.assertIn("12–18%", patched["zh"])
        self.assertIn("32–38%", patched["zh"])
        self.assertIn("12–18%", patched["en"])
        self.assertIn("偏高但非危機", patched["zh"])
        self.assertIn("Elevated but not crisis-level", patched["en"])
        self.assertIn("Out of the 25–35 mid-band, not yet below 20", patched["en"])
        self.assertNotIn("Still in the 25–35 mid-range", re.search(r'data-status="overview-vix">(.*?)</span>', patched["en"]).group(1))
        self.assertIn("up 4 days", patched["en"])
        self.assertNotIn("up three days", patched["en"])
        self.assertIn("still below the 5 Nov 2026 close", patched["en"])
        self.assertIn("仍低於 11 月 5 日收市", patched["zh"])
        self.assertIn("領漲 XLK", patched["zh"])
        self.assertIn("Leader XLK", patched["en"])
        self.assertIn('data-status="overview-spx"', patched["zh"])
        self.assertIn('data-status="overview-spx"', patched["en"])
        self.assertIn('id="sec-rank"', patched["zh"])
        self.assertIn('id="sec-rank"', patched["en"])

    def test_morning_does_not_rewrite_equity_status(self):
        base = mu.patch_html(self.pages["en"], "en", self.snap, "post-close")
        tampered = deepcopy(self.snap)
        tampered["instruments"]["spx"]["close"] = "8000.00"
        tampered["instruments"]["vix"]["close"] = "41"
        tampered["streaks"]["dji"] = 9
        morning = mu.patch_html(base, "en", tampered, "morning")
        for slot in ("overview-spx", "overview-vix", "overview-dji", "sec-rank"):
            self.assertEqual(self.slot(base, slot), self.slot(morning, slot))
        self.assertIn("Not yet a confirmed bottom", morning)

    def test_new_session_rolls_a_stored_streak_once(self):
        session = cal.date(2026, 11, 30)
        decision = mu.decide(ny(2026, 11, 30, 16, 20), "post-close", False)
        updated, _notes = mu.apply_quotes(self.snap, decision, bumped_quotes(self.snap, session))
        self.assertEqual(updated["streaks"]["dji"], 5)
        self.assertEqual(updated["streaks"]["rut"], 5)
        again, _notes = mu.apply_quotes(updated, decision, bumped_quotes(self.snap, session))
        self.assertEqual(again["streaks"]["dji"], 5)

    def slot(self, html, slot):
        match = re.search(rf'data-status="{slot}"[^>]*>(.*?)</', html)
        self.assertIsNotNone(match, slot)
        return match.group(1)

    def check_scripts(self, html, label):
        parts = html.split("<script>")[1:]
        for index, part in enumerate(parts, start=1):
            script = part.split("</script>", 1)[0]
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
                handle.write(script)
                path = handle.name
            result = subprocess.run(["node", "--check", path], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, f"{label} script {index}: {result.stderr}")


class WorkflowTests(unittest.TestCase):
    def test_workflow_shape(self):
        text = (ROOT / ".github" / "workflows" / "update-market-snapshot.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch", text)
        self.assertIn("contents: write", text)
        self.assertIn("cancel-in-progress: false", text)
        self.assertIn("ubuntu-latest", text)
        self.assertIn("0 12 * * 1-5", text)
        self.assertIn("0 13 * * 1-5", text)
        self.assertIn("15 20 * * 1-5", text)
        self.assertIn("15 21 * * 1-5", text)
        self.assertNotIn("\n  push:", text)
        self.assertIn("post-close", text)
        self.assertIn("morning", text)


if __name__ == "__main__":
    unittest.main()
