"""The package manager of the system (apt, dnf, pacman): names, commands, the unit of cron."""
from maxxing import health, pkg


def _only(monkeypatch, binary):
    monkeypatch.setattr(pkg.shutil, "which", lambda b: f"/usr/bin/{b}" if b == binary else None)


def test_debian_keeps_its_names(monkeypatch):
    _only(monkeypatch, "apt-get")
    assert pkg.manager() == "apt"
    assert pkg.hint("cron", "ffmpeg") == "apt-get install -y cron ffmpeg"
    assert pkg.clean_cmd() == ["apt-get", "clean"]
    assert pkg.purge_cmd("caddy")[:2] == ["apt-get", "purge"]


def test_fedora_and_arch_names(monkeypatch):
    _only(monkeypatch, "dnf")
    assert pkg.hint("cron", "ffmpeg", "jq") == "dnf install -y cronie ffmpeg-free jq"
    assert pkg.install_cmd("postgresql")[-1] == "postgresql-server"
    assert pkg.cache()[1] == "*.rpm"
    _only(monkeypatch, "pacman")
    assert pkg.hint("cron") == "pacman -S --needed cronie"
    assert pkg.purge_cmd("caddy") == ["pacman", "-Rns", "--noconfirm", "caddy"]


def test_no_package_manager(monkeypatch):
    _only(monkeypatch, "nothing")
    assert pkg.manager() == ""
    assert pkg.install("socat")[0] == 127


def test_cron_service_follows_the_unit_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(pkg, "UNIT_DIRS", (str(tmp_path),))
    assert pkg.cron_service() == "cron"                      # nothing found: Debian's name
    (tmp_path / "crond.service").write_text("")
    assert pkg.cron_service() == "crond"
    assert "crond" in health.service_names() and "cron" not in health.service_names()
