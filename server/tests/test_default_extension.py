"""The default "Your pages" extension: copied once, never re-created after the user deletes it."""
from __future__ import annotations

import shutil

from maxxing import cmd_core, config, extensions


def test_pages_extension_is_seeded_once(mx):
    ws = config.workspace()
    cmd_core.copy_templates(ws)
    page = ws / "extensions" / "pages"
    assert (page / "manifest.json").is_file() and (page / "page.js").is_file()
    ext = next(e for e in extensions.scan() if e.id == "pages")
    assert ext.error is None and ext.type == "page" and ext.label() == "Your pages"
    config.update_config(language="fr")
    assert ext.label() == "Vos pages"
    assert extensions.handler(ext)(extensions.make_ctx(ext), "GET", "topic", {}, None)["topic"] == \
        "projects/system/topics/harness"
    shutil.rmtree(page)
    cmd_core.copy_templates(ws)                    # next update: left deleted
    assert not page.exists() and (ws / "extensions" / "README.md").is_file()


def test_shipped_extensions_still_load(mx):
    """Every extension we ship (examples + the default one) loads with the current contract."""
    import shutil as sh
    ws = config.workspace()
    root = ws / "extensions"
    root.mkdir(parents=True, exist_ok=True)
    srcs = [p for p in (config.CODE / "examples" / "extensions").iterdir() if p.is_dir()]
    srcs.append(config.TEMPLATES_DIR / "workspace" / "extensions" / "pages")
    for src in srcs:
        sh.copytree(src, root / src.name, dirs_exist_ok=True)
    loaded = {e.id: e for e in extensions.scan()}
    for src in srcs:
        e = loaded[src.name]
        assert e.error is None, (e.id, e.error)
        assert extensions.EXT_API_MIN <= e.api <= extensions.EXT_API
