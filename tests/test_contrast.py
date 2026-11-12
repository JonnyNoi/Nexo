"""Contraste das cores dos temas (WCAG 2.1): texto ≥ 4,5:1, elementos gráficos/texto grande ≥ 3:1."""
import unittest

try:
    from nexo.ui import theme
except ImportError:  # pragma: no cover - sem PySide6
    theme = None


def _lum(h: str) -> float:
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def f(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def ratio(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _mix(a: str, b: str, t: float) -> str:
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb))


@unittest.skipIf(theme is None, "PySide6 não instalado")
class Contrast(unittest.TestCase):
    def test_text_on_backgrounds(self):
        for key, t in theme.THEMES.items():
            for fg in ("text", "muted", "ok", "warn", "bad", "info"):
                for bg in ("bg", "surface", "surface2"):
                    with self.subTest(theme=key, fg=fg, bg=bg):
                        self.assertGreaterEqual(ratio(t[fg], t[bg]), 4.5)
                with self.subTest(theme=key, fg=fg, bg="surface3"):
                    self.assertGreaterEqual(ratio(t[fg], t["surface3"]), 3.0)

    def test_accent_as_text(self):
        # o tema claro usa a cor de destaque como texto (menu e separadores ativos)
        t = theme.THEMES["claro"]
        for bg in ("bg", "surface", "surface2"):
            self.assertGreaterEqual(ratio(t["accent"], t[bg]), 4.5, bg)

    def test_primary_buttons(self):
        for key, t in theme.THEMES.items():
            light = t["light"]
            for acc in ("accent", "accent2"):
                bg = t[acc] if light else _mix(t[acc], "#000000", 0.25)   # igual a theme.stylesheet()
                with self.subTest(theme=key, acc=acc):
                    self.assertGreaterEqual(ratio(t["accent_text"], bg), 4.5)

    def test_danger_hover(self):
        for key, t in theme.THEMES.items():
            fg = "#ffffff" if t["light"] else t["bg"]
            with self.subTest(theme=key):
                self.assertGreaterEqual(ratio(fg, t["bad"]), 4.5)


if __name__ == "__main__":
    unittest.main()
