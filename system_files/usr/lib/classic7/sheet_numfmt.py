"""Number formats for Sheet: Excel's format codes ("#,##0.00", "0%", "dd-mm-yyyy",
'[Red]-#,##0;#,##0', "@") turned into the text shown in a cell, and typed text turned
back into numbers, dates and percentages."""
from __future__ import annotations

import datetime as dt
import decimal as _decimal
import math
import re

from sheet_formula import EPOCH, XLError, fmt_general, from_serial, parse_date

DEC = "."        # decimal point and thousands separator shown in cells (set from the locale)
GROUP = ","

BUILTIN = {
    0: "General", 1: "0", 2: "0.00", 3: "#,##0", 4: "#,##0.00", 9: "0%", 10: "0.00%", 11: "0.00E+00",
    12: "# ?/?", 13: "# ??/??", 14: "dd-mm-yyyy", 15: "d-mmm-yy", 16: "d-mmm", 17: "mmm-yy",
    18: "h:mm AM/PM", 19: "h:mm:ss AM/PM", 20: "h:mm", 21: "h:mm:ss", 22: "dd-mm-yyyy h:mm",
    37: "#,##0 ;(#,##0)", 38: "#,##0 ;[Red](#,##0)", 39: "#,##0.00;(#,##0.00)",
    40: "#,##0.00;[Red](#,##0.00)", 45: "mm:ss", 46: "[h]:mm:ss", 47: "mmss.0", 48: "##0.0E+0", 49: "@",
}

COLORS = {"black": "#000000", "blue": "#0000ff", "cyan": "#00ffff", "green": "#008000", "magenta": "#ff00ff",
          "red": "#ff0000", "white": "#ffffff", "yellow": "#ffff00"}

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def set_locale(decimal_point: str, group: str):
    global DEC, GROUP
    DEC, GROUP = decimal_point or ".", group or ","


def _sections(fmt: str) -> list[str]:
    out, cur, quoted, esc = [], "", False, False
    for ch in fmt:
        if esc:
            cur += ch
            esc = False
            continue
        if ch == "\\":
            cur += ch
            esc = True
            continue
        if ch == '"':
            quoted = not quoted
        if ch == ";" and not quoted:
            out.append(cur)
            cur = ""
            continue
        cur += ch
    out.append(cur)
    return out


COND_RE = re.compile(r"\[(<=|>=|<>|<|>|=)(-?[\d.]+)\]")
BRACKET_RE = re.compile(r"\[([^\]]*)\]")


def _pick_section(value, fmt: str):
    secs = _sections(fmt)
    if isinstance(value, str):
        if len(secs) >= 4:
            return secs[3], False
        for s in secs:
            if "@" in s:
                return s, False
        return "@", False
    conds = [COND_RE.search(s) for s in secs]
    if any(conds):
        for s, c in zip(secs, conds):
            if c:
                op, num = c.group(1), float(c.group(2))
                ok = {"<": value < num, ">": value > num, "=": value == num, "<=": value <= num,
                      ">=": value >= num, "<>": value != num}[op]
                if ok:
                    return s, False
            elif s is secs[-1]:
                return s, False
        return secs[-1], False
    if len(secs) == 1:
        return secs[0], False
    if value > 0 or (value == 0 and len(secs) < 3):
        return secs[0], False
    if value < 0:
        return secs[1], True          # the minus sign is in the section (or left out on purpose)
    return secs[2], False


def is_date_format(fmt: str) -> bool:
    f = BRACKET_RE.sub(lambda m: "h" if m.group(1).lower() in ("h", "hh", "m", "mm", "s", "ss") else "", fmt)
    f = re.sub(r'"[^"]*"|\\.', "", f)
    return bool(re.search(r"[dmyhs]", f, re.I)) and not re.search(r"[0#?]", f)


def format_value(value, fmt: str | None) -> tuple[str, str | None]:
    """(text, colour) for a value shown with a format code."""
    if value is None:
        return "", None
    if isinstance(value, XLError):
        return value.code, None
    if isinstance(value, bool):
        return ("TRUE" if value else "FALSE"), None
    fmt = fmt or "General"
    if isinstance(value, str):
        sec, _ = _pick_section(value, fmt) if ";" in fmt or "@" in fmt else ("@", False)
        color = _color(sec)
        sec = BRACKET_RE.sub("", sec)
        return _literal_fill(sec, value), color
    v = float(value)
    sec, neg_section = _pick_section(v, fmt)
    color = _color(sec)
    if neg_section:
        v = abs(v)
    clean = BRACKET_RE.sub(lambda m: m.group(0) if re.fullmatch(r"[hms]+", m.group(1), re.I)
                           else (_currency(m.group(1)) or ""), sec)
    if clean.strip().lower() in ("general", ""):
        text = general(v)
        return (("-" if v < 0 and neg_section else "") + text if not neg_section else text), color
    if is_date_format(clean):
        if v < 0:
            return "#" * 8, None
        return _format_date(v, clean), color
    return _format_number(v, clean), color


