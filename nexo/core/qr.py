"""Gerador de códigos QR (modo byte, correção de erros M, versões 1–10) — para abrir o painel no telemóvel
sem escrever o endereço. Segue a norma ISO/IEC 18004 (mesma estrutura do gerador de referência de Nayuki).
Chega para ligações até ~210 caracteres."""
from __future__ import annotations

# correção de erros M: códigos de correção por bloco e número de blocos (índice = versão)
_ECC_PER_BLOCK = (-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26)
_NUM_BLOCKS = (-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5)
_ECL_BITS = 0          # M
MAX_VERSION = 10


def _raw_modules(ver: int) -> int:
    r = (16 * ver + 128) * ver + 64
    if ver >= 2:
        n = ver // 7 + 2
        r -= (25 * n - 10) * n - 55
        if ver >= 7:
            r -= 36
    return r


def _data_codewords(ver: int) -> int:
    return _raw_modules(ver) // 8 - _ECC_PER_BLOCK[ver] * _NUM_BLOCKS[ver]


def _gf_mul(x: int, y: int) -> int:
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree: int) -> list[int]:
    res = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            res[j] = _gf_mul(res[j], root)
            if j + 1 < degree:
                res[j] ^= res[j + 1]
        root = _gf_mul(root, 2)
    return res


def _rs_remainder(data: list[int], div: list[int]) -> list[int]:
    res = [0] * len(div)
    for b in data:
        f = b ^ res.pop(0)
        res.append(0)
        for i, c in enumerate(div):
            res[i] ^= _gf_mul(c, f)
    return res


def _codewords(text: bytes) -> tuple[int, list[int]]:
    for ver in range(1, MAX_VERSION + 1):
        cc_bits = 8 if ver <= 9 else 16
        cap = _data_codewords(ver) * 8
        if 4 + cc_bits + len(text) * 8 <= cap:
            break
    else:
        raise ValueError("texto demasiado comprido para o código QR")
    bits: list[int] = []

    def put(val: int, n: int):
        bits.extend((val >> i) & 1 for i in reversed(range(n)))
    put(0b0100, 4)
    put(len(text), cc_bits)
    for b in text:
        put(b, 8)
    put(0, min(4, cap - len(bits)))
    put(0, (-len(bits)) % 8)
    pad = 0xEC
    while len(bits) < cap:
        put(pad, 8)
        pad ^= 0xEC ^ 0x11
    data = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    # blocos + correção de erros, intercalados
    nblocks, ecclen = _NUM_BLOCKS[ver], _ECC_PER_BLOCK[ver]
    raw = _raw_modules(ver) // 8
    nshort = nblocks - raw % nblocks
    shortlen = raw // nblocks
    div = _rs_divisor(ecclen)
    blocks, k = [], 0
    for i in range(nblocks):
        dat = data[k:k + shortlen - ecclen + (0 if i < nshort else 1)]
        k += len(dat)
        ecc = _rs_remainder(dat, div)
        if i < nshort:
            dat = dat + [0]
        blocks.append(dat + ecc)
    out = []
    for i in range(len(blocks[0])):
        for j, blk in enumerate(blocks):
            if i != shortlen - ecclen or j >= nshort:
                out.append(blk[i])
    return ver, out


