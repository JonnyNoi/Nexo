"""Tradução para inglês: catálogo, modelos com valores e coerência do catálogo."""
import unittest

from nexo.core import i18n
from nexo.core.i18n_en import EN, TEMPLATES


class Translate(unittest.TestCase):
    def setUp(self):
        i18n.set_lang_for_tests("en")
        self.addCleanup(i18n.set_lang_for_tests, None)

    def test_exact_and_padding(self):
        self.assertEqual(i18n.tr("Definições"), "Settings")
        self.assertEqual(i18n.tr("  Procurar…"), "  Search…")
        self.assertEqual(i18n.tr("PROCESSADOR"), "PROCESSOR")
        self.assertEqual(i18n.tr("texto sem tradução"), "texto sem tradução")
        self.assertEqual(i18n.tr(""), "")

    def test_templates_translate_values_too(self):
        self.assertEqual(i18n.tr("Saúde do PC: Boa"), "PC health: Good")
        self.assertEqual(i18n.tr("Temperatura da CPU alta: 95 °C (limite 90 °C)"), "CPU temperature high: 95 °C (limit 90 °C)")
        self.assertEqual(i18n.tr("há 5 min"), "5 min ago")
        self.assertEqual(i18n.tr("Passo 2 de 6"), "Step 2 of 6")

    def test_rich_text_lines(self):
        self.assertEqual(i18n.tr("Definições<br>Alertas"), "Settings<br>Alerts")

    def test_portuguese_is_untouched(self):
        i18n.set_lang_for_tests("pt")
        self.assertEqual(i18n.tr("Definições"), "Definições")

    def test_missing_lists_untranslated(self):
        self.assertEqual(i18n.missing(["Definições", "outra frase qualquer", "x"]), ["outra frase qualquer"])


class Catalogue(unittest.TestCase):
    def test_values(self):
        for k, v in EN.items():
            with self.subTest(k=k):
                self.assertTrue(v.strip())
                self.assertNotIn("{}", k, "modelos vão em TEMPLATES")

    def test_template_placeholders_match(self):
        for k, v in TEMPLATES.items():
            with self.subTest(k=k):
                self.assertEqual(k.count("{}"), v.count("{}"))

    def test_more_catalog(self):
        from nexo.core.i18n_en_more import EN_MORE, TEMPLATES_MORE
        for k, v in EN_MORE.items():
            with self.subTest(k=k):
                self.assertTrue(v.strip())
                self.assertNotIn("{}", k, "modelos vão em TEMPLATES_MORE")
        for k, v in TEMPLATES_MORE.items():
            with self.subTest(k=k):
                self.assertEqual(k.count("{}"), v.count("{}"))

    def test_new_pages_translated(self):
        """As páginas novas da 2.3 não podem ter texto visível por traduzir (o detetor apanha f-strings como
        modelos com {}). Para outras páginas: python -m nexo.core.i18n nexo/ui/pages/x.py"""
        import re
        from pathlib import Path

        from nexo.core.i18n import _scan, missing
        root = Path(__file__).resolve().parent.parent / "nexo"
        files = [root / f for f in ("ui/pages/battery.py", "ui/pages/programs.py", "ui/boot_card.py",
                                    "ui/wifi_card.py", "ui/weekly_dialog.py", "core/weekly.py", "core/boottime.py",
                                    "core/battery.py", "core/ramspeed.py", "core/wifi.py")]
        pt = re.compile(r"[ãõçáéíóúâêô]|\b(de|do|da|em|não|para|com|que|os|as)\b", re.I)
        todo = [s for s in missing(_scan(files)) if pt.search(s) and "{{" not in s and "\\" not in s]
        # palavras-chave internas (não aparecem no ecrã)
        todo = [s for s in todo if s != "taxa de rece"]
        self.assertEqual(todo, [])

    def test_menu_is_translated(self):
        names = ["Visão geral", "Informação", "Sensores", "Discos", "Saúde dos discos", "Espaço em disco",
                 "Processos", "Fiabilidade", "Antivírus", "Otimização", "Arranque", "Modo jogo", "Testes",
                 "Benchmark", "Stress test", "Software", "Atualizações", "Instalar aplicações", "Internet",
                 "Utilitários", "Tarefas agendadas", "Fundo de ecrã", "Definições", "SISTEMA", "DESEMPENHO",
                 "FERRAMENTAS"]
        for n in names:
            self.assertIn(n, EN, n)


if __name__ == "__main__":
    unittest.main()