def general(v: float) -> str:
    """Excel's General in a standard-width cell: up to 11 characters (933.3333333, 0.333333333,
    1234567891), switching to scientific when that would show more (3.33333E-05, 1.23457E+11)."""
    if v == 0:
        return "0"
    a = abs(v)
    sign = "-" if v < 0 else ""

    def sci():
        m, e = f"{a:.5E}".split("E")
        m = m.rstrip("0").rstrip(".")
        return f"{sign}{m}E{int(e):+03d}".replace(".", DEC)
    if a >= 1e11:
        return sci()
    int_len = len(str(int(a)))
    places = max(0, 10 - int_len)
    s = str(_decimal.Decimal(repr(a)).quantize(_decimal.Decimal(1).scaleb(-places), _decimal.ROUND_HALF_UP))
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if len(s) > 11 or (a < 1e-4 and float(s) != a):
        return sci()
    if s == "0":
        return "0"
    return (sign + s).replace(".", DEC)


def _color(sec: str) -> str | None:
    for m in BRACKET_RE.finditer(sec):
        name = m.group(1).lower()
        if name in COLORS:
            return COLORS[name]
        mc = re.fullmatch(r"color\s*(\d+)", name)
        if mc:
            from sheet_model import INDEXED_COLORS
            i = int(mc.group(1)) + 7
            if 0 <= i < len(INDEXED_COLORS):
                return INDEXED_COLORS[i]
    return None


def _currency(code: str) -> str | None:
    if code.startswith("$"):
        return '"' + code[1:].split("-")[0] + '"'
    return None


def _literal_fill(sec: str, text: str) -> str:
    out, i = "", 0
    while i < len(sec):
        ch = sec[i]
        if ch == '"':
            j = sec.find('"', i + 1)
            out += sec[i + 1:j if j > 0 else len(sec)]
            i = (j if j > 0 else len(sec)) + 1
            continue
        if ch == "\\" and i + 1 < len(sec):
            out += sec[i + 1]
            i += 2
            continue
        if ch in "_*" and i + 1 < len(sec):
            out += " " if ch == "_" else ""
            i += 2
            continue
        out += text if ch == "@" else ch
        i += 1
    return out


def _tokens(sec: str):
    """Split a number/date section into ('lit', text) and ('code', ch) pieces."""
    out, i = [], 0
    while i < len(sec):
        ch = sec[i]
        if ch == '"':
            j = sec.find('"', i + 1)
            out.append(("lit", sec[i + 1:j if j > 0 else len(sec)]))
            i = (j if j > 0 else len(sec)) + 1
        elif ch == "\\" and i + 1 < len(sec):
            out.append(("lit", sec[i + 1]))
            i += 2
        elif ch == "_" and i + 1 < len(sec):
            out.append(("lit", " "))
            i += 2
        elif ch == "*" and i + 1 < len(sec):
            i += 2
        else:
            out.append(("code", ch))
            i += 1
    return out


