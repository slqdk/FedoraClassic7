"""The logic of the Windows 7 Calculator, without any window.

Standard: immediate execution (2 + 3 * 4 = 20), repeated = (2 + 3 = = gives 8), % of the first
number, sqrt/1/x/negate on the shown number. Scientific and Programmer: operator precedence and
parentheses (2 + 3 * 4 = 14). Programmer works on whole numbers of 8/16/32/64 bits in two's
complement, shown in Hex, Dec, Oct or Bin. Numbers are kept as Decimal (40 digits) so 0.1 + 0.2
is exactly 0.3.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal, DivisionByZero, InvalidOperation, Overflow, localcontext, getcontext

getcontext().prec = 40
getcontext().Emax = 9999
getcontext().Emin = -9999

PI = Decimal("3.1415926535897932384626433832795028841971693993751")
E = Decimal("2.7182818284590452353602874713526624977572470936999")

DIV0 = "Cannot divide by zero"
INVALID = "Invalid input"
OVERFLOW = "Overflow"
UNDEFINED = "Result is undefined"

# binary operators: symbol shown in the history line, precedence, right-associative
BINARY = {
    "+": ("+", 1, False), "-": ("-", 1, False), "*": ("*", 2, False), "/": ("/", 2, False),
    "mod": ("Mod", 2, False), "pow": ("^", 3, True), "root": ("yroot", 3, True),
    # programmer
    "and": ("And", -2, False), "or": ("Or", -4, False), "xor": ("Xor", -3, False),
    "lsh": ("Lsh", 0, False), "rsh": ("Rsh", 0, False),
}


class CalcError(Exception):
    pass


def to_signed(v: int, bits: int) -> int:
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >> (bits - 1) else v


def _dec(x) -> Decimal:
    if isinstance(x, Decimal):
        return x
    if isinstance(x, float):
        if math.isinf(x) or math.isnan(x):
            raise CalcError(OVERFLOW if math.isinf(x) else INVALID)
        return Decimal(repr(x))
    return Decimal(x)


def _float15(x: float) -> Decimal:
    """A float result rounded to 15 significant digits, so asin(0.5) in degrees is 30, not 30.000000000000004."""
    v = _dec(x)
    with localcontext() as ctx:
        ctx.prec = 15
        return +v


def _dsin(x: Decimal) -> Decimal:
    """sin with the full Decimal precision (Taylor series after reducing to -pi..pi)."""
    with localcontext() as ctx:
        ctx.prec += 6
        two_pi = 2 * PI
        x = x % two_pi
        if x > PI:
            x -= two_pi
        elif x < -PI:
            x += two_pi
        i, last, total, fact, num, sign = 1, 0, x, 1, x, 1
        while total != last:
            last = total
            i += 2
            fact *= i * (i - 1)
            num *= x * x
            sign = -sign
            total += num / fact * sign
    return +total


def _dcos(x: Decimal) -> Decimal:
    return _dsin(x + PI / 2)


def _check(v: Decimal) -> Decimal:
    if v.is_nan():
        raise CalcError(INVALID)
    if v.is_infinite() or (v != 0 and abs(v.adjusted()) > 9998):
        raise CalcError(OVERFLOW)
    return v


def _clean(v: Decimal) -> Decimal:
    """Round away the noise of float functions: sin(180) is 0, not 1.2e-16."""
    if v != 0 and abs(v) < Decimal("1e-32"):
        return Decimal(0)
    return v


def format_decimal(v: Decimal, digits: int = 16, force_exp: bool = False) -> str:
    """Windows 7 style: up to `digits` significant digits, '1.e+16' style when too big or small."""
    if v == 0:
        return "0" if not force_exp else "0.e+0"
    with localcontext() as ctx:
        ctx.prec = digits
        q = +v                                   # rounded to `digits` significant digits
    sign = "-" if q < 0 else ""
    q = abs(q)
    e = q.adjusted()
    tup = q.as_tuple()
    sig = "".join(map(str, tup.digits)).rstrip("0") or "0"
    if not force_exp and 0 <= e < digits:
        whole = sig[: e + 1].ljust(e + 1, "0")
        frac = sig[e + 1:]
        return sign + whole + ("." + frac if frac else "")
    if not force_exp and e < 0 and (-e - 1) + len(sig) <= digits:
        return sign + "0." + "0" * (-e - 1) + sig
    if not force_exp and -6 <= e < 0:
        # 0.0697564737441253... : fewer significant digits so the zeros fit, like Windows
        zeros = -e - 1
        with localcontext() as ctx:
            ctx.prec = digits - zeros
            r = +abs(v)
        sig2 = "".join(map(str, r.as_tuple().digits)).rstrip("0") or "0"
        if r.adjusted() == e:
            return sign + "0." + "0" * zeros + sig2
    mant = sig[0] + "." + sig[1:]
    return f"{sign}{mant}e{'+' if e >= 0 else '-'}{abs(e)}"


@dataclass
class Engine:
    mode: str = "standard"           # standard, scientific, programmer
    angle: str = "deg"               # deg, rad, grad
    base: int = 10                   # programmer: 16, 10, 8, 2
    word: int = 64                   # programmer: 64, 32, 16, 8
    inv: bool = False
    fe: bool = False                 # scientific: always show exponential notation
    memory: Decimal | int | None = None
    history: list = field(default_factory=list)

    def __post_init__(self):
        self.clear()

    # ---- state ------------------------------------------------------------------------------
    def clear(self):
        """C"""
        self.entry: str | None = None    # what is being typed
        self.value = self._zero()
        self.error: str | None = None
        self.expr: list[str] = []        # the history line above the number
        self.unary_text: str | None = None
        self.acc = None                  # standard: the first number and its operator
        self.op: str | None = None
        self.last_op = None              # standard: (op, operand) for repeated =
        self.vals: list = []             # scientific/programmer: number and operator stacks
        self.ops: list[str] = []
        self.parens = 0
        self.paren_pos: list[int] = []   # where each open ( is in self.expr
        self.last_key_binary = False
        self.just_evaluated = False

    def _zero(self):
        return 0 if self.mode == "programmer" else Decimal(0)

    @property
    def max_digits(self) -> int:
        return 16 if self.mode == "standard" else 32

    def set_mode(self, mode: str):
        cur = self.current()
        if mode == self.mode:
            return
        old = self.mode
        self.mode = mode
        keep = self.memory
        self.clear()
        if mode == "programmer":
            try:
                self.value = to_signed(int(cur), self.word) if not isinstance(cur, int) else cur
            except (ValueError, OverflowError, InvalidOperation):
                self.value = 0
            self.memory = to_signed(int(keep), self.word) if keep is not None else None
        else:
            self.value = Decimal(cur) if old == "programmer" else cur
            self.memory = Decimal(keep) if keep is not None and old == "programmer" else keep

    def set_base(self, base: int):
        cur = self.current()
        self.entry = None
        self.value = cur
        self.base = base

    def set_word(self, bits: int):
        cur = self.current()
        self.word = bits
        self.entry = None
        self.value = to_signed(cur, bits)
        self.vals = [to_signed(v, bits) for v in self.vals]

    # ---- numbers ----------------------------------------------------------------------------
    def current(self):
        if self.entry is not None:
            return self.parse_entry()
        return self.value

    def parse_entry(self):
        e = self.entry or "0"
        if self.mode == "programmer":
            neg = e.startswith("-")
            v = int(e.lstrip("-") or "0", self.base)
            return to_signed(-v if neg else v, self.word)
        if e.endswith(("e+", "e-")):
            e = e[:-2]
        try:
            return Decimal(e.rstrip(".") or "0")
        except InvalidOperation:
            return Decimal(0)

    def display(self) -> str:
        """The number as typed or as a result (decimal point '.', no grouping)."""
        if self.error:
            return self.error
        if self.entry is not None:
            if self.mode == "programmer" and self.base != 10:
                return self.format_value(self.parse_entry())
            return self.entry or "0"
        return self.format_value(self.value)

    def format_value(self, v) -> str:
        if self.mode == "programmer":
            if self.base == 10:
                return str(to_signed(v, self.word))
            u = v & ((1 << self.word) - 1)
            return {16: f"{u:X}", 8: f"{u:o}", 2: f"{u:b}"}[self.base]
        return format_decimal(v, self.max_digits, self.fe and self.mode == "scientific")

    def expression(self) -> str:
        parts = list(self.expr)
        if self.unary_text:
            parts.append(self.unary_text)
        return " ".join(parts)

    def _text(self, v) -> str:
        return self.format_value(v)

    # ---- keys -------------------------------------------------------------------------------
    def _start_entry(self):
        if self.error:
            self.clear()
        if self.entry is None:
            if self.just_evaluated and self.mode == "standard":
                self.acc = None
                self.op = None
            self.entry = ""
            self.unary_text = None
        self.just_evaluated = False
        self.last_key_binary = False

    def digit(self, d: str):
        """0-9, A-F (programmer) or '.'"""
        d = d.upper()
        if self.mode == "programmer":
            if d == "." or int(d, 16) >= self.base:
                return
            self._start_entry()
            new = ("" if self.entry in ("", "0") else self.entry) + d
            neg = new.startswith("-")
            if int(new.lstrip("-") or "0", self.base) >= (1 << self.word) or (
                    self.base == 10 and int(new.lstrip("-")) > (1 << (self.word - 1)) - (0 if neg else 1)):
                return
            self.entry = new
            return
        if d not in "0123456789.":
            return
        self._start_entry()
        e = self.entry
        if "e" in e:                     # typing the exponent after Exp
            if d == ".":
                return
            mant, exp = e.split("e")
            sign, digits = exp[0], exp[1:]
            digits = (digits.lstrip("0") + d) if digits != "0" else d
            if len(digits) > 4:
                return
            self.entry = f"{mant}e{sign}{digits}"
            return
        if d == ".":
            if "." not in e:
                self.entry = (e or "0") + "."
            return
        if sum(c.isdigit() for c in e.lstrip("-0.")) >= self.max_digits and e not in ("", "0"):
            return
        if e in ("", "0"):
            self.entry = d
        elif e == "-0":
            self.entry = "-" + d
        else:
            self.entry = e + d

    def exp(self):
        """Exp: 1.5 Exp 3 = 1.5e+3"""
        if self.mode != "scientific" or self.error:
            return
        if self.entry is None:
            self._start_entry()
            self.entry = self.format_value(self.value) if self.value != 0 else "0"
        if "e" not in self.entry:
            self.entry = self.entry.rstrip(".") + "e+0"

    def backspace(self):
        if self.error:
            self.clear()
            return
        if self.entry is None:
            return
        e = self.entry[:-1]
        if e.endswith(("e+", "e-")) or e.endswith("e"):
            e = e.split("e")[0]
        self.entry = e if e not in ("", "-") else "0"

    def clear_entry(self):
        """CE"""
        if self.error:
            self.clear()
            return
        self.entry = None
        self.value = self._zero()
        self.unary_text = None
        self.last_key_binary = False

    def negate(self):
        if self.error:
            return
        if self.entry is not None and self.entry not in ("", "0"):
            e = self.entry
            if "e" in e:
                mant, exp = e.split("e")
                self.entry = f"{mant}e{'-' if exp[0] == '+' else '+'}{exp[1:]}"
            elif self.mode == "programmer" and self.base != 10:
                v = self.parse_entry()
                self.entry = None
                self.value = to_signed(-v, self.word)
            else:
                self.entry = e[1:] if e.startswith("-") else "-" + e
            return
        self.unary("negate")

    # ---- calculating ------------------------------------------------------------------------
    def _binary(self, op: str, a, b):
        if self.mode == "programmer":
            w = self.word
            if op == "+":
                return to_signed(a + b, w)
            if op == "-":
                return to_signed(a - b, w)
            if op == "*":
                return to_signed(a * b, w)
            if op in ("/", "mod"):
                if b == 0:
                    raise CalcError(DIV0)
                q = abs(a) // abs(b)
                q = q if (a >= 0) == (b >= 0) else -q
                return to_signed(q if op == "/" else a - b * q, w)
            if op == "and":
                return to_signed(a & b, w)
            if op == "or":
                return to_signed(a | b, w)
            if op == "xor":
                return to_signed(a ^ b, w)
            if op == "lsh":
                return to_signed(a << (b & 0xFF), w) if b >= 0 else to_signed(a >> -b, w)
            if op == "rsh":
                return to_signed(a >> (b & 0xFF), w) if b >= 0 else to_signed(a << -b, w)
            raise CalcError(INVALID)
        try:
            if op == "+":
                return _check(a + b)
            if op == "-":
                return _check(a - b)
            if op == "*":
                return _check(a * b)
            if op == "/":
                if b == 0:
                    raise CalcError(UNDEFINED if a == 0 else DIV0)
                return _check(a / b)
            if op == "mod":
                if b == 0:
                    raise CalcError(DIV0)
                return _check(a % b)
            if op == "pow":
                if a == 0 and b < 0:
                    raise CalcError(DIV0)
                if a < 0 and b != b.to_integral_value():
                    # odd roots of negative numbers: (-8)^(1/3) = -2
                    inv = Decimal(1) / b
                    if inv == inv.to_integral_value() and int(inv) % 2 == 1:
                        return _check(-((-a) ** b))
                    raise CalcError(INVALID)
                return _check(a ** b)
            if op == "root":
                if b == 0:
                    raise CalcError(INVALID)
                return self._binary("pow", a, Decimal(1) / b)
        except (InvalidOperation, Overflow):
            raise CalcError(OVERFLOW) from None
        except DivisionByZero:
            raise CalcError(DIV0) from None
        raise CalcError(INVALID)

    def _to_rad(self, x: Decimal) -> Decimal:
        if self.angle == "deg":
            return x * PI / 180
        if self.angle == "grad":
            return x * PI / 200
        return x

    def _from_rad(self, r: float) -> Decimal:
        if self.angle == "deg":
            return _float15(math.degrees(r))
        if self.angle == "grad":
            return _float15(r * 200 / math.pi)
        return _float15(r)

    def _unary_value(self, fn: str, x):
        if self.mode == "programmer":
            w = self.word
            if fn == "negate":
                return to_signed(-x, w)
            if fn == "not":
                return to_signed(~x, w)
            u = x & ((1 << w) - 1)
            if fn == "rol":
                return to_signed(((u << 1) | (u >> (w - 1))) & ((1 << w) - 1), w)
            if fn == "ror":
                return to_signed(((u >> 1) | ((u & 1) << (w - 1))), w)
            raise CalcError(INVALID)
        try:
            if fn == "negate":
                return -x
            if fn == "sqrt":
                if x < 0:
                    raise CalcError(INVALID)
                return x.sqrt()
            if fn == "recip":
                if x == 0:
                    raise CalcError(DIV0)
                return _check(Decimal(1) / x)
            if fn == "sqr":
                return _check(x * x)
            if fn == "cube":
                return _check(x * x * x)
            if fn == "cuberoot":
                r = abs(x) ** (Decimal(1) / Decimal(3)) if x != 0 else Decimal(0)
                r = r.quantize(Decimal(1)) if abs(r.quantize(Decimal(1)) ** 3) == abs(x) else r
                return -r if x < 0 else r
            if fn == "ln":
                if x <= 0:
                    raise CalcError(INVALID)
                return x.ln()
            if fn == "log":
                if x <= 0:
                    raise CalcError(INVALID)
                return x.log10()
            if fn == "exp":
                return _check(x.exp())
            if fn == "pow10":
                return _check(Decimal(10) ** x)
            if fn in ("sin", "cos", "tan"):
                r = self._to_rad(x)
                # exact values at the multiples of 90 degrees
                if self.angle in ("deg", "grad"):
                    quarter = Decimal(90 if self.angle == "deg" else 100)
                    k = x / quarter
                    if k == k.to_integral_value():
                        k = int(k) % 4
                        table = {"sin": [0, 1, 0, -1], "cos": [1, 0, -1, 0]}
                        if fn == "tan":
                            if k % 2:
                                raise CalcError(INVALID)
                            return Decimal(0)
                        return Decimal(table[fn][k])
                if fn == "sin":
                    return _clean(_dsin(r))
                if fn == "cos":
                    return _clean(_dcos(r))
                c = _dcos(r)
                if abs(c) < Decimal("1e-35"):
                    raise CalcError(INVALID)
                return _clean(_dsin(r) / c)
            if fn in ("asin", "acos"):
                if abs(x) > 1:
                    raise CalcError(INVALID)
                return _clean(self._from_rad((math.asin if fn == "asin" else math.acos)(float(x))))
            if fn == "atan":
                return _clean(self._from_rad(math.atan(float(x))))
            if fn in ("sinh", "cosh", "tanh"):
                ex = _check(x.exp())
                emx = Decimal(1) / ex
                if fn == "sinh":
                    return _clean((ex - emx) / 2)
                if fn == "cosh":
                    return (ex + emx) / 2
                return _clean((ex - emx) / (ex + emx))
            if fn == "asinh":
                return _float15(math.asinh(float(x)))
            if fn == "acosh":
                if x < 1:
                    raise CalcError(INVALID)
                return _float15(math.acosh(float(x)))
            if fn == "atanh":
                if abs(x) >= 1:
                    raise CalcError(INVALID)
                return _float15(math.atanh(float(x)))
            if fn == "fact":
                if x == x.to_integral_value():
                    n = int(x)
                    if n < 0:
                        raise CalcError(INVALID)
                    if n > 3248:
                        raise CalcError(OVERFLOW)
                    return _check(Decimal(math.factorial(n)))
                if x < -1 and x == x.to_integral_value():
                    raise CalcError(INVALID)
                return _float15(math.gamma(float(x) + 1))
            if fn == "int":
                return x.to_integral_value(rounding="ROUND_DOWN")
            if fn == "frac":
                return x - x.to_integral_value(rounding="ROUND_DOWN")
            if fn == "dms":
                neg = x < 0
                x = abs(x)
                d = x.to_integral_value(rounding="ROUND_DOWN")
                m_full = (x - d) * 60
                m = m_full.to_integral_value(rounding="ROUND_DOWN")
                s = (m_full - m) * 60
                r = d + m / 100 + s / 10000
                return -r if neg else r
            if fn == "deg":
                neg = x < 0
                x = abs(x)
                d = x.to_integral_value(rounding="ROUND_DOWN")
                rest = (x - d) * 100
                m = rest.to_integral_value(rounding="ROUND_DOWN")
                s = (rest - m) * 100
                r = d + m / 60 + s / 3600
                return -r if neg else r
        except (InvalidOperation, Overflow, OverflowError, ValueError):
            raise CalcError(OVERFLOW) from None
        except DivisionByZero:
            raise CalcError(DIV0) from None
        raise CalcError(INVALID)

    UNARY_NAMES = {"negate": "negate", "sqrt": "sqrt", "recip": "reciproc", "sqr": "sqr", "cube": "cube",
                   "cuberoot": "cuberoot", "ln": "ln", "log": "log", "exp": "powe", "pow10": "powten",
                   "sin": "sin", "cos": "cos", "tan": "tan", "asin": "asin", "acos": "acos", "atan": "atan",
                   "sinh": "sinh", "cosh": "cosh", "tanh": "tanh", "asinh": "asinh", "acosh": "acosh",
                   "atanh": "atanh", "fact": "fact", "int": "Int", "frac": "frac", "dms": "dms", "deg": "degrees",
                   "not": "Not", "rol": "RoL", "ror": "RoR"}

    def unary(self, fn: str):
        if self.error:
            return
        x = self.current()
        try:
            r = self._unary_value(fn, x)
        except CalcError as e:
            self._fail(str(e))
            return
        name = self.UNARY_NAMES.get(fn, fn)
        if fn in ("sin", "cos", "tan") and self.mode == "scientific":
            name += {"deg": "₀", "rad": "ᵣ", "grad": "g"}.get(self.angle, "")
        inner = self.unary_text or self._text(x)
        self.unary_text = f"{name}({inner})"
        self.entry = None
        self.value = r
        self.last_key_binary = False
        self.just_evaluated = False

    def constant(self, name: str):
        """pi"""
        if self.mode == "programmer":
            return
        if self.error:
            self.clear()
        self.entry = None
        self.unary_text = None
        self.value = PI if name == "pi" else E
        self.last_key_binary = False
        self.just_evaluated = False

    def percent(self):
        if self.error or self.mode == "programmer":
            return
        x = self.current()
        base = self.acc if self.mode == "standard" else (self.vals[-1] if self.vals and self.ops else None)
        r = (base * x / 100) if (base is not None and (self.op or self.ops)) else Decimal(0)
        self.entry = None
        self.value = r
        self.unary_text = self._text(r)
        self.last_key_binary = False

    def _fail(self, msg: str):
        self.error = msg
        self.entry = None

    def binary(self, op: str):
        if self.error:
            return
        sym = BINARY[op][0]
        if self.mode == "standard":
            if self.last_key_binary and self.op is not None:
                self.op = op
                if self.expr:
                    self.expr[-1] = sym
                return
            cur = self.current()
            text = self.unary_text or self._text(cur)
            if self.op is not None and self.acc is not None:
                try:
                    res = self._binary(self.op, self.acc, cur)
                except CalcError as e:
                    self._fail(str(e))
                    return
            else:
                res = cur
                self.expr = []
            self.acc = res
            self.value = res
            self.op = op
            self.expr += [text, sym]
        else:
            if self.last_key_binary and self.ops and self.ops[-1] != "(":
                self.ops.pop()
                if self.expr:
                    self.expr.pop()
            else:
                self._push_operand()
            prec, right = BINARY[op][1], BINARY[op][2]
            try:
                while self.ops and self.ops[-1] != "(":
                    top = self.ops[-1]
                    tprec = BINARY[top][1]
                    if tprec > prec or (tprec == prec and not right):
                        self._reduce()
                    else:
                        break
            except CalcError as e:
                self._fail(str(e))
                return
            self.ops.append(op)
            self.expr.append(sym)
            self.value = self.vals[-1]
        self.entry = None
        self.unary_text = None
        self.last_key_binary = True
        self.just_evaluated = False

    def _push_operand(self):
        cur = self.current()
        if self.just_evaluated:
            self.expr = []
        self.expr.append(self.unary_text or self._text(cur))
        self.vals.append(cur)

    def _reduce(self):
        op = self.ops.pop()
        b = self.vals.pop()
        a = self.vals.pop()
        self.vals.append(self._binary(op, a, b))

    def open_paren(self):
        if self.error or self.mode == "standard":
            return
        if self.just_evaluated:
            self.expr = []
            self.vals = []
            self.ops = []
        self.ops.append("(")
        self.paren_pos.append(len(self.expr))
        self.expr.append("(")
        self.parens += 1
        self.entry = None
        self.value = self._zero()
        self.unary_text = None
        self.last_key_binary = False
        self.just_evaluated = False

    def close_paren(self):
        if self.error or self.mode == "standard" or self.parens == 0:
            return
        self._push_operand()
        try:
            while self.ops and self.ops[-1] != "(":
                self._reduce()
        except CalcError as e:
            self._fail(str(e))
            return
        if self.ops:
            self.ops.pop()
        self.parens -= 1
        # the group becomes one operand: "(2 + 3)", which an operator or a function then uses
        start = self.paren_pos.pop() if self.paren_pos else 0
        group = self.expr[start:]
        del self.expr[start:]
        self.value = self.vals.pop()
        self.entry = None
        self.unary_text = "(" + " ".join(group[1:]) + ")"
        self.last_key_binary = False

    def equals(self):
        if self.error:
            return
        if self.mode == "standard":
            cur = self.current()
            try:
                if self.op is not None:
                    operand = cur
                    text = self.expression() if self.unary_text else " ".join(self.expr + [self._text(cur)])
                    res = self._binary(self.op, self.acc, operand)
                    self.last_op = (self.op, operand)
                elif self.last_op is not None:
                    op, operand = self.last_op
                    text = f"{self._text(cur)} {BINARY[op][0]} {self._text(operand)}"
                    res = self._binary(op, cur, operand)
                else:
                    text, res = self.unary_text or self._text(cur), cur
            except CalcError as e:
                self._fail(str(e))
                return
            self.acc = None
            self.op = None
        else:
            cur = self.current()
            self._push_operand()
            try:
                while self.ops:
                    if self.ops[-1] == "(":
                        self.ops.pop()
                        continue
                    self._reduce()
            except CalcError as e:
                self._fail(str(e))
                return
            res = self.vals.pop() if self.vals else cur
            text = " ".join(self.expr)
            self.vals = []
            self.parens = 0
            self.paren_pos = []
        self.history.append((text, self._text(res)))
        del self.history[:-50]
        self.value = res
        self.entry = None
        self.expr = []
        self.unary_text = None
        self.last_key_binary = False
        self.just_evaluated = True

    # ---- memory -----------------------------------------------------------------------------
    def mem(self, what: str):
        if self.error and what != "mc":
            return
        cur_before = self.current()
        if what == "mc":
            self.memory = None
        elif what == "ms":
            self.memory = self.current()
        elif what == "mr":
            if self.memory is not None:
                self.entry = None
                self.value = self.memory
                self.unary_text = None
                self.last_key_binary = False
        elif what in ("m+", "m-"):
            cur = self.current()
            m = self.memory if self.memory is not None else self._zero()
            if self.mode == "programmer":
                self.memory = to_signed(m + cur if what == "m+" else m - cur, self.word)
            else:
                self.memory = m + cur if what == "m+" else m - cur
        if what in ("ms", "m+", "m-"):
            self.value = cur_before
            self.entry = None
            self.last_key_binary = False

    def paste(self, text: str) -> bool:
        t = text.strip().replace(" ", "").replace(" ", "")
        if self.mode == "programmer":
            try:
                v = int(t, self.base)
            except ValueError:
                return False
            self.entry = None
            self.value = to_signed(v, self.word)
            return True
        try:
            v = Decimal(t)
        except InvalidOperation:
            return False
        self.error = None
        self.entry = None
        self.value = v
        self.unary_text = None
        return True
