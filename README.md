<div align="center">

🌐 **English** · [简体中文](README.zh.md)

# 🏮 Fathom

### Everything finds filenames. **Fathom finds meaning.**

Instant, whole‑disk **semantic** file search that runs **100% offline**.
Type what you *mean* — not the exact words — and find the file. Your files never leave your machine.

`全盘语义搜索 · 秒懂你要找什么 · 纯本地、不联网、隐私零外泄`

**Windows · CPU or GPU · no cloud, no account, no telemetry**

</div>

---

## Search your files by what they *mean*

You remember *what a file was about*. You don't remember its name, or which of five drives it's on, or whether you wrote "invoice" or "发票" or "billing". Keyword search fails you exactly there.

**Fathom searches by meaning.** At its core is a **purpose‑built semantic model** — a compact **109‑million‑parameter embedding network** engineered to understand *what text means*, **not** a bloated multi‑gigabyte local LLM bolted onto a search box. It **re‑ranks whole‑disk candidates with that model** in milliseconds, and — when you want the very best quality — it **builds a complete deep semantic index of the folders you choose**, embedding every passage so it can match your *idea* against files that share **zero words** with your query.

A real semantic engine, not a keyword matcher with a marketing label — and it's **209 MB, lightweight, and 100% on your machine.**

> It's the search **Everything** should have grown into: same instant, whole‑disk reflex — but it understands you.

## By the numbers

| | |
|---|---|
| ⚡ **~8 ms** to semantically search **100,000 files** | comfortably interactive; the model is tiny, not an LLM |
| 🌐 **~0.1 s** whole‑disk semantic results | **zero pre‑indexing** — rides the OS content index |
| 🪶 **109M params · 209 MB** semantic model | vs the **4–8 GB** local LLMs other "AI search" tools ship |
| 🔁 **~35 s** to index 100k files, **~0.1 s** to re‑scan | incremental diff measured **235× faster** than a full scan |
| 🎯 matches paraphrases with **zero shared words** | exact FAISS + BM25 hybrid, fp16 — half the RAM/disk |
| 🔒 **0 bytes** leave your machine | fully offline · binds `127.0.0.1` · no account, no telemetry |
| 📄 **txt · md · pdf · docx** · **中文 & English** | bilingual UI, one‑click 中/EN toggle |

<sub>Speeds measured on a modern GPU (embedding) + FAISS; CPU stays well under the 100 ms interactive bar.</sub>

## Three ways to search, one box

| Mode | What it does | Setup |
|---|---|---|
| 🌐 **Whole‑disk Semantic** | Search the *content* of every file on the machine by meaning. Rides the Windows Search content index, then re‑ranks the hits with a neural model. | **None.** Open and go. |
| ⚡ **Filename** | Instant whole‑disk filename search, the way you already know it. | None. |
| 🎯 **Deep Semantic (Control Mode)** | Point it at folders (or a whole drive) and it builds its *own* deep index — the highest quality, catches paraphrases with **zero word overlap**. First scan is full; after that it only touches what changed, and keeps itself up to date in the background. | One click per folder. |

Plus: **bilingual UI (中文 / English, one‑click toggle)**, keyboard‑driven (`Enter` to search, `↑/↓` to move, `Enter` to open), live‑highlighted snippets that show *why* a file matched, and a portable build that runs on any Windows PC with **no Python install**.

## The privacy stance (the whole point)

- **Fully local.** The embedding model is bundled. Unplug the network and everything still works.
- **Binds `127.0.0.1` only.** Nothing is served to your LAN, let alone the internet.
- **No accounts, no telemetry, no "anonymous usage stats."** There is no server to call.
- Your index and settings live in `~/.localsearch_index` on your own disk.

## Quick start

**Run from source**

```bash
pip install -r requirements.txt
python -m localsearch.app          # opens http://127.0.0.1:8731 in your browser
```

or just double‑click **`run.bat`** (Windows).

**Portable build (no Python needed)** — package it into a single self‑contained folder with a bundled CPU model, then double‑click the `.exe`. Any Windows machine, fully offline. See [`localsearch/README.md`](localsearch/README.md) for the packaging recipe.

## How it works

```
        your query ("the reservoir that hit a record low")
                              │
        ┌─────────────────────┼───────────────────────────┐
   Whole‑disk              Filename                    Deep Semantic
   (Windows Search   →     (Everything‑style,          (own FAISS index of
    content index)          MFT filename)               your chosen folders)
        │                                                    │
        └──────────────►  neural re‑rank · Fathom semantic model  ◄─┘
                              │
                     ranked files + the exact matching sentence, highlighted
```

- **Fathom's semantic model:** a compact **109M‑param embedding network** (768‑dim), purpose‑built to represent *meaning* — not a text‑generating LLM. Runs on CPU, no GPU required, and **never trains on your files**.
- **Retrieval:** exact FAISS (fp16 scalar‑quantized — half the RAM/disk, still exhaustive) fused with a BM25 lexical arm; CJK‑aware chunking + bigram tokenizer so Chinese documents are fully searchable.
- **Instant mode:** queries the OS content index via the `Search.CollatorDSO` provider, then embeds and re‑ranks the candidates — global content search with **zero pre‑indexing**.
- **Robust by design:** crash‑durable index writes (fsync + generation‑stamped, torn saves detected and quarantined), save‑on‑exit, live progress and search *during* indexing, and a single‑thread watcher that survives bulk file copies.

Fathom is English‑first today, and Chinese is fully searchable (structure + lexical + bigram BM25); a Chinese‑primary model can be swapped in. The promise isn't to beat a datacenter on a benchmark — it's cloud‑grade *convenience* with **zero** privacy cost.

## Project layout

```
localsearch/          the engine + local web UI (this is the product)
  ├─ engine.py        orchestrator: scan → parse → chunk → embed → index → search
  ├─ index.py         dual index: fp16 FAISS dense + BM25, crash‑durable persistence
  ├─ winsearch.py     the "instant whole‑disk" breakthrough (Windows content index)
  ├─ search.py        hybrid retrieval + best‑sentence snippets
  ├─ watcher.py       debounced background re‑indexing
  ├─ app.py           Flask backend (127.0.0.1 only) + JSON API
  └─ web/index.html   single‑page UI, bilingual, zero build step
demo_*.py             runnable end‑to‑end examples
run.bat               double‑click launcher
```

## License & credits

**[PolyForm Noncommercial 1.0.0](LICENSE.md)** — free to use, study, modify, and share for any **noncommercial** purpose (personal use, research, education, nonprofits). Commercial use is not granted by this license; reach out if you want to talk.

<sub>Fathom stands on excellent open source: its embedding weights come from the open **BGE** model (BAAI, MIT), retrieval uses **FAISS** (MIT), and filename mode talks to **Everything** (`es.exe`, voidtools — download it yourself). These remain under their own terms.</sub>

---

<div align="center">
<sub>Built for people who remember <i>what</i> they wrote, not <i>where</i> they put it.</sub>
</div>
