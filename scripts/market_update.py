#!/usr/bin/env python3
"""Update the official snapshot in zh.html and en.html.

Post-close (16:15 America/New_York) writes cash closes for indices, VIX,
the 11 Select Sector SPDRs, and SPY, QQQ, RSP, QQEW, SPYM. It also refreshes
Brent, WTI, gold, silver, DXY, USD/JPY, and offshore USD/CNH.

Morning (08:00 America/New_York) may refresh those cross-assets only. It does
not replace official equity, VIX, sector, or ETF cash closes with pre-market
or overnight prints.

Figures come from the public CNBC quote service already used by the pages,
with Yahoo Finance daily bars as a free check. No API key is required.

The script does not invent GDP, PCE, CPI, PPI, NFP, official HY OAS, ChartRow
breadth, SSGA holding weights, Treasury cash yields, or a new market call.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nyse_calendar import (
    NY,
    as_ny,
    close_hhmm,
    close_time,
    in_morning_window,
    in_post_close_window,
    is_early_close,
    is_trading_day,
    previous_trading_day,
)

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = ROOT / "data" / "official-snapshot.json"
CNBC_URL = (
    "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"
    "?symbols={symbols}&requestMethod=itv&noform=1&partnerId=2&output=json"
)
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=10d"
USER_AGENT = "us-market-dashboard/1.0 (public GitHub Pages snapshot; no API key)"

INDEX_IDS = ["sox", "ndx", "ixic", "rut", "spx", "dji"]
SECTOR_IDS = ["xlk", "xly", "xlc", "xlb", "xli", "xle", "xlf", "xlre", "xlp", "xlv", "xlu"]
ETF_IDS = ["spy", "qqq", "rsp", "qqew", "spym"]
EQUITY_IDS = INDEX_IDS + ["vix"] + SECTOR_IDS + ETF_IDS
CORE_IDS = ["spx", "dji", "ixic", "vix"]
CROSS_IDS = ["brent", "wti", "gold", "silver", "dxy", "jpy", "cnh"]
# Brent's Yahoo continuous contract is not the ICE official settle.
YAHOO_CHECK_ONLY = {"brent"}
BLOCK_DIFF = Decimal("0.005")
NOTE_DIFF = Decimal("0.0008")

ZH_WD = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
EN_WD = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
EN_MON = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
EN_MON_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

INDEX_LABELS = {
    "zh": {
        "sox": "費城半導體（SOX）",
        "ndx": "納指 100（NDX）",
        "ixic": "納指綜合",
        "rut": "羅素 2000",
        "spx": "S&amp;P 500",
        "dji": "道指",
        "vix": "VIX（波動指數）",
    },
    "en": {
        "sox": "PHLX Semiconductor (SOX)",
        "ndx": "Nasdaq-100 (NDX)",
        "ixic": "Nasdaq Composite",
        "rut": "Russell 2000",
        "spx": "S&amp;P 500",
        "dji": "Dow",
        "vix": "VIX (volatility index)",
    },
}
VIX_NA = {"zh": "不適用（波動指數）", "en": "n/a (volatility index)"}
SECTOR_NAMES = {
    "zh": {
        "XLB": "原材料", "XLRE": "房地產", "XLC": "通訊服務", "XLI": "工業",
        "XLE": "能源", "XLF": "金融", "XLU": "公用事業", "XLP": "必需消費",
        "XLY": "非必需消費", "XLV": "醫療保健", "XLK": "資訊科技",
    },
    "en": {
        "XLB": "Materials", "XLRE": "Real Estate", "XLC": "Communication Services",
        "XLI": "Industrials", "XLE": "Energy", "XLF": "Financials", "XLU": "Utilities",
        "XLP": "Consumer Staples", "XLY": "Consumer Discretionary", "XLV": "Health Care",
        "XLK": "Technology",
    },
}
SPYM_NAME = {
    "zh": "標普 500 基準（SPDR Portfolio）",
    "en": "S&amp;P 500 benchmark (SPDR Portfolio)",
}
SPYM_RANK = {"zh": "基準", "en": "Bench"}
OVERVIEW_LABELS = {
    "zh": {
        "spx": "S&amp;P 500", "dji": "道指", "ixic": "納指", "sox": "SOX",
        "rsp": "RSP 等權", "vix": "VIX", "ndxqqq": "NDX／QQQ",
    },
    "en": {
        "spx": "S&amp;P 500", "dji": "Dow", "ixic": "Nasdaq", "sox": "SOX",
        "rsp": "RSP equal-weight", "vix": "VIX", "ndxqqq": "NDX／QQQ",
    },
}
EQUITY_K = {
    "zh": {
        "spx": "S&amp;P 500", "dji": "道指", "ixic": "納指綜合",
        "ndx": "NDX／QQQ", "sox": "SOX 半導體", "vix": "VIX",
    },
    "en": {
        "spx": "S&amp;P 500", "dji": "Dow", "ixic": "Nasdaq Composite",
        "ndx": "NDX／QQQ", "sox": "SOX semiconductors", "vix": "VIX",
    },
}
DRAW_LABELS = {
    "zh": {
        "rsp": "RSP 等權", "spx": "S&amp;P 500", "dji": "道指", "rut": "羅素 2000",
        "ixic": "納指", "ndx": "納指 100", "sox": "費城半導體 SOX",
    },
    "en": {
        "rsp": "RSP Equal-Weight", "spx": "S&amp;P 500", "dji": "Dow",
        "rut": "Russell 2000", "ixic": "Nasdaq Comp", "ndx": "Nasdaq-100",
        "sox": "PHLX Semi SOX",
    },
}
PRINT_LABELS = {
    "zh": [
        ("費城半導體", "sox"), ("納指 100", "ndx"), ("納指綜合", "ixic"),
        ("羅素 2000", "rut"), ("S&amp;P 500", "spx"), ("道指", "dji"),
        ("VIX", "vix"), ("SPYM", "spym"), ("QQEW", "qqew"), ("QQQ", "qqq"),
        ("RSP", "rsp"), ("SPY", "spy"),
        ("XLK", "xlk"), ("XLY", "xly"), ("XLC", "xlc"), ("XLB", "xlb"),
        ("XLI", "xli"), ("XLE", "xle"), ("XLF", "xlf"), ("XLRE", "xlre"),
        ("XLP", "xlp"), ("XLV", "xlv"), ("XLU", "xlu"),
    ],
    "en": [
        ("PHLX Semiconductor", "sox"), ("Nasdaq-100", "ndx"), ("Nasdaq Composite", "ixic"),
        ("Russell 2000", "rut"), ("S&amp;P 500", "spx"), ("Dow", "dji"),
        ("VIX", "vix"), ("SPYM", "spym"), ("QQEW", "qqew"), ("QQQ", "qqq"),
        ("RSP", "rsp"), ("SPY", "spy"),
        ("XLK", "xlk"), ("XLY", "xly"), ("XLC", "xlc"), ("XLB", "xlb"),
        ("XLI", "xli"), ("XLE", "xle"), ("XLF", "xlf"), ("XLRE", "xlre"),
        ("XLP", "xlp"), ("XLV", "xlv"), ("XLU", "xlu"),
    ],
}
ASOF_EQUITY = {"zh": "股指／VIX／廣度", "en": "Equities / VIX / breadth"}
ASOF_CROSS = {"zh": "跨資產", "en": "Cross-asset"}
INST_KEYS = {
    "spx", "dji", "ixic", "ndx", "sox", "rut", "vix", "dxy", "jpy", "cnh",
    "brent", "wti", "gold", "silver", "xlb", "xlre", "xlc", "xli", "xle",
    "xlf", "xlu", "xlp", "xly", "xlv", "xlk", "spym",
}


class UpdateError(Exception):
    pass


def D(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def q(value, dec: int) -> Decimal:
    return D(value).quantize(Decimal(1).scaleb(-dec), rounding=ROUND_HALF_UP)


def fmt_num(value, dec: int) -> str:
    number = q(value, dec)
    body = f"{abs(number):,.{dec}f}"
    return ("−" if number < 0 else "") + body


def fmt_signed(value, dec: int, suffix: str = "") -> str:
    number = q(value, dec)
    body = f"{abs(number):,.{dec}f}"
    if number > 0:
        return "＋" + body + suffix
    if number < 0:
        return "−" + body + suffix
    return body + suffix


def fmt_pct(value) -> str:
    return fmt_signed(value, 2, "%")


def js_num(value, dec: int) -> str:
    return f"{q(value, dec):.{dec}f}"


def day_pct(close, prev) -> Decimal:
    return (D(close) - D(prev)) / D(prev) * Decimal(100)


def vs_ath(close, ath) -> Decimal:
    return (D(close) / D(ath) - 1) * Decimal(100)


def rel_diff(left, right) -> Decimal:
    return abs(D(left) - D(right)) / max(abs(D(right)), Decimal("0.0000001"))


def parse_when(text: str) -> tuple[date | None, time | None]:
    if not text:
        return None, None
    raw = text.strip()
    if "T" not in raw:
        try:
            return date.fromisoformat(raw[:10]), None
        except ValueError:
            return None, None
    iso = raw
    if re.search(r"[+-]\d{4}$", iso):
        iso = iso[:-5] + iso[-5:-2] + ":" + iso[-2:]
    try:
        moment = datetime.fromisoformat(iso)
    except ValueError:
        return None, None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=NY)
    local = moment.astimezone(NY)
    return local.date(), local.timetz().replace(tzinfo=None, microsecond=0)


def session_date(session: dict) -> date:
    return date.fromisoformat(session["date"])


def weekday_zh(day: date) -> str:
    return ZH_WD[day.weekday()]


def weekday_en(day: date) -> str:
    return EN_WD[day.weekday()]


def phrase(session: dict, lang: str) -> str:
    day = session_date(session)
    early = bool(session.get("earlyClose"))
    clock = session["closeEt"]
    if lang == "zh":
        base = f"{weekday_zh(day)} {day.month} 月 {day.day} 日"
        kind = "官方提早收市" if early else "官方收市"
        return f"{base}{kind}（{clock} ET）"
    kind = "early close" if early else "close"
    return f"official {weekday_en(day)} {day.day} {EN_MON[day.month - 1]} {kind}, {clock} ET"


def short_phrase(session: dict, lang: str) -> str:
    day = session_date(session)
    early = bool(session.get("earlyClose"))
    if lang == "zh":
        base = f"{weekday_zh(day)} {day.month} 月 {day.day} 日"
        return base + ("提早收市" if early else "")
    kind = " early close" if early else ""
    return f"{weekday_en(day)} {day.day} {EN_MON[day.month - 1]}{kind}"


def date_mentioned(text: str, day: date, lang: str) -> bool:
    if lang == "zh":
        return f"{day.month} 月 {day.day} 日" in text or day.isoformat() in text
    month = EN_MON[day.month - 1]
    abbr = EN_MON_ABBR[day.month - 1]
    return (
        f"{day.day} {month}" in text
        or f"{day.day} {abbr}" in text
        or f"{month} {day.day}" in text
        or f"{abbr} {day.day}" in text
    )


def load_snapshot(path: Path = SNAPSHOT_PATH) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    for item in EQUITY_IDS:
        if item not in data["instruments"]:
            raise UpdateError(f"snapshot missing instrument {item}")
    for item in CROSS_IDS:
        if item not in data["crossAsset"]:
            raise UpdateError(f"snapshot missing cross-asset {item}")
    return data


def save_snapshot(snapshot: dict, path: Path = SNAPSHOT_PATH) -> None:
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def decide(now: datetime, job: str, ignore_calendar: bool) -> dict:
    local = as_ny(now)
    day = local.date()
    resolved = job
    if job == "auto":
        if in_post_close_window(local):
            resolved = "post-close"
        elif in_morning_window(local):
            resolved = "morning"
        else:
            return {"action": "noop", "reason": f"outside the 16:15 and 08:00 ET windows ({local.strftime('%Y-%m-%d %H:%M %Z')})"}
    if not ignore_calendar and not is_trading_day(day):
        why = "weekend" if day.weekday() >= 5 else "NYSE holiday"
        return {"action": "noop", "reason": f"{day.isoformat()} is not a cash trading day ({why})"}
    if resolved == "post-close" and is_trading_day(day) and local.time() < close_time(day):
        return {
            "action": "noop",
            "reason": f"cash session is still open (closes {close_hhmm(day)} ET); not writing official closes",
        }
    early = is_early_close(day) if is_trading_day(day) else False
    return {
        "action": resolved,
        "reason": resolved,
        "session_date": day,
        "close_et": close_hhmm(day) if is_trading_day(day) or ignore_calendar else REGULAR_CLOSE_SAFE(day),
        "early": early,
        "now": local,
    }


def REGULAR_CLOSE_SAFE(day: date) -> str:
    return close_hhmm(day) if is_trading_day(day) or is_early_close(day) else "16:00"


def http_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_number(value) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return D(value)
    text = str(value).strip().replace(",", "").replace("%", "").replace("+", "")
    if not text or text.upper() == "UNCH" or text in {"--", "N/A", "null"}:
        return None
    text = text.replace("−", "-")
    try:
        return Decimal(text)
    except Exception:
        return None


def fetch_cnbc(symbols: list[str]) -> dict[str, dict]:
    url = CNBC_URL.format(symbols=urllib.parse.quote("|".join(symbols)))
    payload = http_json(url)
    quotes = payload.get("FormattedQuoteResult", {}).get("FormattedQuote") or []
    if isinstance(quotes, dict):
        quotes = [quotes]
    found = {}
    for quote in quotes:
        symbol = quote.get("symbol")
        last = parse_number(quote.get("last"))
        if not symbol or last is None:
            continue
        session_day, clock = parse_when(str(quote.get("last_time") or ""))
        settle_day, _clock = parse_when(str(quote.get("settleDate") or ""))
        found[symbol] = {
            "last": last,
            "prev": parse_number(quote.get("previous_day_closing")),
            "change": parse_number(quote.get("change")),
            "status": quote.get("curmktstatus") or "",
            "session_date": session_day,
            "clock": clock,
            "settle": parse_number(quote.get("settlePrice")),
            "settle_date": settle_day,
        }
    return found


def fetch_yahoo(symbol: str) -> dict:
    url = YAHOO_URL.format(symbol=urllib.parse.quote(symbol))
    payload = http_json(url)
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        raise UpdateError(f"Yahoo returned no result for {symbol}")
    block = result[0]
    stamps = block.get("timestamp") or []
    closes = ((block.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    bars = []
    for stamp, close in zip(stamps, closes):
        if close is None:
            continue
        # Daily bars are labeled by the exchange session date. UTC date matches
        # the cash session for the bars this page already cross-checks.
        bar_day = datetime.fromtimestamp(stamp, tz=NY).date()
        # Yahoo's daily timestamp is often 00:00 in the exchange zone, but some
        # bars arrive as the prior UTC evening. Prefer the New York date and
        # also keep the UTC date so either label can match the session.
        utc_day = datetime.fromtimestamp(stamp, tz=timezone_utc()).date()
        bars.append((bar_day, utc_day, D(close)))
    meta = block.get("meta") or {}
    price = parse_number(meta.get("regularMarketPrice"))
    return {"bars": bars, "last": price}


def timezone_utc():
    from datetime import timezone
    return timezone.utc


def yahoo_close_on(bars: list, day: date) -> Decimal | None:
    for local_day, utc_day, close in bars:
        if day in {local_day, utc_day}:
            return close
    return None


def fetch_quotes(snapshot: dict) -> dict:
    symbols = []
    for item in list(snapshot["instruments"].values()) + list(snapshot["crossAsset"].values()):
        symbol = item.get("cnbc")
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    if "US10Y" not in symbols:
        symbols.append("US10Y")
    try:
        cnbc = fetch_cnbc(symbols)
    except (urllib.error.URLError, TimeoutError, UpdateError, KeyError, ValueError) as exc:
        raise UpdateError(f"CNBC quote request failed: {exc}") from exc
    yahoo = {}
    yahoo_symbols = {}
    for key, item in list(snapshot["instruments"].items()) + list(snapshot["crossAsset"].items()):
        symbol = item.get("yahoo")
        if symbol:
            yahoo_symbols[key] = symbol
    yahoo_symbols["us10y"] = "^TNX"
    for key, symbol in yahoo_symbols.items():
        try:
            yahoo[symbol] = fetch_yahoo(symbol)
        except (urllib.error.URLError, TimeoutError, UpdateError, KeyError, ValueError, json.JSONDecodeError):
            yahoo[symbol] = None
    return {"cnbc": cnbc, "yahoo": yahoo}


def past_close(now: datetime, session: date, close_at: time) -> bool:
    local = as_ny(now)
    if local.date() > session:
        return True
    if local.date() < session:
        return False
    return local.time() >= close_at


def equity_print_accepted(quote: dict, session: date, close_at: time, now: datetime) -> bool:
    if not past_close(now, session, close_at):
        return False
    if quote.get("session_date") != session:
        return False
    clock = quote.get("clock")
    if clock is None:
        return True
    status = str(quote.get("status") or "").upper()
    if status in {"POST_MKT", "POST", "CLOSE", "CLOSED"}:
        return True
    close_minutes = close_at.hour * 60 + close_at.minute
    clock_minutes = clock.hour * 60 + clock.minute
    return clock_minutes >= close_minutes - 20


def prev_ties(quote: dict, prev_close, dec: int) -> str:
    last = quote["last"]
    prev = quote.get("prev")
    change = quote.get("change")
    tolerance = Decimal(10) ** -max(dec - 1, 0)
    if prev is not None and abs(D(prev) - D(prev_close)) <= max(tolerance, Decimal("0.02")):
        return "ok"
    if change is not None and abs((D(last) - D(change)) - D(prev_close)) <= max(tolerance, Decimal("0.02")):
        return "change-ties"
    return "mismatch"


def apply_quotes(snapshot: dict, decision: dict, quotes: dict) -> tuple[dict, list[str]]:
    snap = copy.deepcopy(snapshot)
    notes: list[str] = []
    job = decision["action"]
    session = decision["session_date"]
    close_at = close_time(session) if is_trading_day(session) or decision.get("early") else time(16, 0)
    if job == "post-close":
        blocked = apply_post_close(snap, session, close_at, decision["now"], quotes, notes)
        if blocked:
            raise UpdateError(blocked)
    elif job == "morning":
        apply_morning(snap, decision["now"], quotes, notes)
    else:
        raise UpdateError(f"unexpected job {job}")
    apply_us10y(snap, quotes, notes)
    return snap, notes


def apply_post_close(snap: dict, session: date, close_at: time, now: datetime, quotes: dict, notes: list[str]) -> str | None:
    accepted = {}
    for key in EQUITY_IDS:
        inst = snap["instruments"][key]
        quote = quotes["cnbc"].get(inst["cnbc"])
        if not quote or not equity_print_accepted(quote, session, close_at, now):
            return f"{key}: no verified cash close for {session.isoformat()} from CNBC"
        yahoo_symbol = inst.get("yahoo")
        yahoo_bar = None
        if yahoo_symbol and quotes["yahoo"].get(yahoo_symbol):
            yahoo_bar = yahoo_close_on(quotes["yahoo"][yahoo_symbol]["bars"], session)
        if yahoo_bar is not None and rel_diff(quote["last"], yahoo_bar) > BLOCK_DIFF:
            return (
                f"{key}: CNBC {quote['last']} and Yahoo {yahoo_bar} disagree by more than 0.5%; "
                "left the official close unchanged"
            )
        if key != "vix":
            # A rerun of the same session compares with prevClose. A new session
            # compares with the close we are about to rotate into prevClose.
            prior = inst["prevClose"] if snap["equitySession"]["date"] == session.isoformat() else inst["close"]
            tie = prev_ties(quote, prior, int(inst["dec"]))
            if tie == "mismatch" and yahoo_bar is None:
                return f"{key}: CNBC close does not tie to the stored previous close and Yahoo did not confirm it"
            if tie == "mismatch":
                notes.append(f"{key}: CNBC previous-day field does not match the stored official close; used CNBC last because Yahoo agrees")
        if yahoo_bar is not None and rel_diff(quote["last"], yahoo_bar) > NOTE_DIFF:
            notes.append(f"{key}: CNBC {quote['last']} vs Yahoo {yahoo_bar}")
        accepted[key] = (quote, yahoo_bar)

    new_session = snap["equitySession"]["date"] != session.isoformat()
    if new_session:
        for key in EQUITY_IDS:
            snap["instruments"][key]["prevClose"] = snap["instruments"][key]["close"]
        snap["previousEquitySession"] = copy.deepcopy(snap["equitySession"])
        snap["equitySession"] = {
            "date": session.isoformat(),
            "closeEt": close_at.strftime("%H:%M"),
            "earlyClose": is_early_close(session),
        }
    for key, (quote, _yahoo) in accepted.items():
        inst = snap["instruments"][key]
        dec = int(inst["dec"])
        inst["close"] = js_num(quote["last"], dec)
        ath = inst.get("ath")
        if ath and D(inst["close"]) > D(ath):
            inst["ath"] = js_num(inst["close"], dec)
            inst["athDate"] = session.isoformat()
            notes.append(f"{key}: new closing high {inst['close']}")
    append_vix(snap, session)
    apply_cross_post_close(snap, session, quotes, notes)
    return None


def append_vix(snap: dict, session: date) -> None:
    if not is_trading_day(session):
        return
    close = snap["instruments"]["vix"]["close"]
    path = snap["vixPath"]
    iso = session.isoformat()
    note = vix_note(session)
    if path and path[-1]["date"] == iso:
        path[-1]["close"] = close
        return
    if path and path[-1]["date"] > iso:
        raise UpdateError("VIX path is newer than the session being written")
    path.append({"date": iso, "close": close, "marker": None, "note": note})
    while len(path) > 14:
        path.pop(0)


def vix_note(session: date) -> dict:
    early = " · 提早收市 13:00 ET" if is_early_close(session) else ""
    early_en = " · early close 13:00 ET" if is_early_close(session) else ""
    return {"zh": weekday_zh(session) + early, "en": weekday_en(session) + early_en}


def apply_cross_post_close(snap: dict, session: date, quotes: dict, notes: list[str]) -> None:
    for key in CROSS_IDS:
        item = snap["crossAsset"][key]
        quote = quotes["cnbc"].get(item["cnbc"])
        yahoo_symbol = item.get("yahoo")
        yahoo_bar = None
        if yahoo_symbol and quotes["yahoo"].get(yahoo_symbol):
            yahoo_bar = yahoo_close_on(quotes["yahoo"][yahoo_symbol]["bars"], session)
        chosen = None
        kind = item.get("displayKind") or "settle"
        source = "unchanged"
        if key in {"brent", "wti", "gold", "silver"}:
            if quote and quote.get("settle") is not None and quote.get("settle_date") == session:
                chosen = quote["settle"]
                kind = "settle"
                source = "cnbc-settle"
                item["officialSettle"] = js_num(chosen, int(item["dec"]))
                item["settleDate"] = session.isoformat()
                if yahoo_bar is not None and rel_diff(chosen, yahoo_bar) > NOTE_DIFF:
                    extra = " Yahoo BZ=F is not used as the ICE settle." if key == "brent" else ""
                    notes.append(f"{key}: CNBC settle {chosen} vs Yahoo {yahoo_bar}.{extra}")
            else:
                notes.append(f"{key}: no CNBC settlement dated {session.isoformat()}; kept the previous official settle")
        elif key == "dxy":
            if quote and quote.get("session_date") == session:
                chosen = quote["last"]
                kind = "fx-close"
                source = "cnbc"
                if yahoo_bar is not None and rel_diff(chosen, yahoo_bar) > NOTE_DIFF:
                    notes.append(f"dxy: CNBC {chosen} vs Yahoo {yahoo_bar}")
            elif yahoo_bar is not None:
                chosen = yahoo_bar
                kind = "fx-close"
                source = "yahoo"
                notes.append("dxy: CNBC session print missing; used the Yahoo daily bar")
        else:
            # JPY and CNH follow the page: Yahoo daily bar, CNBC noted when it differs.
            if yahoo_bar is not None:
                chosen = yahoo_bar
                kind = "fx-close"
                source = "yahoo"
                if quote and quote.get("last") is not None and rel_diff(chosen, quote["last"]) > NOTE_DIFF:
                    notes.append(f"{key}: Yahoo {chosen} vs CNBC {quote['last']}")
            elif quote and quote.get("session_date") == session:
                chosen = quote["last"]
                kind = "fx-close"
                source = "cnbc"
                notes.append(f"{key}: Yahoo session bar missing; used CNBC")
        if chosen is None:
            continue
        dec = int(item["dec"])
        new_value = js_num(chosen, dec)
        if (
            item.get("value") == new_value
            and item.get("display") == new_value
            and item.get("displayKind") == kind
        ):
            continue
        if item.get("value") != new_value:
            item["prev"] = item.get("value")
        item["value"] = new_value
        item["display"] = new_value
        item["displayKind"] = kind
        item["source"] = source
        if quote and quote.get("last") is not None:
            item["cnbcLast"] = js_num(quote["last"], 3 if key == "dxy" else dec)
        if yahoo_bar is not None:
            item["yahooLast"] = js_num(yahoo_bar, dec)
        item["asOf"] = session.isoformat()


def apply_morning(snap: dict, now: datetime, quotes: dict, notes: list[str]) -> None:
    local = as_ny(now)
    for key in CROSS_IDS:
        item = snap["crossAsset"][key]
        quote = quotes["cnbc"].get(item["cnbc"])
        yahoo_pack = quotes["yahoo"].get(item.get("yahoo") or "")
        live = None
        yahoo_last = None
        if key in {"brent", "wti", "gold", "silver"}:
            if quote and quote.get("last") is not None and quote.get("clock") is not None:
                live = quote["last"]
            elif quote and quote.get("last") is not None and quote.get("session_date") == local.date():
                live = quote["last"]
        else:
            if yahoo_pack and yahoo_pack.get("last") is not None:
                yahoo_last = yahoo_pack["last"]
            if quote and quote.get("last") is not None:
                live = quote["last"]
            if key in {"jpy", "cnh"} and yahoo_last is not None:
                if live is not None and rel_diff(yahoo_last, live) > NOTE_DIFF:
                    notes.append(f"{key}: morning Yahoo {yahoo_last} vs CNBC {live}")
                live = yahoo_last
            elif key == "dxy" and live is not None and yahoo_last is not None and rel_diff(live, yahoo_last) > NOTE_DIFF:
                notes.append(f"dxy: morning CNBC {live} vs Yahoo {yahoo_last}")
        if live is None:
            notes.append(f"{key}: no morning print; left the tile on the last official figure")
            continue
        dec = int(item["dec"])
        shown = js_num(live, dec)
        if shown == item.get("display") and item.get("displayKind") != "intraday":
            continue
        if shown == item.get("value") and item.get("displayKind") in {"settle", "fx-close"}:
            continue
        item["display"] = shown
        item["displayKind"] = "intraday"
        item["asOf"] = local.strftime("%Y-%m-%dT%H:%M")
        if quote and quote.get("last") is not None:
            item["cnbcLast"] = js_num(quote["last"], 3 if key == "dxy" else dec)
        if yahoo_last is not None:
            item["yahooLast"] = js_num(yahoo_last, dec)
        notes.append(f"{key}: morning print {shown}")


def apply_us10y(snap: dict, quotes: dict, notes: list[str]) -> None:
    quote = quotes["cnbc"].get("US10Y")
    if not quote or quote.get("last") is None:
        return
    value = js_num(quote["last"], 3)
    current = snap.get("us10yMarket") or {}
    if current.get("value") == value:
        return
    when = ""
    if quote.get("session_date"):
        when = quote["session_date"].isoformat()
    if quote.get("clock"):
        when = f"{when}T{quote['clock'].strftime('%H:%M')}"
    snap["us10yMarket"] = {"value": value, "asOf": when}
    notes.append(f"US10Y market yield {value} (not an official Treasury cash yield)")


def balanced_div(html: str, start: int) -> tuple[int, int]:
    if not html.startswith("<div", start):
        raise UpdateError("expected a div")
    index = start
    depth = 0
    while index < len(html):
        if html.startswith("<div", index) and (index + 4 == len(html) or html[index + 4] in " \n>/"):
            depth += 1
            index = html.find(">", index)
            if index < 0:
                break
            index += 1
            continue
        if html.startswith("</div>", index):
            depth -= 1
            index += 6
            if depth == 0:
                return start, index
            continue
        index += 1
    raise UpdateError("unbalanced div")


def live_blocks(html: str, live_id: str) -> list[tuple[int, int]]:
    needle = f'data-live="{live_id}"'
    blocks = []
    cursor = 0
    while True:
        found = html.find(needle, cursor)
        if found < 0:
            break
        start = html.rfind("<div", 0, found)
        open_at, close_at = balanced_div(html, start)
        blocks.append((open_at, close_at))
        cursor = close_at
    return blocks


def replace_spans(html: str, spans: list[tuple[int, int, str]]) -> str:
    for start, end, new in sorted(spans, key=lambda item: item[0], reverse=True):
        if html[start:end] != new:
            html = html[:start] + new + html[end:]
    return html


def section_bounds(html: str, start_id: str, end_id: str) -> tuple[int, int]:
    start = html.find(f'id="{start_id}"')
    end = html.find(f'id="{end_id}"', start + 1)
    if start < 0 or end < 0:
        raise UpdateError(f"missing section {start_id}")
    return start, end


def patch_html(html: str, lang: str, snap: dict, job: str) -> str:
    if job == "post-close":
        html = patch_heroes(html, lang, snap)
        html = patch_sector_tiles(html, lang, snap)
        html = patch_tables(html, lang, snap)
        html = patch_overview(html, lang, snap)
        html = patch_equity_grid(html, lang, snap)
        html = patch_drawdown(html, lang, snap)
        html = patch_vix(html, lang, snap)
        html = patch_periods(html, lang, snap)
        html = patch_inst(html, snap, include_cross=True)
        html = patch_txt(html, snap)
        html = patch_cross_tiles(html, lang, snap, job)
        html = patch_labels(html, lang, snap, job)
    else:
        html = patch_cross_tiles(html, lang, snap, job)
        html = patch_cross_asof(html, lang, snap, job)
    html = patch_us10y(html, lang, snap)
    html = patch_status(html, lang, snap, job)
    html = patch_note(html, lang, snap, job)
    return html


def shown_cross(item: dict, job: str) -> tuple[str, str]:
    if job == "morning" and item.get("displayKind") == "intraday":
        return item.get("display") or item["value"], "intraday"
    return item.get("display") or item["value"], item.get("displayKind") or "settle"


def patch_heroes(html: str, lang: str, snap: dict) -> str:
    spans = []
    for key in ("spx", "ixic", "vix", "dxy"):
        for start, end in live_blocks(html, key):
            block = html[start:end]
            if "sec-tile" in block[:80]:
                continue
            if key == "dxy":
                value, kind = shown_cross(snap["crossAsset"]["dxy"], "post-close")
                prev = snap["crossAsset"]["dxy"].get("prev") or value
                dec = int(snap["crossAsset"]["dxy"]["dec"])
                level = fmt_num(value, dec)
                change = fmt_pct(day_pct(value, prev)) if prev and D(prev) != 0 else ""
                block = replace_hero_numbers(block, level, change, None, key)
            else:
                inst = snap["instruments"][key]
                level = fmt_num(inst["close"], int(inst["dec"]))
                if key == "vix":
                    points = fmt_signed(D(inst["close"]) - D(inst["prevClose"]), int(inst["dec"]))
                    change = points + " pts"
                    ath_text = None
                else:
                    change = fmt_pct(day_pct(inst["close"], inst["prevClose"]))
                    ath_text = fmt_pct(vs_ath(inst["close"], inst["ath"]))
                block = replace_hero_numbers(block, level, change, ath_text, key)
            spans.append((start, end, block))
    return replace_spans(html, spans)


def replace_hero_numbers(block: str, level: str, change: str, ath_text: str | None, key: str) -> str:
    current = re.search(r'<div class="v">([^<]*)</div>', block)
    if not current:
        return block
    if current.group(1) != level:
        block = block.replace(current.group(0), f'<div class="v">{level}</div>', 1)
    sign = 1 if change.startswith("＋") else (-1 if change.startswith("−") else 0)
    arrow = "▲ " if sign > 0 else ("▼ " if sign < 0 else "")
    chg_class = "up" if sign > 0 else ("down" if sign < 0 else "flat")
    chg_re = re.search(r'<span class="chg[^"]*">([^<]*)</span>', block)
    if chg_re and change:
        new_chg = f'<span class="chg {chg_class}">{arrow}{change}</span>'
        if chg_re.group(0) != new_chg and (current.group(1) != level or chg_re.group(1).strip() != f"{arrow}{change}".strip()):
            # Rewrite the change when the level changed or the printed change differs.
            old_num = re.search(r"[−＋+\-]?\d[\d,]*\.?\d*", chg_re.group(1))
            new_num = re.search(r"[−＋+\-]?\d[\d,]*\.?\d*", change)
            if current.group(1) != level or (old_num and new_num and old_num.group(0) != new_num.group(0)):
                block = block.replace(chg_re.group(0), new_chg, 1)
    if ath_text:
        block = re.sub(
            r"([−＋+\-]?\d+\.\d+%)(\s*ATH)",
            lambda match: ath_text + match.group(2) if match.group(1) != ath_text else match.group(0),
            block,
            count=1,
        )
    if key in {"spx", "ixic"}:
        if sign > 0 and "up-card" not in block:
            block = block.replace('class="tile hero"', 'class="tile hero up-card"', 1)
        if sign < 0:
            block = block.replace(" up-card", "", 1)
    return block


def patch_sector_tiles(html: str, lang: str, snap: dict) -> str:
    session = snap["equitySession"]
    day = session_date(session)
    spans = []
    for key in SECTOR_IDS:
        inst = snap["instruments"][key]
        ticker = key.upper()
        for start, end in live_blocks(html, key):
            block = html[start:end]
            if "sec-tile" not in block:
                continue
            pct = fmt_pct(day_pct(inst["close"], inst["prevClose"]))
            direction = "up" if pct.startswith("＋") else "down"
            level = fmt_num(inst["close"], int(inst["dec"]))
            if lang == "zh":
                when = f"{day.month} 月 {day.day} 日" + ("提早收市 " if session.get("earlyClose") else "收市 ")
                ao = when + level
            else:
                when = f"{day.day} {EN_MON[day.month - 1]} " + ("early close " if session.get("earlyClose") else "close ")
                ao = when + level
            new = re.sub(r'class="sec-tile[^"]*"', f'class="sec-tile {direction}-tile"', block, count=1)
            new = re.sub(
                r'(<div class="pc )[^"]*(">)(.*?)(</div>)',
                lambda m: m.group(1) + direction + m.group(2) + pct + m.group(4),
                new,
                count=1,
            )
            new = re.sub(
                r'(<div class="ao">)(.*?)(</div>)',
                lambda m: m.group(1) + ao + m.group(3),
                new,
                count=1,
            )
            spans.append((start, end, new))
    return replace_spans(html, spans)


def index_rows(lang: str, snap: dict) -> list[str]:
    ranked = []
    for key in INDEX_IDS:
        inst = snap["instruments"][key]
        ranked.append((day_pct(inst["close"], inst["prevClose"]), key))
    ranked.sort(key=lambda item: item[0], reverse=True)
    rows = []
    for rank, (_pct, key) in enumerate(ranked, start=1):
        rows.append(index_row(lang, snap, key, str(rank), pin=False))
    rows.append(index_row(lang, snap, "vix", "—", pin=True))
    return rows


def index_row(lang: str, snap: dict, key: str, rank: str, pin: bool) -> str:
    inst = snap["instruments"][key]
    dec = int(inst["dec"])
    close = fmt_num(inst["close"], dec)
    prev = fmt_num(inst["prevClose"], dec)
    change = fmt_signed(D(inst["close"]) - D(inst["prevClose"]), dec)
    pct = fmt_pct(day_pct(inst["close"], inst["prevClose"]))
    direction = "up" if change.startswith("＋") else ("down" if change.startswith("−") else "")
    cls = f"num {direction}".strip()
    name = INDEX_LABELS[lang][key]
    if key == "vix":
        ath = VIX_NA[lang]
    else:
        ath_pct = fmt_pct(vs_ath(inst["close"], inst["ath"]))
        ath_px = fmt_num(inst["ath"], dec)
        ath_day = date.fromisoformat(inst["athDate"])
        if lang == "zh":
            ath = f"{ath_pct}（{ath_day.isoformat()}：{ath_px}）"
        else:
            ath = f"{ath_pct} ({ath_day.day} {EN_MON_ABBR[ath_day.month - 1]} {ath_day.year}: {ath_px})"
    pin_attr = ' class="pin"' if pin else ""
    return (
        f'<tr{pin_attr}><td>{rank}</td><td>{name}</td>'
        f'<td class="num now">{close}</td><td class="num">{prev}</td>'
        f'<td class="{cls}">{change}</td><td class="{cls}">{pct}</td><td>{ath}</td></tr>'
    )


def sector_rows(lang: str, snap: dict) -> list[str]:
    ranked = []
    for key in SECTOR_IDS:
        inst = snap["instruments"][key]
        ranked.append((day_pct(inst["close"], inst["prevClose"]), SECTOR_IDS.index(key), key))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    rows = []
    for rank, (_pct, _order, key) in enumerate(ranked, start=1):
        rows.append(sector_row(lang, snap, key, str(rank), pin=False))
    rows.append(sector_row(lang, snap, "spym", SPYM_RANK[lang], pin=True))
    return rows


def sector_row(lang: str, snap: dict, key: str, rank: str, pin: bool) -> str:
    inst = snap["instruments"][key]
    dec = int(inst["dec"])
    ticker = "SPYM" if key == "spym" else key.upper()
    name = SPYM_NAME[lang] if key == "spym" else SECTOR_NAMES[lang][ticker]
    close = fmt_num(inst["close"], dec)
    prev = fmt_num(inst["prevClose"], dec)
    change = fmt_signed(D(inst["close"]) - D(inst["prevClose"]), dec)
    pct = fmt_pct(day_pct(inst["close"], inst["prevClose"]))
    direction = "up" if change.startswith("＋") else ("down" if change.startswith("−") else "")
    cls = f"num {direction}".strip()
    pin_attr = ' class="pin"' if pin else ""
    return (
        f'<tr{pin_attr}><td>{rank}</td><td>{ticker}</td><td>{name}</td>'
        f'<td class="num now">{close}</td><td class="num">{prev}</td>'
        f'<td class="{cls}">{change}</td><td class="{cls}">{pct}</td></tr>'
    )


def replace_tbody(html: str, body_id: str, rows: list[str]) -> str:
    match = re.search(rf'(<tbody id="{body_id}">)(.*?)(</tbody>)', html, re.S)
    if not match:
        raise UpdateError(f"missing tbody {body_id}")
    inner = "\n" + "\n".join("            " + row for row in rows) + "\n          "
    new = match.group(1) + inner + match.group(3)
    if new == match.group(0):
        return html
    return html[:match.start()] + new + html[match.end():]


def patch_tables(html: str, lang: str, snap: dict) -> str:
    html = replace_tbody(html, "idx-body", index_rows(lang, snap))
    html = replace_tbody(html, "sec-body", sector_rows(lang, snap))
    html = patch_print_tables(html, lang, snap)
    return html


def strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def match_print_id(cell: str, lang: str) -> str | None:
    text = strip_tags(cell)
    ticker = re.match(r"^(XL[A-Z]+|SPYM|SPY|QQQ|QQEW|RSP)\b", text)
    if ticker:
        return ticker.group(1).lower()
    for label, inst_id in PRINT_LABELS[lang]:
        if text == label or text.startswith(label):
            return inst_id
    return None


def patch_print_tables(html: str, lang: str, snap: dict) -> str:
    def repl_table(match: re.Match) -> str:
        table = match.group(0)
        headers = re.findall(r"<th\b", table)
        if len(headers) < 10:
            return table
        def repl_row(row_match: re.Match) -> str:
            row = row_match.group(0)
            cells = re.findall(r"<td([^>]*)>(.*?)</td>", row, re.S)
            if len(cells) < 4:
                return row
            inst_id = match_print_id(cells[0][1], lang)
            if not inst_id or inst_id not in snap["instruments"]:
                return row
            inst = snap["instruments"][inst_id]
            dec = int(inst["dec"])
            close = fmt_num(inst["close"], dec)
            prev = fmt_num(inst["prevClose"], dec)
            current = strip_tags(cells[1][1])
            if current not in {close, prev}:
                return row
            pct = fmt_pct(day_pct(inst["close"], inst["prevClose"]))
            direction = "up" if pct.startswith("＋") else ("down" if pct.startswith("−") else "")
            cls = f"num {direction}".strip()
            new_cells = list(cells)
            last_text = strip_tags(cells[-1][1])
            pct_now = strip_tags(cells[2][1])
            at_high = bool(inst.get("ath")) and inst_id != "vix" and D(inst["close"]) >= D(inst["ath"])
            high_labels = {"新高", "New high", "＋0.00%", "+0.00%", "0.00%"}
            expected_ath = ""
            if inst.get("ath") and inst_id != "vix" and not at_high:
                expected_ath = fmt_pct(vs_ath(inst["close"], inst["ath"]))
            unchanged = current == close and pct_now == pct and (
                inst_id == "vix"
                or not inst.get("ath")
                or (at_high and last_text in high_labels)
                or (expected_ath and (expected_ath == last_text or expected_ath in last_text))
            )
            if unchanged:
                return row
            new_cells[1] = (' class="num now"', close)
            new_cells[2] = (f' class="{cls}"', pct)
            if inst.get("ath") and inst_id != "vix" and re.search(r"%|新高|New high", last_text):
                if at_high:
                    new_cells[-1] = (' class="num up"', "＋0.00%")
                else:
                    new_cells[-1] = (' class="num down"', expected_ath)
            rebuilt = "<tr>" + "".join(f"<td{attrs}>{inner}</td>" for attrs, inner in new_cells) + "</tr>"
            # Keep a pin class if the original row had one.
            if 'class="pin"' in row[:40] or row.startswith('<tr class="pin"'):
                rebuilt = rebuilt.replace("<tr>", '<tr class="pin">', 1)
            return rebuilt
        return re.sub(r"<tr\b.*?</tr>", repl_row, table, flags=re.S)
    return re.sub(r'<table class="prints compact">.*?</table>', repl_table, html, flags=re.S)


def patch_overview(html: str, lang: str, snap: dict) -> str:
    start, end = section_bounds(html, "overview", "indexes")
    section = html[start:end]
    labels = OVERVIEW_LABELS[lang]

    def repl_row(label: str, level: str, percents: list[str] | None) -> None:
        nonlocal section
        pattern = rf'(<tr><td>{re.escape(label)}</td><td class="now">)(.*?)(</td><td>)(.*?)(</td>)'
        match = re.search(pattern, section)
        if not match:
            raise UpdateError(f"overview row missing: {label}")
        third = match.group(4)
        new_third = third
        if percents:
            tokens = re.findall(r"[−＋+\-]?\d+\.\d+%", third)
            if len(tokens) == len(percents):
                iterator = iter(percents)
                new_third = re.sub(r"[−＋+\-]?\d+\.\d+%", lambda _m: next(iterator), third)
        if match.group(2) == level and new_third == third:
            return
        section = section[:match.start()] + match.group(1) + level + match.group(3) + new_third + match.group(5) + section[match.end():]

    for key in ("spx", "dji", "ixic", "sox", "rsp"):
        inst = snap["instruments"][key]
        repl_row(labels[key], fmt_num(inst["close"], int(inst["dec"])), [fmt_pct(vs_ath(inst["close"], inst["ath"]))])
    ndx = snap["instruments"]["ndx"]
    qqq = snap["instruments"]["qqq"]
    slash = "／"
    level = fmt_num(ndx["close"], 2) + slash + fmt_num(qqq["close"], 2)
    repl_row(labels["ndxqqq"], level, [fmt_pct(vs_ath(ndx["close"], ndx["ath"])), fmt_pct(vs_ath(qqq["close"], qqq["ath"]))])
    vix = snap["instruments"]["vix"]
    repl_row(labels["vix"], fmt_num(vix["close"], 2), None)
    return html[:start] + section + html[end:]


def patch_equity_grid(html: str, lang: str, snap: dict) -> str:
    start, end = section_bounds(html, "equities", "crossasset")
    section = html[start:end]
    spans = []
    cursor = 0
    while True:
        found = section.find('<div class="tile"', cursor)
        if found < 0:
            break
        open_at, close_at = balanced_div(section, found)
        block = section[open_at:close_at]
        label = re.search(r'<div class="k">([^<]*)</div>', block)
        if label:
            for key, name in EQUITY_K[lang].items():
                if label.group(1) != name:
                    continue
                inst = snap["instruments"][key]
                level = fmt_num(inst["close"], int(inst["dec"]))
                new = re.sub(r'(<div class="v">)([^<]*)(</div>)', rf"\g<1>{level}\3", block, count=1)
                if key != "vix" and inst.get("ath"):
                    pct = fmt_pct(vs_ath(inst["close"], inst["ath"]))
                    if key == "ndx":
                        qqq = snap["instruments"]["qqq"]
                        percents = [pct, fmt_pct(vs_ath(qqq["close"], qqq["ath"]))]

                        def repl_inner(inner: str, values: list[str] = percents) -> str:
                            iterator = iter(values)
                            try:
                                return re.sub(r"[−＋+\-]?\d+\.\d+%", lambda _m: next(iterator), inner)
                            except StopIteration:
                                return inner

                        new = re.sub(
                            r'(<div class="d">)(.*?)(</div>)',
                            lambda m: m.group(1) + repl_inner(m.group(2)) + m.group(3) if "%" in m.group(2) else m.group(0),
                            new,
                            count=1,
                            flags=re.S,
                        )
                    else:
                        new = re.sub(
                            r'(<div class="d">)([−＋+\-]?\d+\.\d+%)',
                            lambda m: m.group(1) + pct if m.group(2) != pct else m.group(0),
                            new,
                            count=1,
                        )
                spans.append((open_at, close_at, new))
        cursor = close_at
    section = replace_spans(section, spans)
    return html[:start] + section + html[end:]


def patch_drawdown(html: str, lang: str, snap: dict) -> str:
    for key, label in DRAW_LABELS[lang].items():
        inst = snap["instruments"][key]
        pct = fmt_pct(vs_ath(inst["close"], inst["ath"]))
        price = fmt_num(inst["close"], int(inst["dec"]))
        color = bar_color(vs_ath(inst["close"], inst["ath"]))
        width = (abs(q(vs_ath(inst["close"], inst["ath"]), 2)) * Decimal(12)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        origin = (Decimal(760) - width).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        labeled = re.compile(
            rf'(<text[^>]*>){re.escape(label)}([（(])([^）)]*)([）)])(</text>\s*<rect\b)([^>]*?)(/>\s*<text\b)([^>]*?)(>)([−＋+\-]?\d+\.\d+%)(</text>)',
            re.S,
        )
        plain = re.compile(
            rf'(<text[^>]*>){re.escape(label)}(</text>\s*<rect\b)([^>]*?)(/>\s*<text\b)([^>]*?)(>)([−＋+\-]?\d+\.\d+%)(</text>)',
            re.S,
        )

        def paint(attrs: str) -> str:
            attrs = re.sub(r'\bx="[^"]*"', f'x="{origin}"', attrs, count=1)
            attrs = re.sub(r'\bwidth="[^"]*"', f'width="{width}"', attrs, count=1)
            attrs = re.sub(r'\bfill="[^"]*"', f'fill="{color}"', attrs, count=1)
            return attrs

        def paint_text(attrs: str) -> str:
            label_x = origin - Decimal(8)
            attrs = re.sub(r'\bx="[^"]*"', f'x="{label_x}"', attrs, count=1)
            attrs = re.sub(r'\bfill="[^"]*"', f'fill="{color}"', attrs, count=1)
            return attrs

        match = labeled.search(html)
        if match and (match.group(10) != pct or price not in match.group(3)):
            html = labeled.sub(
                lambda m: m.group(1) + label + m.group(2) + price + m.group(4) + m.group(5) + paint(m.group(6)) + m.group(7) + paint_text(m.group(8)) + m.group(9) + pct + m.group(11),
                html,
                count=1,
            )
            continue
        match = plain.search(html)
        if match and match.group(7) != pct:
            html = plain.sub(
                lambda m: m.group(1) + label + m.group(2) + paint(m.group(3)) + m.group(4) + paint_text(m.group(5)) + m.group(6) + pct + m.group(8),
                html,
                count=1,
            )
    return html


def bar_color(pct: Decimal) -> str:
    if pct <= Decimal("-20"):
        return "#C53030"
    if pct <= Decimal("-10"):
        return "#D95D24"
    return "#0D7A5F"


def vix_steps_span(html: str) -> tuple[int, int]:
    start = html.find('<div class="steps n14">')
    if start < 0:
        raise UpdateError("missing VIX steps")
    return balanced_div(html, start)


def vix_closes_match(html: str, closes: list[str]) -> bool:
    start, end = vix_steps_span(html)
    current = re.findall(r'<div class="n">([^<]*)</div>', html[start:end])
    return len(current) == len(closes) and all(D(left) == D(right) for left, right in zip(current, closes))


def patch_vix(html: str, lang: str, snap: dict) -> str:
    closes = [fmt_num(item["close"], 2) for item in snap["vixPath"]]
    same = vix_closes_match(html, closes)
    if not same:
        html = patch_vix_data(html, lang, snap, closes)
        html = patch_vix_steps(html, lang, snap, closes)
        html = patch_vix_sequences(html, snap, closes)
    html = patch_vix_labels(html, lang, snap, closes)
    return html


def patch_vix_data(html: str, lang: str, snap: dict, closes: list[str]) -> str:
    match = re.search(r"var vixData = \[(.*?)\];", html, re.S)
    if not match:
        raise UpdateError("missing vixData")
    current = re.findall(r"\bv:\s*([\d.]+)", match.group(1))
    if current == [item["close"] if "." in str(item["close"]) else item["close"] for item in snap["vixPath"]] or [fmt_num(item, 2) for item in current] == closes:
        # Compare numerically.
        if len(current) == len(closes) and all(D(a) == D(b) for a, b in zip(current, closes)):
            return html
    lines = ["var vixData = ["]
    for item in snap["vixPath"]:
        day = date.fromisoformat(item["date"])
        label = f"{day.month}/{day.day}"
        note = (item.get("note") or {}).get(lang) or (weekday_zh(day) if lang == "zh" else weekday_en(day))
        note = note.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'    {{ d: "{label}", v: {fmt_num(item["close"], 2)}, note: "{note}" }},')
    lines.append("  ];")
    return html[:match.start()] + "\n".join(lines) + html[match.end():]


def patch_vix_steps(html: str, lang: str, snap: dict, closes: list[str]) -> str:
    start, end = vix_steps_span(html)
    block = html[start:end]
    current = re.findall(r'<div class="n">([^<]*)</div>', block)
    if len(current) == len(closes) and all(D(a) == D(b) for a, b in zip(current, closes)):
        return html
    rows = []
    for item in snap["vixPath"]:
        day = date.fromisoformat(item["date"])
        if lang == "zh":
            label = f"{day.month} 月 {day.day} 日"
        else:
            label = f"{day.day} {EN_MON_ABBR[day.month - 1]}"
        marker = item.get("marker")
        css = "st" + (f" {marker}" if marker in {"low", "peak"} else "")
        rows.append(f'      <div class="{css}"><div class="dt">{label}</div><div class="n">{fmt_num(item["close"], 2)}</div></div>')
    inner = '<div class="steps n14">\n' + "\n".join(rows) + "\n    </div>"
    return html[:start] + inner + html[end:]


def patch_vix_sequences(html: str, snap: dict, closes: list[str]) -> str:
    last = closes[-1]
    previous = closes[-2] if len(closes) > 1 else snap["instruments"]["vix"]["prevClose"]
    sequence = " → ".join(closes[:-1]) + " → <strong>" + last + "</strong>"

    def repl_seq(match: re.Match) -> str:
        body = match.group(0)
        numbers = re.findall(r"\d+\.\d+", body)
        if not numbers or D(numbers[-1]) != D(previous):
            return body
        if body.lstrip().startswith("…"):
            tail = " → ".join(closes[-8:-1]) + " → <strong>" + last + "</strong>"
            return "…→" + tail
        return sequence

    return re.sub(r"(?:…→)?(?:\d+\.\d+\s*→\s*){6,}(?:<strong>)?\d+\.\d+(?:</strong>)?", repl_seq, html)


def patch_vix_labels(html: str, lang: str, snap: dict, closes: list[str]) -> str:
    last = closes[-1]
    first = closes[0]
    first_day = date.fromisoformat(snap["vixPath"][0]["date"])
    last_day = date.fromisoformat(snap["vixPath"][-1]["date"])
    title = re.search(r'(<p class="pc-title">)(VIX[^<]*)(</p>)', html)
    end_shown = f"{last_day.day} 日" in title.group(2) if title and lang == "zh" else (
        title is not None and re.search(rf"(?<!\d){last_day.day}(?!\d)", title.group(2)) is not None
        and (EN_MON[last_day.month - 1] in title.group(2) or EN_MON_ABBR[last_day.month - 1] in title.group(2))
    )
    if title and not end_shown:
        if lang == "zh":
            text = f"VIX 路徑 · 14 個交易日收市（{first_day.month} 月 {first_day.day} 日至 {last_day.day} 日，可互動）"
        else:
            text = f"VIX Path · 14 Session Closes ({first_day.day}–{last_day.day} {EN_MON[last_day.month - 1]}, Interactive)"
        html = html[:title.start()] + title.group(1) + text + title.group(3) + html[title.end():]
    aria = re.search(r'(<svg id="vix-svg"[^>]*aria-label=")([^"]*)(")', html)
    if aria and last not in aria.group(2):
        if lang == "zh":
            label = f"可互動的 VIX 14 個交易日路徑：由 {first_day.month} 月 {first_day.day} 日收市 {first} 至 {last_day.month} 月 {last_day.day} 日收市 {last}"
        else:
            label = f"Interactive VIX 14-session path from {first_day.day} {EN_MON[first_day.month - 1]} close of {first} to {last_day.day} {EN_MON[last_day.month - 1]} close of {last}"
        html = html[:aria.start()] + aria.group(1) + label + aria.group(3) + html[aria.end():]
    return html


def js_string(rows: list[str]) -> str:
    inner = "".join(row.replace("\\", "\\\\").replace('"', '\\"') for row in rows)
    return inner


def replace_js_string_property(html: str, var_name: str, prop: str, new_inner: str) -> str:
    start = html.find(f"var {var_name} = ")
    if start < 0:
        raise UpdateError(f"missing {var_name}")
    end = html.find("\n  var ", start + 1)
    if end < 0:
        end = len(html)
    block = html[start:end]
    pattern = rf'("{prop}":\s*")((?:\\.|[^"\\])*)(")'
    new_block, count = re.subn(pattern, lambda m: m.group(1) + new_inner + m.group(3), block, count=1)
    if count != 1:
        raise UpdateError(f"missing {var_name}.{prop}")
    return html[:start] + new_block + html[end:]


def patch_periods(html: str, lang: str, snap: dict) -> str:
    html = replace_js_string_property(html, "IDX_PERIODS", "1D", js_string(index_rows(lang, snap)))
    html = replace_js_string_property(html, "SEC_PERIODS", "1D", js_string(sector_rows(lang, snap)))
    html = patch_sector_chart(html, lang, snap)
    day = session_date(snap["equitySession"])
    if not session_chip_current(html, day, lang):
        if lang == "zh":
            chip = f"起始上一交易日收市 → {day.month} 月 {day.day} 日" + ("提早收市" if snap["equitySession"].get("earlyClose") else "收市")
        else:
            chip = f"Prior close → {day.day} {EN_MON[day.month - 1]}" + (" early close" if snap["equitySession"].get("earlyClose") else " close")
        html = replace_js_string_property(html, "PERIOD_CHIPS", "1D", chip)
    return html


def session_chip_current(html: str, day: date, lang: str) -> bool:
    start = html.find("var PERIOD_CHIPS = ")
    if start < 0:
        return True
    end = html.find("\n  var ", start + 1)
    return date_mentioned(html[start:end], day, lang)


def patch_sector_chart(html: str, lang: str, snap: dict) -> str:
    start = html.find("var SEC_CHART_DATA = ")
    if start < 0:
        raise UpdateError("missing SEC_CHART_DATA")
    end = html.find("\n  function ", start)
    block = html[start:end]
    match = re.search(r'("1D":\s*\[)(.*?)(\n\s*\],)', block, re.S)
    if not match:
        raise UpdateError("missing SEC_CHART_DATA 1D")
    existing = re.findall(r'tk:\s*"([A-Z]+)",\s*name:\s*"([^"]*)",\s*v:\s*(-?\d+(?:\.\d+)?)', match.group(2))
    names = {ticker: name for ticker, name, _value in existing}
    ranked = []
    for key in SECTOR_IDS:
        ticker = key.upper()
        pct = day_pct(snap["instruments"][key]["close"], snap["instruments"][key]["prevClose"])
        ranked.append((pct, SECTOR_IDS.index(key), ticker, names.get(ticker, SECTOR_NAMES[lang][ticker])))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    existing_pairs = sorted((ticker, str(q(value, 2))) for ticker, _name, value in existing)
    ranked_pairs = sorted((ticker, str(q(pct, 2))) for pct, _order, ticker, _name in ranked)
    if existing_pairs == ranked_pairs:
        return html
    lines = []
    for pct, _order, ticker, name in ranked:
        number = f"{q(pct, 2):.2f}".rstrip("0").rstrip(".")
        lines.append(f'      {{ tk: "{ticker}", name: "{name}", v: {number} }}')
    array = "\n" + ",\n".join(lines) + "\n    "
    new_block = block[:match.start(2)] + array + block[match.end(2):]
    return html[:start] + new_block + html[end:]


def patch_inst(html: str, snap: dict, include_cross: bool) -> str:
    start = html.find("  var INST = {")
    end = html.find("\n  };", start)
    if start < 0 or end < 0:
        raise UpdateError("missing INST")
    block = html[start:end]
    lines = block.split("\n")
    new_lines = []
    for line in lines:
        match = re.match(r"\s*([A-Za-z0-9]+):\s*\{", line)
        if not match or match.group(1) == "us10y":
            new_lines.append(line)
            continue
        key = match.group(1)
        if key in snap["instruments"] and key in INST_KEYS:
            inst = snap["instruments"][key]
            line = re.sub(r"(official:\s*)(-?\d+(?:\.\d+)?)", lambda m: m.group(1) + js_num(inst["close"], int(inst["dec"])), line, count=1)
            if inst.get("ath") and "ath:" in line:
                line = re.sub(r"(ath:\s*)(-?\d+(?:\.\d+)?)", lambda m: m.group(1) + js_num(inst["ath"], int(inst["dec"])), line, count=1)
        elif include_cross and key in snap["crossAsset"]:
            item = snap["crossAsset"][key]
            line = re.sub(r"(official:\s*)(-?\d+(?:\.\d+)?)", lambda m: m.group(1) + js_num(item["value"], int(item["dec"])), line, count=1)
        new_lines.append(line)
    return html[:start] + "\n".join(new_lines) + html[end:]


def txt_block(snap: dict) -> str:
    session = snap["equitySession"]
    day = session_date(session)
    early = bool(session.get("earlyClose"))
    clock = session["closeEt"]
    zh_base = f"{weekday_zh(day)} {day.month} 月 {day.day} 日"
    zh_kind = f"{zh_base}官方提早收市" if early else f"{zh_base}官方收市"
    zh_idle = f"數據：{zh_kind}（{clock} ET；開啟時可更新）"
    zh_fail = f"未能更新即時報價，仍顯示上次官方收市（{zh_base}提早收市）" if early else f"未能更新即時報價，仍顯示上次官方收市（{zh_base}）"
    zh_official = f"官方收市（{zh_base}提早收市）" if early else f"官方收市（{zh_base}）"
    zh_asof = f"即時／延遲最後價，對官方{zh_base}提早收市" if early else f"即時／延遲最後價，對官方{zh_base}收市"
    zh_cnh = f"{weekday_zh(day)}外匯時段收市（Yahoo 日線，非官方中間價）"
    zh_settle = f"{weekday_zh(day)}官方結算"
    en_kind = f"{weekday_en(day)} {day.day} {EN_MON[day.month - 1]} early close" if early else f"{weekday_en(day)} {day.day} {EN_MON[day.month - 1]}"
    en_idle = f"Data: official {en_kind}, {clock} ET (can update when opened)" if early else f"Data: official {en_kind} close, {clock} ET (can update when opened)"
    en_fail = f"Could not refresh live quotes; still showing the last official close ({en_kind})"
    en_official = f"Official close ({en_kind})"
    en_asof = f"Live / delayed last vs official {en_kind}"
    en_cnh = f"{weekday_en(day)} FX-session close (Yahoo daily, not an official fixing)"
    en_settle = f"{weekday_en(day)} official settlement"
    return f"""  var TXT = LANG === "zh" ? {{
    idle: "{zh_idle}",
    loading: "正在更新報價…",
    fail: "{zh_fail}",
    successPrefix: "即時／延遲報價，開啟時已更新：",
    successSuffix: " 香港時間",
    officialClose: "官方收市",
    officialWed: "{zh_official}",
    compiledCnh: "{zh_cnh}",
    officialSettle: "{zh_settle}",
    vsOfficial: "對官方收市",
    vsSettle: "對官方結算",
    vsCompiled: "對編譯時盤中",
    updatedCount: function (n) {{ return "（已更新 " + n + " 個代碼）"; }},
    vsAth: "距 ATH",
    sameAsOfficial: "與官方收市相同",
    liveDelayed: "即時／延遲",
    mktYield: "市場收益率（US10Y，非財政部官方現金收益率）",
    asof1d: "{zh_asof}",
    sourceCnbc: "來源：CNBC delayed/live，非官方收市",
    nUpdated: "已更新"
  }} : {{
    idle: "{en_idle}",
    loading: "Refreshing quotes…",
    fail: "{en_fail}",
    successPrefix: "Live / delayed quotes, updated on open: ",
    successSuffix: " Hong Kong time",
    officialClose: "Official close",
    officialWed: "{en_official}",
    compiledCnh: "{en_cnh}",
    officialSettle: "{en_settle}",
    vsOfficial: "vs official close",
    vsSettle: "vs official settlement",
    vsCompiled: "vs compiled print",
    updatedCount: function (n) {{ return " (" + n + " symbols updated)"; }},
    vsAth: "from ATH",
    sameAsOfficial: "unchanged vs official close",
    liveDelayed: "Live / delayed",
    mktYield: "Market yield (US10Y, not the official Treasury cash yield)",
    asof1d: "{en_asof}",
    sourceCnbc: "Source: CNBC delayed/live, not an official close",
    nUpdated: "Updated"
  }};"""


def patch_txt(html: str, snap: dict) -> str:
    start = html.find("  var TXT = LANG === \"zh\" ? {")
    end = html.find("\n  var INST = {", start)
    if start < 0 or end < 0:
        raise UpdateError("missing TXT")
    return html[:start] + txt_block(snap) + "\n\n" + html[end + 1:]


def cross_caption(item: dict, lang: str, job: str) -> tuple[str, str]:
    value, kind = shown_cross(item, job)
    dec = int(item["dec"])
    prev = item.get("prev") or item.get("value")
    pct = fmt_pct(day_pct(value, prev)) if prev and D(prev) != 0 else ""
    cnbc = item.get("cnbcLast")
    yahoo = item.get("yahooLast")
    if kind == "intraday":
        if lang == "zh":
            short = f"08:00 ET 盤中 {pct}，非官方結算".strip()
            detail = f"盤中 {fmt_num(value, dec)}"
            if cnbc:
                detail += f"；CNBC {cnbc}"
            if yahoo:
                detail += f"；Yahoo {yahoo}"
            if item.get("value"):
                detail += f"。上一官方數字仍為 {fmt_num(item['value'], dec)}"
        else:
            short = f"08:00 ET intraday {pct}, not an official settle".strip()
            detail = f"Intraday {fmt_num(value, dec)}"
            if cnbc:
                detail += f"; CNBC {cnbc}"
            if yahoo:
                detail += f"; Yahoo {yahoo}"
            if item.get("value"):
                detail += f". Last official figure remains {fmt_num(item['value'], dec)}"
        return short, detail
    if lang == "zh":
        label = "官方結算" if kind == "settle" else "外匯收市"
        short = f"{label} {pct}".strip()
        detail = f"CNBC {cnbc or fmt_num(value, dec)}"
        if yahoo:
            detail += f"；Yahoo {yahoo}"
    else:
        label = "Official settle" if kind == "settle" else "FX-session close"
        short = f"{label} {pct}".strip()
        detail = f"CNBC {cnbc or fmt_num(value, dec)}"
        if yahoo:
            detail += f"; Yahoo {yahoo}"
    return short, detail


def patch_cross_tiles(html: str, lang: str, snap: dict, job: str) -> str:
    spans = []
    for key in CROSS_IDS:
        item = snap["crossAsset"][key]
        value, _kind = shown_cross(item, job)
        level = fmt_num(value, int(item["dec"]))
        short, detail = cross_caption(item, lang, job)
        for start, end in live_blocks(html, key):
            block = html[start:end]
            if "sec-tile" in block[:120]:
                continue
            current = re.search(r'<div class="v">([^<]*)</div>', block)
            if not current or current.group(1) == level:
                continue
            new = current.group(0).replace(current.group(1), level)
            block = block.replace(current.group(0), new, 1)
            block = re.sub(r'(<div class="d">)(.*?)(</div>)', lambda m: m.group(1) + short + m.group(3), block, count=1)
            block = re.sub(
                r'(<div class="s">)(.*?)(</div>)',
                lambda m: m.group(1) + detail + m.group(3),
                block,
                count=1,
                flags=re.S,
            )
            if '<span class="chg' in block:
                sign = 1 if short.find("＋") >= 0 else (-1 if "−" in short else 0)
                arrow = "▲ " if sign > 0 else ("▼ " if sign < 0 else "")
                chg_class = "up" if sign > 0 else ("down" if sign < 0 else "flat")
                pct = fmt_pct(day_pct(value, item.get("prev") or value))
                block = re.sub(r'<span class="chg[^"]*">[^<]*</span>', f'<span class="chg {chg_class}">{arrow}{pct}</span>', block, count=1)
            spans.append((start, end, block))
    return replace_spans(html, spans)


def patch_labels(html: str, lang: str, snap: dict, job: str) -> str:
    status = re.search(r'<span id="quote-status"[^>]*>([^<]*)</span>', html)
    day = session_date(snap["equitySession"])
    if status and date_mentioned(status.group(1), day, lang):
        return html
    text = phrase(snap["equitySession"], lang)
    if lang == "zh":
        idle = f"數據：{text}（開啟時可更新）"
        header = f"股指為{text}"
        period = f"資料時點　股指 {day.isoformat()} {snap['equitySession']['closeEt']} ET　·　跨資產同時點　·　宏觀維持上次官方印值"
        hint = f"官方收市快照　｜　{text}"
        equity_tail = "　" + text
        cross_tail = "　" + ("官方結算／外匯收市，同時點" )
    else:
        idle = f"Data: {text} (can update when opened)"
        header = f"Equities are the {text}"
        period = f"As of　Equities {day.isoformat()} {snap['equitySession']['closeEt']} ET　·　Cross-asset same timestamp　·　Macro unchanged"
        hint = f"Official close snapshot ｜ {text}"
        equity_tail = "　" + text
        cross_tail = "　Official settlement / FX-session close, same timestamp"
    html = re.sub(r'(<span id="quote-status"[^>]*>)([^<]*)(</span>)', rf"\1{idle}\3", html, count=1)
    html = re.sub(r'(<p class="header-sub">)(.*?)(</p>)', rf"\1{header}\3", html, count=1, flags=re.S)
    html = re.sub(r'(<div class="period">)(.*?)(</div>)', rf"\1{period}\3", html, count=1, flags=re.S)
    for section_id in ("overview", "indexes", "equities", "crossasset"):
        html = replace_hint(html, section_id, hint)
    html = replace_asof(html, ASOF_EQUITY[lang], equity_tail)
    html = replace_asof(html, ASOF_CROSS[lang], cross_tail)
    chip = hint
    html = re.sub(r'(<span class="asof-chip" id="idx-asof">)(.*?)(</span>)', rf"\1{chip}\3", html, count=1)
    html = re.sub(r'(<span class="asof-chip" id="sec-asof">)(.*?)(</span>)', rf"\1{chip}\3", html, count=1)
    return html


def replace_hint(html: str, section_id: str, text: str) -> str:
    start, end = section_bounds(html, section_id, {"overview": "indexes", "indexes": "sectors", "equities": "crossasset", "crossasset": "macro"}[section_id])
    section = html[start:end]
    new, count = re.subn(r'(<span class="hint">)(.*?)(</span>)', rf"\1{text}\3", section, count=1, flags=re.S)
    if count != 1:
        return html
    return html[:start] + new + html[end:]


def replace_asof(html: str, label: str, tail: str) -> str:
    pattern = rf'(<span class="asof"><b>{re.escape(label)}</b>)(.*?)(</span>)'
    return re.sub(pattern, rf"\1{tail}\3", html, count=1, flags=re.S)


def patch_cross_asof(html: str, lang: str, snap: dict, job: str) -> str:
    if not any(snap["crossAsset"][key].get("displayKind") == "intraday" for key in CROSS_IDS):
        return html
    if lang == "zh":
        tail = "　08:00 ET 盤中／即時，非股指官方收市，亦非把未結算報價寫成官方結算"
    else:
        tail = "　08:00 ET intraday, not an equity official close and not treated as an official settle unless labeled"
    return replace_asof(html, ASOF_CROSS[lang], tail)


def patch_us10y(html: str, lang: str, snap: dict) -> str:
    market = snap.get("us10yMarket") or {}
    if not market.get("value"):
        return html
    when = market.get("asOf") or ""
    clock = ""
    if "T" in when:
        clock = when.split("T", 1)[1][:5] + " ET"
    if lang == "zh":
        text = f"市場收益率 US10Y {market['value']}%" + (f"（{clock}，非財政部官方現金收益率）" if clock else "（非財政部官方現金收益率）")
    else:
        text = f"Market yield US10Y {market['value']}%" + (f" ({clock}, not the official Treasury cash yield)" if clock else " (not the official Treasury cash yield)")
    spans = []
    for start, end in live_blocks(html, "us10y"):
        block = html[start:end]
        if re.search(r'class="quote-official"', block):
            block = re.sub(r'(<div class="quote-official">)(.*?)(</div>)', rf"\1{text}\3", block, count=1, flags=re.S)
        else:
            block = block[:-6] + f'<div class="quote-official">{text}</div></div>'
        spans.append((start, end, block))
    return replace_spans(html, spans)


def patch_status(html: str, lang: str, snap: dict, job: str) -> str:
    session = snap["equitySession"]
    match = re.search(r'<span id="quote-status"[^>]*>', html)
    if not match:
        raise UpdateError("missing quote-status")
    tag = match.group(0)
    tag = re.sub(r'\sdata-snapshot-[a-z]+="[^"]*"', "", tag)
    attrs = f' data-snapshot-date="{session["date"]}" data-snapshot-close="{session["closeEt"]}" data-snapshot-job="{job}"'
    tag = tag[:-1] + attrs + ">"
    return html[:match.start()] + tag + html[match.end():]


def note_text(lang: str, snap: dict, job: str) -> str:
    session = phrase(snap["equitySession"], lang)
    morning = any(snap["crossAsset"][key].get("displayKind") == "intraday" for key in CROSS_IDS)
    if lang == "zh":
        text = f"自動更新快照：股指、VIX、11 隻產業 SPDR 與 SPY／QQQ／RSP／QQEW／SPYM 的官方收市為{session}。早晨 08:00 ET 只更新跨資產，不覆蓋這些官方收市。GDP、PCE、CPI、PPI、NFP、官方 HY OAS、ChartRow 廣度、SSGA 持股權重、財政部現金收益率與文字評論維持上次人工版本。"
        if morning:
            text += "跨資產磚上若標明盤中，該數字不是官方結算。"
        return text
    text = f"Auto-updated snapshot: official closes for equities, VIX, the 11 sector SPDRs, and SPY / QQQ / RSP / QQEW / SPYM are the {session}. The 08:00 ET run refreshes cross-assets only and does not overwrite those official closes. GDP, PCE, CPI, PPI, NFP, official HY OAS, ChartRow breadth, SSGA holding weights, official Treasury cash yields, and the written commentary stay on the last human edition."
    if morning:
        text += " A cross-asset tile marked intraday is not an official settlement."
    return text


def patch_note(html: str, lang: str, snap: dict, job: str) -> str:
    paragraph = f'<p class="note" id="auto-snapshot-note">{note_text(lang, snap, job)}</p>'
    if 'id="auto-snapshot-note"' in html:
        return re.sub(r'<p class="note" id="auto-snapshot-note">.*?</p>', paragraph, html, count=1, flags=re.S)
    return html.replace("<main>", "<main>\n" + paragraph + "\n", 1)


def render_pages(snapshot: dict, job: str, root: Path = ROOT) -> dict[str, str]:
    changed = {}
    for lang, name in (("zh", "zh.html"), ("en", "en.html")):
        path = root / name
        original = path.read_text(encoding="utf-8")
        updated = patch_html(original, lang, snapshot, job)
        if updated != original:
            changed[name] = updated
    return changed


def write_outputs(snapshot: dict, pages: dict[str, str], root: Path, write_snapshot: bool) -> None:
    if write_snapshot:
        save_snapshot(snapshot, root / "data" / "official-snapshot.json")
    for name, text in pages.items():
        (root / name).write_text(text, encoding="utf-8")


def snapshot_changed(before: dict, after: dict) -> bool:
    return json.dumps(before, ensure_ascii=False, sort_keys=True) != json.dumps(after, ensure_ascii=False, sort_keys=True)


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Update the US market dashboard snapshot.")
    parser.add_argument("--job", choices=["auto", "post-close", "morning"], default="auto")
    parser.add_argument("--now", help="Timezone-aware timestamp, used for tests and dry runs.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--ignore-calendar", action="store_true", help="Test hook. Scheduled runs must not set this.")
    parser.add_argument("--render-snapshot", action="store_true", help="Rewrite snapshot fields from data/official-snapshot.json without fetching.")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(tz=NY)
    if now.tzinfo is None:
        now = now.replace(tzinfo=NY)
    snapshot = load_snapshot(args.root / "data" / "official-snapshot.json")
    if args.render_snapshot:
        pages = render_pages(snapshot, "post-close", args.root)
        print(f"render-snapshot: {len(pages)} file(s) would change" if args.dry_run else f"render-snapshot: updated {sorted(pages)}")
        if not args.dry_run:
            write_outputs(snapshot, pages, args.root, write_snapshot=False)
        return 0
    decision = decide(now, args.job, args.ignore_calendar)
    if decision["action"] == "noop":
        print(f"No-op: {decision['reason']}")
        return 0
    print(
        f"Job {decision['action']} on {decision['session_date'].isoformat()} "
        f"(cash close {decision['close_et']} ET)"
    )
    try:
        quotes = fetch_quotes(snapshot)
        updated, notes = apply_quotes(snapshot, decision, quotes)
    except UpdateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    for note in notes:
        print(f"note: {note}")
    pages = render_pages(updated, decision["action"], args.root)
    changed_snapshot = snapshot_changed(snapshot, updated)
    if not pages and not changed_snapshot:
        print("No figure changes.")
        return 0
    print(f"Would write {sorted(pages)}{' and official-snapshot.json' if changed_snapshot else ''}" if args.dry_run else f"Writing {sorted(pages)}")
    if args.dry_run:
        return 0
    write_outputs(updated, pages, args.root, write_snapshot=changed_snapshot)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(run())