def _format_number(v: float, sec: str) -> str:
    toks = _tokens(sec)
    codes = "".join(t for k, t in toks if k == "code")
    percent = codes.count("%")
    v = v * (100 ** percent)
    # scientific
    m = re.search(r"([0#?.,]+)[eE]([+-])([0#]+)", codes)
    if m:
        mant_fmt, sign, exp_fmt = m.group(1), m.group(2), m.group(3)
        decimals = len(mant_fmt.split(".")[1]) if "." in mant_fmt else 0
        int_digits = max(1, len(mant_fmt.split(".")[0].replace(",", "")))
        if v == 0:
            exp = 0
        else:
            exp = int(math.floor(math.log10(abs(v))))
            if int_digits > 1:
                exp -= exp % int_digits
        mant = v / (10 ** exp) if v else 0
        mtxt = f"{abs(mant):.{decimals}f}".replace(".", DEC)
        etxt = str(abs(exp)).zfill(len(exp_fmt))
        esign = "-" if exp < 0 else ("+" if sign == "+" else "")
        pre = "".join(t for k, t in toks[:0])
        return ("-" if v < 0 else "") + pre + mtxt + "E" + esign + etxt
    # fractions: "# ?/?" or "?/8"
    fm = re.search(r"(#*\s*)?([?0#]+)/([?0#]+|\d+)", codes)
    if fm and "/" in codes:
        whole_part = bool(fm.group(1) and fm.group(1).strip())
        denom_fmt = fm.group(3)
        sign = "-" if v < 0 else ""
        a = abs(v)
        whole = int(a) if whole_part else 0
        frac = a - whole
        if denom_fmt.isdigit():
            d = int(denom_fmt)
            n = round(frac * d)
        else:
            maxd = 10 ** len(denom_fmt) - 1
            best = (0, 1, 1.0)
            for d in range(1, maxd + 1):
                n = round(frac * d)
                err = abs(frac - n / d)
                if err < best[2] - 1e-12:
                    best = (n, d, err)
            n, d = best[0], best[1]
        if n == d and whole_part:
            whole, n = whole + 1, 0
        if n == 0:
            return f"{sign}{whole}" if whole_part else f"{sign}0"
        return f"{sign}{str(whole) + ' ' if whole_part and whole else ''}{n}/{d}"
    # plain numbers: integer and decimal placeholders
    num_part = re.search(r"[0#?,.]*[0#?][0#?,.]*", codes)
    if not num_part:
        out = "".join(t if k == "lit" else ("" if t in "%" else t) for k, t in toks)
        return out + ("%" * 0)
    pattern = num_part.group(0)
    scale = 0
    while pattern.endswith(","):
        scale += 1
        pattern = pattern[:-1]
    v = v / (1000 ** scale)
    int_fmt, _, dec_fmt = pattern.partition(".")
    grouping = "," in int_fmt
    int_fmt = int_fmt.replace(",", "")
    decimals = len(dec_fmt)
    rounded = round(abs(v) + 1e-12 * (abs(v) > 0), decimals)
    s = f"{rounded:.{decimals}f}"
    ip, _, dp = s.partition(".")
    # decimal places: trailing zeros only where the format has 0
    if dp:
        keep = len(dec_fmt.rstrip("#?"))
        dp_out = dp[:keep] + dp[keep:].rstrip("0")
        pad = dec_fmt[len(dp_out):]
        dp_out += "".join(" " if ch == "?" else "" for ch in pad)
    else:
        dp_out = ""
    min_int = int_fmt.count("0")
    if ip == "0" and min_int == 0:
        ip = ""
    ip = ip.zfill(min_int) if min_int else ip
    if grouping and ip:
        ip = f"{int(ip):,}".replace(",", "\x00") if ip.isdigit() else ip
        ip = ip.replace("\x00", GROUP)
    number = ip + (DEC + dp_out if decimals and (dp_out or "." in pattern) else "")
    if decimals and not dp_out.strip() and dec_fmt.strip("#") == "":
        number = ip + DEC
    # rebuild: literals before and after the number, % signs
    out, placed = "", False
    code_positions = [i for i, (k, t) in enumerate(toks) if k == "code" and t in "0#?,."]
    first_num = code_positions[0] if code_positions else len(toks)
    last_num = code_positions[-1] if code_positions else -1
    for idx, (k, t) in enumerate(toks):
        if first_num <= idx <= last_num:
            if not placed:
                out += number
                placed = True
            continue
        out += t
    if v < 0 and rounded != 0:
        out = "-" + out
    return out


def _format_date(v: float, sec: str) -> str:
    d = from_serial(round(v * 86400) / 86400)
    ampm = bool(re.search(r"AM/PM|A/P", sec, re.I))
    sec = re.sub(r"AM/PM", "\x02", sec, flags=re.I)
    sec = re.sub(r"A/P", "\x03", sec, flags=re.I)
    sec = re.sub(r"\[h+\]", "\x04", sec, flags=re.I)
    sec = re.sub(r"\[(m+|s+)\]", r"\1", sec, flags=re.I)
    toks = _tokens(sec)
    out = []
    codes = []
    # group consecutive same letters into tokens
    for k, t in toks:
        if k == "code" and t.lower() in "ymdhsa/:0." and codes and codes[-1][0] == "code" and \
                codes[-1][1][0].lower() == t.lower() and t.lower() in "ymdhs":
            codes[-1] = ("code", codes[-1][1] + t)
        else:
            codes.append((k, t))
    # AM/PM
    text_codes = []
    for idx, (k, t) in enumerate(codes):
        text_codes.append((k, t))
    for idx, (k, t) in enumerate(text_codes):
        if k == "lit":
            out.append(t)
            continue
        if t == "\x02":
            out.append("AM" if d.hour < 12 else "PM")
            continue
        if t == "\x03":
            out.append("A" if d.hour < 12 else "P")
            continue
        if t == "\x04":
            out.append(str(int(v * 24 + 1e-9)))
            continue
        low = t.lower()
        if low.startswith("y"):
            out.append(f"{d.year % 100:02d}" if len(t) <= 2 else str(d.year))
        elif low.startswith("m"):
            # minutes if after an hour or before seconds
            prev = next((c for c in reversed(text_codes[:idx]) if c[0] == "code" and (c[1][0].lower() in "hymds"
                                                                                      or c[1] == "\x04")), None)
            nxt = next((c for c in text_codes[idx + 1:] if c[0] == "code" and c[1][0].lower() in "hymds"), None)
            minutes = (prev and (prev[1][0].lower() == "h" or prev[1] == "\x04")) or (nxt and nxt[1][0].lower() == "s")
            if minutes and len(t) <= 2:
                out.append(f"{d.minute:0{len(t)}d}")
            elif len(t) == 1:
                out.append(str(d.month))
            elif len(t) == 2:
                out.append(f"{d.month:02d}")
            elif len(t) == 3:
                out.append(MONTHS[d.month - 1][:3])
            elif len(t) == 5:
                out.append(MONTHS[d.month - 1][0])
            else:
                out.append(MONTHS[d.month - 1])
        elif low.startswith("d"):
            if len(t) == 1:
                out.append(str(d.day))
            elif len(t) == 2:
                out.append(f"{d.day:02d}")
            elif len(t) == 3:
                out.append(DAYS[d.weekday()][:3])
            else:
                out.append(DAYS[d.weekday()])
        elif low.startswith("h"):
            h = d.hour
            if ampm:
                h = h % 12 or 12
            out.append(f"{h:0{min(len(t), 2)}d}")
        elif low.startswith("s"):
            out.append(f"{d.second:0{min(len(t), 2)}d}")
        elif t == "[":
            out.append("")
        else:
            out.append(t)
    return "".join(out)


