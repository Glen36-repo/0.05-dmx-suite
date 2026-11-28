"""Small QR code encoder for the phone link on the Setup page (no extra dependency).

Byte mode, error correction level M, versions 1-10 (up to 213 bytes: plenty for a LAN address),
the mask with the lowest penalty, as in ISO/IEC 18004. `matrix(text)` gives rows of booleans
(True = dark); `svg(text)` draws it with a 4-module quiet zone.
"""

from __future__ import annotations

# level M: (error correction codewords per block, [(blocks, data codewords per block), ...])
_EC_M = {
    1: (10, [(1, 16)]), 2: (16, [(1, 28)]), 3: (26, [(1, 44)]), 4: (18, [(2, 32)]),
    5: (24, [(2, 43)]), 6: (16, [(4, 27)]), 7: (18, [(4, 31)]), 8: (22, [(2, 38), (2, 39)]),
    9: (22, [(3, 36), (2, 37)]), 10: (26, [(4, 43), (1, 44)]),
}
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38],
          8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50]}
_LEVEL_M = 0  # format bits for M


# ---------------------------------------------------------------- Reed-Solomon over GF(256)

_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _mul(a: int, b: int) -> int:
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _generator(degree: int) -> list[int]:
    g = [1]
    for i in range(degree):
        g = [a ^ _mul(b, _EXP[i]) for a, b in zip([*g, 0], [0, *g], strict=True)]
    return g  # highest power first


def rs_remainder(data: list[int], degree: int) -> list[int]:
    g = _generator(degree)
    rem = [0] * degree
    for d in data:
        factor = d ^ rem[0]
        rem = rem[1:] + [0]
        for i in range(degree):
            rem[i] ^= _mul(g[i + 1], factor)
    return rem


# ---------------------------------------------------------------- codewords


def _capacity(version: int) -> int:
    return sum(n * k for n, k in _EC_M[version][1])


def _version_for(n: int) -> int:
    for v in range(1, 11):
        count_bits = 8 if v < 10 else 16
        if 4 + count_bits + 8 * n <= 8 * _capacity(v):
            return v
    raise ValueError("too long for a QR code here (213 bytes at most)")


def codewords(data: bytes) -> tuple[int, list[int]]:
    """Version and the final interleaved codeword sequence (data then error correction)."""
    v = _version_for(len(data))
    bits: list[int] = []

    def put(value: int, n: int) -> None:
        bits.extend((value >> i) & 1 for i in range(n - 1, -1, -1))

    put(0b0100, 4)
    put(len(data), 8 if v < 10 else 16)
    for b in data:
        put(b, 8)
    cap = 8 * _capacity(v)
    put(0, min(4, cap - len(bits)))
    put(0, -len(bits) % 8)
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(words) < cap // 8:
        words.append(pad)
        pad ^= 0xEC ^ 0x11
    ec_len, groups = _EC_M[v]
    blocks: list[list[int]] = []
    i = 0
    for n, k in groups:
        for _ in range(n):
            blocks.append(words[i:i + k])
            i += k
    ecs = [rs_remainder(b, ec_len) for b in blocks]
    out = [b[j] for j in range(max(map(len, blocks))) for b in blocks if j < len(b)]
    out += [e[j] for j in range(ec_len) for e in ecs]
    return v, out


# ---------------------------------------------------------------- matrix


def _bch(value: int, poly: int, poly_bits: int) -> int:
    v = value << (poly_bits - 1)
    for i in range(v.bit_length() - poly_bits, -1, -1):
        if v >> (i + poly_bits - 1) & 1:
            v ^= poly << i
    return (value << (poly_bits - 1)) | v


def format_bits(mask: int) -> int:
    return _bch((_LEVEL_M << 3) | mask, 0b10100110111, 11) ^ 0b101010000010010


def version_bits(version: int) -> int:
    return _bch(version, 0b1111100100101, 13)


