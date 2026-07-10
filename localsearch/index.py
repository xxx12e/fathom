"""Dual index: fp16 FAISS dense (exact) + BM25 lexical, crash-durable on disk."""
import logging
import os
import pickle
import struct
from pathlib import Path

import numpy as np
import faiss

from .chunker import tokenize

log = logging.getLogger("localsearch.index")
faiss.omp_set_num_threads(1)

INDEX_VERSION = 2
_MAGIC = b"LSDX0002"


class IndexVersionError(Exception):
    """Index on disk was built by an incompatible (older) version."""


class IndexCorruptError(Exception):
    """Index files on disk are torn/inconsistent (e.g. power loss mid-save)."""


def _new_dense(dim):
    inner = faiss.IndexScalarQuantizer(dim, faiss.ScalarQuantizer.QT_fp16,
                                       faiss.METRIC_INNER_PRODUCT)
    return faiss.IndexIDMap2(inner)


class DualIndex:
    def __init__(self, dim):
        self.dim = dim
        self.dense = _new_dense(dim)
        self.chunk_meta = {}
        self.file_chunks = {}
        self.file_meta = {}
        self.next_id = 0
        self.generation = 0
        self._bm25 = None
        self._bm25_cids = []
        self._tokens = {}
        self._dir_refs = None


    @staticmethod
    def _ancestors(path):
        p = os.path.normcase(str(path))
        while True:
            parent = os.path.dirname(p)
            if not parent or parent == p:
                return
            yield parent
            p = parent

    def _dir_ref(self, path, delta):
        if self._dir_refs is None:
            return
        for d in self._ancestors(path):
            n = self._dir_refs.get(d, 0) + delta
            if n > 0:
                self._dir_refs[d] = n
            else:
                self._dir_refs.pop(d, None)

    def dir_known(self, prefix):
        """True if any indexed file lives under `prefix` (O(1) after lazy build)."""
        if self._dir_refs is None:
            self._dir_refs = {}
            for p in self.file_meta:
                self._dir_ref(p, +1)
        return os.path.normcase(str(prefix)).rstrip("\\/") in self._dir_refs


    def add_file(self, path, chunks, vecs, fmeta):
        """chunks: [(text,start,end)]; vecs: [n,dim] aligned to chunks."""
        path = str(path)
        if path in self.file_chunks:
            self.remove_file(path)
        self._dir_ref(path, +1)
        if len(chunks) == 0:
            self.file_meta[path] = fmeta
            self.file_chunks[path] = []
            return 0
        cids = list(range(self.next_id, self.next_id + len(chunks)))
        self.next_id += len(chunks)
        self.dense.add_with_ids(vecs, np.array(cids, dtype=np.int64))
        for cid, (text, st, en), i in zip(cids, chunks, range(len(chunks))):
            self.chunk_meta[cid] = dict(path=path, idx=i, text=text, start=st, end=en)
            self._tokens[cid] = tokenize(text)
        self.file_chunks[path] = cids
        self.file_meta[path] = fmeta
        return len(chunks)

    def _pop_file(self, path):
        """Drop a file's dict entries; return its cids (dense NOT touched)."""
        if path in self.file_chunks:
            self._dir_ref(path, -1)
        cids = self.file_chunks.pop(path, [])
        self.file_meta.pop(path, None)
        for cid in cids:
            self.chunk_meta.pop(cid, None)
            self._tokens.pop(cid, None)
        return cids

    def remove_file(self, path):
        cids = self._pop_file(str(path))
        if cids:
            self.dense.remove_ids(faiss.IDSelectorBatch(np.array(cids, dtype=np.int64)))
        return len(cids)

    def remove_files(self, paths):
        """Batched removal: one remove_ids pass for many files."""
        all_cids = []
        for p in paths:
            all_cids.extend(self._pop_file(str(p)))
        if all_cids:
            self.dense.remove_ids(faiss.IDSelectorBatch(np.array(all_cids, dtype=np.int64)))
        return len(all_cids)


    def bm25_inputs(self):
        """Snapshot (cids, token_lists) for an out-of-lock BM25 build."""
        cids = list(self.chunk_meta.keys())
        toks = []
        for c in cids:
            t = self._tokens.get(c)
            if t is None:
                t = tokenize(self.chunk_meta[c]["text"])
                self._tokens[c] = t
            toks.append(t)
        return cids, toks

    def set_bm25(self, cids, bm25):
        self._bm25_cids = cids
        self._bm25 = bm25

    @staticmethod
    def build_bm25(toks):
        """Pure compute -- safe to run outside the engine lock on a snapshot."""
        if not toks:
            return None
        from rank_bm25 import BM25Okapi
        return BM25Okapi(toks)

    def rebuild_bm25(self):
        cids, toks = self.bm25_inputs()
        self.set_bm25(cids, self.build_bm25(toks))

    def ensure_bm25(self):
        """Build BM25 on first need (loads no longer build it -> fast startup)."""
        if self._bm25 is None and self.chunk_meta:
            self.rebuild_bm25()


    def search_dense(self, qvec, topk):
        if self.dense.ntotal == 0:
            return []
        D, I = self.dense.search(qvec, min(topk, self.dense.ntotal))
        return [(int(c), float(s)) for c, s in zip(I[0], D[0]) if c >= 0]

    def search_bm25(self, qtokens, topk):
        if self._bm25 is None or not self._bm25_cids:
            return []
        scores = self._bm25.get_scores(qtokens)
        n = min(topk, len(scores))
        top = np.argpartition(-scores, n - 1)[:n]
        top = top[np.argsort(-scores[top])]
        return [(self._bm25_cids[i], float(scores[i])) for i in top]


    def snapshot(self):
        """Serialize under the engine lock; write_snapshot() writes it outside."""
        self.generation += 1
        dense_arr = faiss.serialize_index(self.dense)
        store = dict(version=INDEX_VERSION, generation=self.generation, dim=self.dim,
                     chunk_meta=dict(self.chunk_meta), file_chunks=dict(self.file_chunks),
                     file_meta=dict(self.file_meta), next_id=self.next_id,
                     tokens=dict(self._tokens))
        return self.generation, dense_arr, store

    @staticmethod
    def write_snapshot(index_dir, generation, dense_arr, store):
        """Write tmp-first with fsync, then rename back-to-back (torn-save safe)."""
        index_dir = Path(index_dir)
        index_dir.mkdir(parents=True, exist_ok=True)
        tmp_d = index_dir / "dense.faiss.tmp"
        with open(tmp_d, "wb") as f:
            f.write(_MAGIC + struct.pack("<Q", generation))
            dense_arr.tofile(f)
            f.flush()
            os.fsync(f.fileno())
        tmp_s = index_dir / "store.pkl.tmp"
        with open(tmp_s, "wb") as f:
            pickle.dump(store, f, protocol=pickle.HIGHEST_PROTOCOL)
            f.flush()
            os.fsync(f.fileno())
        tmp_d.replace(index_dir / "dense.faiss")
        tmp_s.replace(index_dir / "store.pkl")
        log.info("saved index gen %d: %d files, %d chunks -> %s",
                 generation, len(store["file_chunks"]), len(store["chunk_meta"]), index_dir)

    def save(self, index_dir):
        gen, dense_arr, store = self.snapshot()
        self.write_snapshot(index_dir, gen, dense_arr, store)

    @classmethod
    def load(cls, index_dir):
        index_dir = Path(index_dir)
        with open(index_dir / "store.pkl", "rb") as f:
            store = pickle.load(f)
        if store.get("version") != INDEX_VERSION:
            raise IndexVersionError(
                f"index version {store.get('version')} != {INDEX_VERSION} (rebuild needed)")
        with open(index_dir / "dense.faiss", "rb") as f:
            raw = f.read()
        if len(raw) < 16 or raw[:8] != _MAGIC:
            raise IndexCorruptError("dense.faiss: bad header")
        (gen,) = struct.unpack("<Q", raw[8:16])
        if gen != store.get("generation"):
            raise IndexCorruptError(
                f"dense.faiss gen {gen} != store gen {store.get('generation')} (torn save)")
        obj = cls(store["dim"])
        obj.dense = faiss.deserialize_index(np.frombuffer(raw, dtype=np.uint8, offset=16))
        obj.chunk_meta = store["chunk_meta"]
        obj.file_chunks = store["file_chunks"]
        obj.file_meta = store["file_meta"]
        obj.next_id = store["next_id"]
        obj.generation = store["generation"]
        obj._tokens = store.get("tokens") or {}


        if obj.dense.ntotal != len(obj.chunk_meta):
            raise IndexCorruptError(
                f"dense has {obj.dense.ntotal} vectors but store has "
                f"{len(obj.chunk_meta)} chunks")
        if obj.chunk_meta and obj.next_id <= max(obj.chunk_meta):
            raise IndexCorruptError("next_id <= max chunk id (id reuse would corrupt)")

        log.info("loaded index gen %d: %d files, %d chunks",
                 obj.generation, len(obj.file_chunks), len(obj.chunk_meta))
        return obj

    @staticmethod
    def exists(index_dir):
        index_dir = Path(index_dir)
        return (index_dir / "store.pkl").exists() and (index_dir / "dense.faiss").exists()

    @staticmethod
    def quarantine(index_dir):
        """Move damaged index files aside (kept for post-mortem, out of the way)."""
        index_dir = Path(index_dir)
        for name in ("dense.faiss", "store.pkl"):
            p = index_dir / name
            try:
                if p.exists():
                    p.replace(index_dir / (name + ".corrupt"))
            except OSError as e:
                log.warning("could not quarantine %s: %s", p, e)
