"""Drivers e componentes em falta (Linux e Windows) e a sua entrada na Saúde do PC."""
import unittest
from unittest import mock

from nexo.core import components as c


def linux(**kw):
    base = {"os": "linux", "pm": "pacman", "gpus": [{"name": "RX 6500 XT", "vendor": "AMD", "driver": "amdgpu"}],
            "installed": ["vulkan-radeon", "lib32-vulkan-radeon", "intel-ucode"], "steam_native": True,
            "cpu_vendor": "Intel", "chwd": False, "ubuntu_drivers": False, "rpmfusion": False}
    base.update(kw)
    return base


def ids(found):
    return [f.id for f in found]


class Linux(unittest.TestCase):
    def test_complete_system_has_nothing(self):
        self.assertEqual(c.evaluate(linux()), [])

    def test_missing_vulkan_is_bad_and_installable(self):
        f = c.evaluate(linux(installed=["lib32-vulkan-radeon", "intel-ucode"]))
        self.assertEqual(ids(f), ["vulkan_amd"])
        self.assertEqual((f[0].kind, f[0].packages, f[0].action), ("bad", ["vulkan-radeon"], "install"))

    def test_amdvlk_counts_as_vulkan(self):
        self.assertEqual(c.evaluate(linux(installed=["amdvlk", "lib32-amdvlk", "intel-ucode"])), [])

    def test_lib32_only_matters_with_native_steam(self):
        have = ["vulkan-radeon", "intel-ucode"]
        self.assertEqual(ids(c.evaluate(linux(installed=have))), ["vulkan32_amd"])
        self.assertEqual(c.evaluate(linux(installed=have, steam_native=False)), [])

    def test_microcode_per_vendor(self):
        f = c.evaluate(linux(cpu_vendor="AMD"))
        self.assertEqual(ids(f), ["microcode"])
        self.assertEqual(f[0].packages, ["amd-ucode"])

    def test_nouveau(self):
        g = [{"name": "RTX 3060", "vendor": "NVIDIA", "driver": "nouveau"}]
        f = c.evaluate(linux(gpus=g, installed=["intel-ucode"], chwd=True))
        # o lib32 da NVIDIA não aparece antes de haver driver principal
        self.assertEqual(ids(f), ["nvidia"])
        self.assertEqual(f[0].kind, "bad")
        self.assertEqual(f[0].command, "sudo chwd -a")
        self.assertEqual(f[0].action, "")   # nunca instala drivers NVIDIA sozinho

    def test_nvidia_proprietary_needs_lib32_for_steam(self):
        g = [{"name": "RTX 3060", "vendor": "NVIDIA", "driver": "nvidia 580.1"}]
        self.assertEqual(ids(c.evaluate(linux(gpus=g, installed=["intel-ucode"]))), ["vulkan32_nvidia"])

    def test_debian_names(self):
        f = c.evaluate(linux(pm="dpkg", installed=[]))
        pk = {x.id: x.packages for x in f}
        self.assertEqual(pk["vulkan_amd"], ["mesa-vulkan-drivers"])
        self.assertEqual(pk["vulkan32_amd"], ["mesa-vulkan-drivers:i386"])
        self.assertEqual(pk["microcode"], ["intel-microcode"])

    def test_unknown_package_manager_does_not_guess(self):
        self.assertEqual(c.evaluate(linux(pm=None, installed=[])), [])


class Windows(unittest.TestCase):
    def test_basic_display_adapter(self):
        f = c.evaluate({"os": "windows", "win_gpus": ["Microsoft Basic Display Adapter"],
                        "win_devices": [{"Name": "Microsoft Basic Display Adapter", "ConfigManagerErrorCode": 28,
                                         "PNPClass": "Display"}]})
        self.assertEqual(ids(f), ["basic_display"])   # a placa não conta duas vezes

    def test_devices_ignore_disabled(self):
        f = c.evaluate({"os": "windows", "win_gpus": ["AMD Radeon RX 6500 XT"],
                        "win_devices": [{"Name": "Rede", "ConfigManagerErrorCode": 22},
                                        {"Name": "Leitor USB", "ConfigManagerErrorCode": 45},
                                        {"Name": None, "ConfigManagerErrorCode": 28}]})
        self.assertEqual(ids(f), ["devices"])
        self.assertIn("Dispositivo desconhecido (sem driver instalado)", f[0].detail)
        self.assertTrue(f[0].title.startswith("1 "))


class Health(unittest.TestCase):
    def test_worst_finding_goes_to_health(self):
        from nexo.core import healthscore
        found = [c.Finding("microcode", "warn", "Falta o microcode da CPU AMD", ""),
                 c.Finding("vulkan_amd", "bad", "Falta o driver Vulkan da placa AMD", "")]
        with mock.patch.object(c, "cached_findings", return_value=found):
            chk = healthscore._components()
        self.assertEqual(chk[0].kind, "bad")
        self.assertEqual(chk[0].text, "Falta o driver Vulkan da placa AMD (+1).")
        self.assertEqual(chk[0].page, "Atualizações")

    def test_install_command(self):
        found = [c.Finding("vulkan_amd", "bad", "", "", ["vulkan-radeon"], action="install"),
                 c.Finding("vulkan32_amd", "warn", "", "", ["lib32-vulkan-radeon"], action="install"),
                 c.Finding("nvidia", "bad", "", "", command="sudo chwd -a")]
        with mock.patch.object(c, "_pm", return_value="pacman"), \
                mock.patch.object(c, "run_root", return_value=(0, "")) as rr, \
                mock.patch.object(c, "check", return_value=[]), \
                mock.patch("nexo.core.snapshot.with_snapshot", side_effect=lambda cmd, _w: cmd), \
                mock.patch("nexo.core.changes.mark"):
            ok, _msg = c.install(found)
        self.assertTrue(ok)
        self.assertEqual(rr.call_args[0][0], "pacman -S --needed --noconfirm vulkan-radeon lib32-vulkan-radeon")


if __name__ == "__main__":
    unittest.main()
