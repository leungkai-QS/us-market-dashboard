"""Deterministic status lines derived from the official snapshot.

These phrases describe the close, the distance from the stored ATH, the
5 November 2026 anchors that are actually in the snapshot, a stored
up/down streak, the VIX band, and the sector leader and laggard.
They do not state a market call.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

ZH_WD = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
EN_WD = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
EN_MON = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
ANCHOR_DATE = "2026-11-05"
SECTOR_ORDER = ["xlk", "xly", "xlc", "xlb", "xli", "xle", "xlf", "xlre", "xlp", "xlv", "xlu"]


def D(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def q(value, dec: int) -> Decimal:
    return D(value).quantize(Decimal(1).scaleb(-dec), rounding=ROUND_HALF_UP)


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


def fmt_num(value, dec: int) -> str:
    number = q(value, dec)
    body = f"{abs(number):,.{dec}f}"
    return ("−" if number < 0 else "") + body


def day_pct(close, prev) -> Decimal:
    return (D(close) - D(prev)) / D(prev) * Decimal(100)


def vs_ath(close, ath) -> Decimal:
    return (D(close) / D(ath) - 1) * Decimal(100)


def session_day(snap: dict) -> date:
    return date.fromisoformat(snap["equitySession"]["date"])


def weekday_name(day: date, lang: str) -> str:
    return ZH_WD[day.weekday()] if lang == "zh" else EN_WD[day.weekday()]


def anchors(snap: dict) -> dict:
    return ((snap.get("anchors") or {}).get(ANCHOR_DATE) or {})


def streaks(snap: dict) -> dict:
    return snap.get("streaks") or {}


def next_streak(current: int, delta: Decimal) -> int:
    if delta > 0:
        return current + 1 if current > 0 else 1
    if delta < 0:
        return current - 1 if current < 0 else -1
    return 0


def drawdown_zone(pct: Decimal) -> str:
    if pct >= 0:
        return "high"
    if pct <= Decimal("-20"):
        return "bear"
    if pct <= Decimal("-10"):
        return "correction"
    return "outside"


def zone_text(zone: str, lang: str) -> tuple[str, str]:
    table = {
        "zh": {
            "high": ("刷新收市高", ""),
            "outside": ("仍在調整區外", ""),
            "correction": ("仍在調整", ""),
            "bear": ("收市回撤深於 20%", " deep"),
        },
        "en": {
            "high": ("New closing high", ""),
            "outside": ("Outside a correction", ""),
            "correction": ("In a correction", ""),
            "bear": ("Drawdown deeper than 20%", " deep"),
        },
    }
    return table[lang][zone]


def recapture_text(close, anchor, lang: str) -> str | None:
    if anchor is None:
        return None
    above = D(close) >= D(anchor)
    if lang == "zh":
        return "已收復 11 月 5 日收市" if above else "仍低於 11 月 5 日收市"
    return "back above the 5 Nov 2026 close" if above else "still below the 5 Nov 2026 close"


def streak_text(count: int, lang: str) -> str | None:
    if not count:
        return None
    days = abs(int(count))
    if lang == "zh":
        return f"連升{days}日" if count > 0 else f"連跌{days}日"
    word = "day" if days == 1 else "days"
    return f"up {days} {word}" if count > 0 else f"down {days} {word}"


def index_status(key: str, snap: dict, lang: str) -> tuple[str, str]:
    inst = snap["instruments"][key]
    pct = vs_ath(inst["close"], inst["ath"]) if inst.get("ath") else None
    if pct is None:
        raise ValueError(f"{key} has no ATH")
    zone = drawdown_zone(pct)
    text, css = zone_text(zone, lang)
    parts = [text]
    recapture = recapture_text(inst["close"], anchors(snap).get(key), lang)
    if recapture:
        parts.append(recapture)
    streak = streak_text(int(streaks(snap).get(key, 0) or 0), lang)
    if streak:
        parts.append(streak)
    joiner = "，" if lang == "zh" else ", "
    return joiner.join(parts), css


def vix_band(close) -> str:
    level = D(close)
    if level < 20:
        return "below20"
    if level < 25:
        return "below_mid"
    if level <= 35:
        return "mid"
    if level < 40:
        return "above_mid"
    return "panic"


def vix_regime_text(close, lang: str) -> tuple[str, str]:
    band = vix_band(close)
    table = {
        "zh": {
            "below20": ("已回到 &lt;20", " ok"),
            "below_mid": ("已跌出 25–35 中段、尚未回到 &lt;20", ""),
            "mid": ("仍在 25–35 中段", ""),
            "above_mid": ("高於中段、尚未收市 ≥40", " deep"),
            "panic": ("收市 ≥40", " deep"),
        },
        "en": {
            "below20": ("Back below 20", " ok"),
            "below_mid": ("Out of the 25–35 mid-band, not yet below 20", ""),
            "mid": ("Inside the 25–35 mid-band", ""),
            "above_mid": ("Above the mid-band, not a ≥40 close", " deep"),
            "panic": ("Closed at or above 40", " deep"),
        },
    }
    return table[lang][band]


def vix_path_text(path: list, lang: str) -> str:
    touched = any(D(item["close"]) >= 40 for item in path)
    if lang == "zh":
        return "近 14 日曾收市 ≥40" if touched else "近 14 日未收市 ≥40"
    return "A ≥40 close is in the last 14 sessions" if touched else "No ≥40 close in the last 14 sessions"


def rsp_status(snap: dict, lang: str) -> tuple[str, str]:
    rsp = vs_ath(snap["instruments"]["rsp"]["close"], snap["instruments"]["rsp"]["ath"])
    spy = vs_ath(snap["instruments"]["spy"]["close"], snap["instruments"]["spy"]["ath"])
    shallower = rsp > spy
    if lang == "zh":
        return ("仍淺於市值加權" if shallower else "不淺於市值加權", " ok" if shallower else "")
    return (
        "Shallower than cap-weighted" if shallower else "Not shallower than cap-weighted",
        " ok" if shallower else "",
    )


def hero_equity_caption(key: str, snap: dict, lang: str) -> str:
    inst = snap["instruments"][key]
    status, _css = index_status(key, snap, lang)
    ath = fmt_pct(vs_ath(inst["close"], inst["ath"]))
    sep = "　｜　" if lang == "zh" else " ｜ "
    return f"{ath} ATH{sep}{status}"


def equity_vix_caption(snap: dict, lang: str) -> str:
    inst = snap["instruments"]["vix"]
    points = fmt_signed(D(inst["close"]) - D(inst["prevClose"]), int(inst["dec"]))
    regime, _css = vix_regime_text(inst["close"], lang)
    path = vix_path_text(snap.get("vixPath") or [], lang)
    if lang == "zh":
        return f"對上一官方收市 {points} 點<br/>{regime}；{path}"
    return f"{points} pts vs prior official close<br/>{regime}; {path}"


def hero_vix_caption(snap: dict, lang: str) -> str:
    regime, _css = vix_regime_text(snap["instruments"]["vix"]["close"], lang)
    path = vix_path_text(snap.get("vixPath") or [], lang)
    sep = "　｜　" if lang == "zh" else " ｜ "
    return regime + sep + path


def qqq_clause(snap: dict, lang: str) -> str:
    """Price, then the one-day change in parentheses. Vs-ATH stays outside that pair."""
    qqq = snap["instruments"]["qqq"]
    price = fmt_num(qqq["close"], 2)
    day = fmt_pct(day_pct(qqq["close"], qqq["prevClose"]))
    ath = fmt_pct(vs_ath(qqq["close"], qqq["ath"]))
    if lang == "zh":
        return f"QQQ {price}（{day}） · 距 ATH {ath}"
    return f"QQQ {price} ({day}) · {ath} vs ATH"


def equity_caption(key: str, snap: dict, lang: str) -> str:
    inst = snap["instruments"][key]
    dec = int(inst["dec"])
    day = session_day(snap)
    name = weekday_name(day, lang)
    change = fmt_pct(day_pct(inst["close"], inst["prevClose"]))
    ath_px = fmt_num(inst["ath"], dec)
    status, _css = index_status(key, snap, lang)
    if lang == "zh":
        line1 = f"{name} {change} · ATH {ath_px}"
        extra = []
        if key == "spx":
            spy = snap["instruments"]["spy"]
            extra.append("SPY " + fmt_pct(vs_ath(spy["close"], spy["ath"])))
        if key == "ndx":
            extra.append(qqq_clause(snap, "zh"))
        tail = " · ".join(extra + [status]) if extra else status
        return line1 + "<br/>" + tail
    line1 = f"{name} {change} · ATH {ath_px}"
    extra = []
    if key == "spx":
        spy = snap["instruments"]["spy"]
        extra.append("SPY " + fmt_pct(vs_ath(spy["close"], spy["ath"])))
    if key == "ndx":
        extra.append(qqq_clause(snap, "en"))
    tail = " · ".join(extra + [status]) if extra else status
    return line1 + "<br/>" + tail


def sector_rank_text(snap: dict, lang: str) -> str:
    rows = []
    for key in SECTOR_ORDER:
        inst = snap["instruments"][key]
        rows.append((q(day_pct(inst["close"], inst["prevClose"]), 2), key.upper()))
    best = max(item[0] for item in rows)
    worst = min(item[0] for item in rows)
    leaders = [ticker for pct, ticker in rows if pct == best]
    laggards = [ticker for pct, ticker in rows if pct == worst]
    lead_px = fmt_pct(best)
    lag_px = fmt_pct(worst)
    lead_names = "、".join(leaders) if lang == "zh" else ", ".join(leaders)
    lag_names = "、".join(laggards) if lang == "zh" else ", ".join(laggards)
    if lang == "zh":
        if best > 0 and worst < 0:
            return f"領漲 {lead_names} {lead_px}　｜　落後 {lag_names} {lag_px}"
        if best <= 0:
            return f"跌幅最小 {lead_names} {lead_px}　｜　領跌 {lag_names} {lag_px}"
        return f"領漲 {lead_names} {lead_px}　｜　升幅最小 {lag_names} {lag_px}"
    if best > 0 and worst < 0:
        return f"Leader {lead_names} {lead_px} ｜ Laggard {lag_names} {lag_px}"
    if best <= 0:
        return f"Smallest decline {lead_names} {lead_px} ｜ Largest decline {lag_names} {lag_px}"
    return f"Leader {lead_names} {lead_px} ｜ Smallest gain {lag_names} {lag_px}"


def period_chip(snap: dict, lang: str) -> str:
    start = date.fromisoformat(snap["previousEquitySession"]["date"])
    end = session_day(snap)
    early = bool(snap["equitySession"].get("earlyClose"))
    if lang == "zh":
        end_label = f"{end.month} 月 {end.day} 日" + ("提早收市" if early else "收市")
        return f"起始 {start.month} 月 {start.day} 日收市 → {end_label}"
    end_label = f"{end.day} {EN_MON[end.month - 1]}" + (" early close" if early else " close")
    return f"From {start.day} {EN_MON[start.month - 1]} close → {end_label}"


def last_date_chip(snap: dict, lang: str) -> str:
    day = session_day(snap)
    if lang == "zh":
        return f"最後價日期一律 {day.month} 月 {day.day} 日"
    return f"Last-price date is {day.day} {EN_MON[day.month - 1]}"


def ath_chart_title(snap: dict, lang: str) -> str:
    day = session_day(snap)
    early = "提早收市" if snap["equitySession"].get("earlyClose") else "收市"
    if lang == "zh":
        return f"距收市歷史高位（ATH）· 截至{weekday_name(day, lang)} {day.month} 月 {day.day} 日{early}"
    early_en = " early close" if snap["equitySession"].get("earlyClose") else " close"
    return (
        "Distance from closing ATH · As of "
        f"{weekday_name(day, lang)} {day.day} {EN_MON[day.month - 1]}{early_en}"
    )


def skipped_status_notes(snap: dict) -> list[str]:
    notes = []
    known = anchors(snap)
    for key in ("ndx", "sox", "rut", "dji", "qqq", "spy"):
        if key not in known:
            notes.append(
                f"{key}: no {ANCHOR_DATE} anchor in the snapshot; "
                "auto status will not say whether that close was recaptured"
            )
    notes.append("YTD is not in the snapshot; auto status pills do not repeat a year-to-date figure")
    notes.append(
        "The all-history claim that VIX has never closed at or above 40 is not re-derived; "
        "the auto line uses only the stored 14-session path"
    )
    tracked = set(streaks(snap))
    for key in ("spx", "ixic", "ndx", "sox"):
        if key not in tracked:
            notes.append(f"{key}: no stored up/down streak; auto status will not state a multi-day streak")
    notes.append("Sector and index commentary paragraphs stay manual; the leader/laggard chip uses the 11 sector day-changes")
    return notes