_MASKS = [
    lambda r, c: (r + c) % 2 == 0, lambda r, c: r % 2 == 0, lambda r, c: c % 3 == 0,
    lambda r, c: (r + c) % 3 == 0, lambda r, c: (r // 2 + c // 3) % 2 == 0,
    lambda r, c: r * c % 2 + r * c % 3 == 0, lambda r, c: (r * c % 2 + r * c % 3) % 2 == 0,
    lambda r, c: ((r + c) % 2 + r * c % 3) % 2 == 0,
]


class _Grid:
    def __init__(self, version: int) -> None:
        self.v = version
        self.n = 17 + 4 * version
        self.dark = [[False] * self.n for _ in range(self.n)]
        self.fixed = [[False] * self.n for _ in range(self.n)]
        self._functions()

    def set(self, r: int, c: int, dark: bool) -> None:
        self.dark[r][c] = dark
        self.fixed[r][c] = True

    def _functions(self) -> None:
        n = self.n
        for i in range(n):  # timing patterns
            self.set(6, i, i % 2 == 0)
            self.set(i, 6, i % 2 == 0)
        for r0, c0 in ((0, 0), (0, n - 7), (n - 7, 0)):  # finders with separators
            for dr in range(-1, 8):
                for dc in range(-1, 8):
                    r, c = r0 + dr, c0 + dc
                    if 0 <= r < n and 0 <= c < n:
                        d = max(abs(dr - 3), abs(dc - 3))
                        self.set(r, c, d not in (2, 4))
        pos = _ALIGN[self.v]
        for r in pos:
            for c in pos:
                if (r, c) in ((6, 6), (6, pos[-1]), (pos[-1], 6)):
                    continue  # under a finder
                for dr in range(-2, 3):
                    for dc in range(-2, 3):
                        self.set(r + dr, c + dc, max(abs(dr), abs(dc)) != 1)
        self.format(0)  # reserve, real bits written after masking
        if self.v >= 7:
            bits = version_bits(self.v)
            for i in range(18):
                b = (bits >> i) & 1 == 1
                a, c = n - 11 + i % 3, i // 3
                self.set(a, c, b)
                self.set(c, a, b)

    def format(self, mask: int) -> None:
        n = self.n
        bits = format_bits(mask)
        b = [(bits >> i) & 1 == 1 for i in range(15)]
        for i in range(6):
            self.set(i, 8, b[i])
        self.set(7, 8, b[6])
        self.set(8, 8, b[7])
        self.set(8, 7, b[8])
        for i in range(9, 15):
            self.set(8, 14 - i, b[i])
        for i in range(8):
            self.set(8, n - 1 - i, b[i])
        for i in range(8, 15):
            self.set(n - 15 + i, 8, b[i])
        self.set(n - 8, 8, True)  # always dark

    def data_cells(self) -> list[tuple[int, int]]:
        """Data module positions in placement order (two-column zigzag from the bottom right)."""
        n, out = self.n, []
        right = n - 1
        while right >= 1:
            if right == 6:
                right = 5
            upward = ((right + 1) & 2) == 0
            for vert in range(n):
                r = n - 1 - vert if upward else vert
                for c in (right, right - 1):
                    if not self.fixed[r][c]:
                        out.append((r, c))
            right -= 2
        return out


def _penalty(m: list[list[bool]]) -> int:
    n, score = len(m), 0
    for lines in (m, [list(col) for col in zip(*m, strict=True)]):
        for line in lines:
            run, prev = 0, None
            for x in line:
                if x == prev:
                    run += 1
                else:
                    if run >= 5:
                        score += run - 2
                    run, prev = 1, x
            if run >= 5:
                score += run - 2
            s = "".join("1" if x else "0" for x in line)
            for pat in ("10111010000", "00001011101"):
                start = s.find(pat)
                while start != -1:
                    score += 40
                    start = s.find(pat, start + 1)
    for r in range(n - 1):
        for c in range(n - 1):
            if m[r][c] == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                score += 3
    dark = sum(map(sum, m))
    score += abs(dark * 20 - n * n * 10) // (n * n) * 10
    return score


def matrix(text: str) -> list[list[bool]]:
    v, words = codewords(text.encode("utf-8"))
    best: tuple[int, list[list[bool]]] | None = None
    for mask in range(8):
        g = _Grid(v)
        cells = g.data_cells()
        bits = [(w >> (7 - i)) & 1 for w in words for i in range(8)]
        bits += [0] * (len(cells) - len(bits))  # remainder bits
        for (r, c), bit in zip(cells, bits, strict=True):
            g.dark[r][c] = (bit == 1) != _MASKS[mask](r, c)
        g.format(mask)
        p = _penalty(g.dark)
        if best is None or p < best[0]:
            best = (p, g.dark)
    assert best is not None
    return best[1]


def svg(text: str, module: int = 6) -> str:
    m = matrix(text)
    n = len(m) + 8
    path = "".join(f"M{c + 4},{r + 4}h1v1h-1z" for r, row in enumerate(m) for c, d in enumerate(row) if d)
    px = n * module
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" width="{px}" height="{px}" '
            f'shape-rendering="crispEdges"><rect width="{n}" height="{n}" fill="#fff"/>'
            f'<path d="{path}" fill="#000"/></svg>')
