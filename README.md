# devi-subhadra-plugins

Katalog plugin lepas untuk agen [devi-subhadra](https://github.com/tonshans/devi-subhadra). Repo agen
hanya membawa plugin inti; plugin di sini dipasang saat dibutuhkan.

## Struktur

```
devi-subhadra-plugins/
├── config.yaml        # lokasi checkout agent (agent_dir)
├── devi-plugins.py    # installer/uninstaller
├── test_devi_plugins.py
└── plugins/
    ├── <nama>.py
    └── <nama>.test.py # opsional; ikut dipasang ke tests/ agent
```

## Pemakaian

```bash
cd devi-subhadra-plugins
python3 devi-plugins.py help
python3 devi-plugins.py available
python3 devi-plugins.py installed
python3 devi-plugins.py install web_browser
python3 devi-plugins.py remove web_browser
python3 devi-plugins.py verify web_browser
```

Target agent diambil dari `config.yaml` (`agent_dir`). Override kapan saja:

```bash
python3 devi-plugins.py --dir=../devi-subhadra available
python3 devi-plugins.py available --dir=../devi-subhadra
```

`available` menandai plugin yang sudah terpasang dengan `*`.

## Yang dilakukan `install`

1. Cek kontrak plugin secara statis (AST, tanpa import): subclass
   `BaseAgentPlugin`, `plugin_name`/`description` literal, `input_schema`,
   method `initialize`/`execute`/`shutdown`, nama file == `plugin_name`, dan
   import `core.*` hanya dari `core.base_plugin`, `core.schemas`,
   `core.config_loader`.
2. Salin `<nama>.py` ke `<agent>/plugins/`.
3. Salin `<nama>.test.py` (kalau ada) ke `<agent>/tests/`.
4. Muat plugin lewat `PluginLoader` memakai `.venv` agent. Gagal → file hasil
   salinan dihapus dan pesan menyebut dependency yang kurang.

Kalau `.venv` agent tidak ada, langkah 4 dilewati dengan peringatan.

## Perintah lain

- `installed`: daftar plugin di `<agent>/plugins/`, ditandai `[catalog]` kalau
  berasal dari repo ini atau `[local]` kalau buatan agent sendiri.
- `verify <nama>`: load plugin lalu jalankan `pytest` test-nya di venv agent.
- `remove <nama>`: hapus plugin + test-nya. File yang bukan dari katalog
  (plugin buatan agent) hanya dihapus dengan `--force`.

## Plugin di katalog

| Plugin | Kebutuhan |
| --- | --- |
| `web_browser` | stdlib saja |
| `academic_search` | `httpx` |
| `community_pulse` | `httpx` |
| `mcp_connector` | `httpx` (server MCP eksternal) |
| `antigravity_delegate` | CLI `agy` di LXC |
| `headless_browser` | extra `browser` (`playwright` + Chromium) |
| `lainnya` | `menyusul` |

Untuk `headless_browser`:

```bash
cd ../devi-subhadra
uv sync --extra browser
uv run playwright install chromium
```

## Menambah plugin baru

1. Taruh `<nama>.py` di `plugins/`, ikuti `_template_plugin.py` di repo agen.
2. Opsional: `<nama>.test.py` di folder yang sama.
3. Jalankan `python3 devi-plugins.py install <nama>`.

Metadata plugin dibaca dari class attribute; tidak ada file manifest terpisah.

## Test script

```bash
python3 -m unittest test_devi_plugins
```