def encode(text: str, mask: int | None = None) -> list[list[bool]]:
    """Matriz de módulos (True = escuro), sem a margem branca."""
    ver, cw = _codewords(text.encode("utf-8"))
    size = ver * 4 + 17
    mod = [[False] * size for _ in range(size)]
    fn = [[False] * size for _ in range(size)]

    def setf(x, y, dark):
        mod[y][x] = dark
        fn[y][x] = True
    for i in range(size):                              # linhas de sincronização
        setf(6, i, i % 2 == 0)
        setf(i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):   # padrões de localização
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < size and 0 <= y < size:
                    setf(x, y, max(abs(dx), abs(dy)) not in (2, 4))
    if ver > 1:                                        # padrões de alinhamento
        n = ver // 7 + 2
        step = (ver * 8 + n * 3 + 5) // (n * 4 - 4) * 2
        pos = [6] + [size - 7 - i * step for i in range(n - 1)][::-1]
        for i, ax in enumerate(pos):
            for j, ay in enumerate(pos):
                if (i, j) in ((0, 0), (0, n - 1), (n - 1, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        setf(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)

    def draw_format(m: int):
        data = _ECL_BITS << 3 | m
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        b = lambda i: (bits >> i) & 1 != 0  # noqa: E731
        for i in range(6):
            setf(8, i, b(i))
        setf(8, 7, b(6))
        setf(8, 8, b(7))
        setf(7, 8, b(8))
        for i in range(9, 15):
            setf(14 - i, 8, b(i))
        for i in range(8):
            setf(size - 1 - i, 8, b(i))
        for i in range(8, 15):
            setf(8, size - 15 + i, b(i))
        setf(8, size - 8, True)
    draw_format(0)                                     # reserva as posições
    if ver >= 7:
        rem = ver
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        bits = ver << 12 | rem
        for i in range(18):
            bit = (bits >> i) & 1 != 0
            a, c = size - 11 + i % 3, i // 3
            setf(a, c, bit)
            setf(c, a, bit)
    # dados em ziguezague
    i, right = 0, size - 1
    total = len(cw) * 8
    while right >= 1:
        if right == 6:
            right = 5
        for vert in range(size):
            for j in range(2):
                x = right - j
                up = ((right + 1) & 2) == 0
                y = size - 1 - vert if up else vert
                if not fn[y][x] and i < total:
                    mod[y][x] = (cw[i >> 3] >> (7 - (i & 7))) & 1 != 0
                    i += 1
        right -= 2

    masks = {0: lambda x, y: (x + y) % 2 == 0, 1: lambda x, y: y % 2 == 0, 2: lambda x, y: x % 3 == 0,
             3: lambda x, y: (x + y) % 3 == 0, 4: lambda x, y: (x // 3 + y // 2) % 2 == 0,
             5: lambda x, y: x * y % 2 + x * y % 3 == 0, 6: lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
             7: lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0}

    def apply(m):
        f = masks[m]
        for y in range(size):
            for x in range(size):
                if not fn[y][x] and f(x, y):
                    mod[y][x] = not mod[y][x]

    def penalty() -> int:
        p = 0
        for grid in (mod, [list(c) for c in zip(*mod)]):
            for row in grid:
                run, prev = 0, None
                for v in row:
                    if v == prev:
                        run += 1
                    else:
                        if run >= 5:
                            p += run - 2
                        run, prev = 1, v
                if run >= 5:
                    p += run - 2
                s = "".join("1" if v else "0" for v in row)
                p += 40 * (s.count("1011101" + "0000") + s.count("0000" + "1011101"))
        for y in range(size - 1):
            for x in range(size - 1):
                if mod[y][x] == mod[y][x + 1] == mod[y + 1][x] == mod[y + 1][x + 1]:
                    p += 3
        dark = sum(v for row in mod for v in row)
        p += abs(dark * 20 - size * size * 10) // (size * size) * 10
        return p

    if mask is None:
        best = None
        for m in range(8):
            apply(m)
            draw_format(m)
            sc = penalty()
            if best is None or sc < best[0]:
                best = (sc, m)
            apply(m)                                   # desfaz (XOR)
        mask = best[1]
    apply(mask)
    draw_format(mask)
    return mod


def to_pbm(matrix: list[list[bool]], border: int = 4, scale: int = 4) -> bytes:
    """Imagem PBM (para testes e diagnósticos)."""
    n = len(matrix) + 2 * border
    rows = []
    for y in range(-border, len(matrix) + border):
        row = []
        for x in range(-border, len(matrix) + border):
            dark = 0 <= y < len(matrix) and 0 <= x < len(matrix) and matrix[y][x]
            row += ["1" if dark else "0"] * scale
        rows += [" ".join(row)] * scale
    return f"P1\n{n * scale} {n * scale}\n".encode() + "\n".join(rows).encode() + b"\n"
