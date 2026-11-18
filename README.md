# devi-subhadra-plugins

Katalog plugin lepas untuk agen [devi-subhadra](https://github.com/tonshans/devi-subhadra). Repo agen
hanya membawa plugin inti; plugin di sini dipasang saat dibutuhkan.

## Struktur

```
devi-subhadra-plugins/
├── config.yaml        # lokasi checkout agent (agent_dir)
├── devi-plugins.py    # installer/uninstaller
├── tests/
│   └── test_devi_plugins.py  # test installer
└── plugins/
    ├── <nama>.py
    └── <nama>.test.py # opsional; ikut dipasang ke tests/ agent
```

Test plugin tinggal di `plugins/` (bukan `tests/`) karena `install` mengambil test dari
sana, dan test plugin butuh `core.*` milik checkout agent.

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
5. Cetak `next steps:` dari docstring modul plugin: baris pertama ringkasan,
   baris berikutnya langkah manual setelah install (mis. key `.env` atau
   module Python yang perlu dipasang).

Kalau `.venv` agent tidak ada, langkah 4 dilewati dengan peringatan.

## Perintah lain

- `installed`: daftar plugin di `<agent>/plugins/`, ditandai `[catalog]` kalau
  berasal dari repo ini atau `[local]` kalau buatan agent sendiri.
- `verify <nama>`: load plugin lalu jalankan `pytest` test-nya di venv agent.
- `remove <nama>`: hapus plugin + test-nya. File yang bukan dari katalog
  (plugin buatan agent) hanya dihapus dengan `--force`.


## Menambah plugin baru

1. Taruh `<nama>.py` di `plugins/`, ikuti `_template_plugin.py` di repo agen.
   Docstring modul opsional: baris pertama ringkasan, baris berikutnya dicetak
   sebagai `next steps` setelah install.
2. Opsional: `<nama>.test.py` di folder yang sama.
3. Jalankan `python3 devi-plugins.py install <nama>`.

Metadata plugin dibaca dari class attribute; tidak ada file manifest terpisah.

## Test script

Test installer:

```bash
python3 -m unittest tests.test_devi_plugins
```

Test plugin butuh `core.*` dari checkout agent, jadi jalankan lewat venv agent:

```bash
PYTHONPATH=../devi-subhadra ../devi-subhadra/.venv/bin/python -m pytest \
  -o python_files='*.test.py test_*.py' --import-mode=importlib tests plugins
```
