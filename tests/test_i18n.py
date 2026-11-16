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