# ---- typing into a cell ---------------------------------------------------------------------------
NUM_RE = re.compile(r"^[+-]?(\d+([.,]\d*)?|[.,]\d+)([eE][+-]?\d+)?$")


def parse_input(text: str):
    """What the user typed -> (value, suggested format or None). Formulas start with '='."""
    t = text.strip()
    if t == "":
        return None, None
    if t.upper() in ("TRUE", "FALSE"):
        return t.upper() == "TRUE", None
    from sheet_formula import ERRORS
    if t.upper() in ERRORS:
        return ERRORS[t.upper()], None
    # numbers with the locale's separators or the C locale's
    cand = t.replace(" ", "")
    pct = cand.endswith("%")
    if pct:
        cand = cand[:-1]
    currency = None
    for sym in ("kr.", "kr", "$", "€", "£", "DKK"):
        if cand.startswith(sym) or cand.endswith(sym):
            currency = sym
            cand = cand.replace(sym, "").strip()
            break
    neg = cand.startswith("(") and cand.endswith(")")
    if neg:
        cand = cand[1:-1]
    grouped = False
    if GROUP and GROUP in cand and DEC != GROUP:
        parts = cand.lstrip("+-").split(DEC)[0].split(GROUP)
        if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]) and parts[0]:
            cand = cand.replace(GROUP, "")
            grouped = True
    if DEC != ".":
        cand = cand.replace(DEC, ".")
    if NUM_RE.match(cand) and "," not in cand:
        v = float(cand)
        if neg:
            v = -v
        if pct:
            decimals = len(cand.split(".")[1]) if "." in cand else 0
            return v / 100, "0%" if not decimals else "0." + "0" * decimals + "%"
        if currency:
            return v, f'#,##0.00 "{currency}"' if currency in ("kr", "kr.", "DKK") else f'"{currency}"#,##0.00'
        if grouped:
            return v, "#,##0" if "." not in cand else "#,##0.00"
        return v, None
    d = parse_date(t)
    if d is not None:
        if ":" in t and not re.search(r"\d{4}|\d+[-/.]\d+[-/.]", t):
            return d, "h:mm" if t.count(":") == 1 else "h:mm:ss"
        if ":" in t:
            return d, "dd-mm-yyyy h:mm"
        return d, "dd-mm-yyyy"
    return text, None


def date_to_serial(d: dt.date | dt.datetime) -> float:
    if not isinstance(d, dt.datetime):
        d = dt.datetime(d.year, d.month, d.day)
    delta = d - EPOCH
    return delta.days + delta.seconds / 86400


def edit_text(value, fmt: str | None) -> str:
    """The text shown in the formula bar for a value (dates as dates, percents with %)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, XLError):
        return value.code
    if isinstance(value, (int, float)):
        f = fmt or "General"
        if is_date_format(BRACKET_RE.sub("", f)) or is_date_format(f):
            d = from_serial(value + 1e-9)
            if value < 1:
                return d.strftime("%H:%M:%S")
            if abs(value - int(value)) > 1e-9:
                return d.strftime("%d-%m-%Y %H:%M:%S")
            return d.strftime("%d-%m-%Y")
        if f.endswith("%") and "%" in f:
            return (fmt_general(value * 100) + "%").replace(".", DEC)
        return fmt_general(float(value)).replace(".", DEC)
    return str(value)
