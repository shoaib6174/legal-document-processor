from typing import List

import chromadb
from chromadb.config import Settings
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

from .models import RetrievedEvidence, TextChunk


class EvidenceRetriever:
    """Hybrid dense + sparse retrieval with Reciprocal Rank Fusion."""

    def __init__(self, persist_dir: str = "./data/chroma_db"):
        self.persist_dir = persist_dir
        self.client = chromadb.Client(
            Settings(persist_directory=persist_dir, is_persistent=True)
        )
        self.collection = self.client.get_or_create_collection("legal_docs")
        self.encoder = SentenceTransformer("all-MiniLM-L6-v2")
        self.bm25: BM25Okapi | None = None
        self.chunk_map: dict[str, TextChunk] = {}
        self.tokenized_corpus: list[list[str]] = []

    def index(self, chunks: List[TextChunk]) -> None:
        """Index chunks in both ChromaDB (dense) and BM25 (sparse)."""
        if not chunks:
            return

        texts = [c.text for c in chunks]
        ids = [c.chunk_id for c in chunks]
        embeddings = self.encoder.encode(texts).tolist()

        metadatas = [
            {
                "source_doc": c.source_doc,
                "page_num": c.page_num,
                "confidence_score": c.confidence_score,
            }
            for c in chunks
        ]

        self.collection.add(
            documents=texts,
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
        )

        self.tokenized_corpus = [doc.lower().split() for doc in texts]
        self.bm25 = BM25Okapi(self.tokenized_corpus)
        self.chunk_map = {c.chunk_id: c for c in chunks}

    def retrieve(self, query: str, top_k: int = 5) -> List[RetrievedEvidence]:
        """Hybrid retrieval with RRF fusion of dense + sparse rankings."""
        # Dense search
        query_embedding = self.encoder.encode(query).tolist()
        dense_results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k * 2,
        )

        dense_ranking: dict[str, int] = {}
        if dense_results["ids"] and dense_results["ids"][0]:
            for rank, chunk_id in enumerate(dense_results["ids"][0]):
                dense_ranking[chunk_id] = rank + 1

        # Sparse search
        sparse_ranking: dict[str, int] = {}
        if self.bm25 and self.tokenized_corpus:
            tokenized_query = query.lower().split()
            bm25_scores = self.bm25.get_scores(tokenized_query)
            import numpy as np

            top_sparse_indices = np.argsort(bm25_scores)[::-1][: top_k * 2]
            chunk_ids = list(self.chunk_map.keys())
            for rank, idx in enumerate(top_sparse_indices):
                if idx < len(chunk_ids):
                    sparse_ranking[chunk_ids[idx]] = rank + 1

        # RRF fusion
        k_rrf = 60
        fused_scores: dict[str, float] = {}
        all_ids = set(dense_ranking.keys()) | set(sparse_ranking.keys())

        for chunk_id in all_ids:
            score = 0.0
            if chunk_id in dense_ranking:
                score += 1.0 / (k_rrf + dense_ranking[chunk_id])
            if chunk_id in sparse_ranking:
                score += 1.0 / (k_rrf + sparse_ranking[chunk_id])
            fused_scores[chunk_id] = score

        sorted_ids = sorted(
            fused_scores.keys(), key=lambda x: fused_scores[x], reverse=True
        )[:top_k]

        results = []
        for chunk_id in sorted_ids:
            chunk = self.chunk_map.get(chunk_id)
            if chunk:
                results.append(
                    RetrievedEvidence(
                        chunk_id=chunk_id,
                        text=chunk.text,
                        source_doc=chunk.source_doc,
                        page_num=chunk.page_num,
                        score=fused_scores[chunk_id],
                    )
                )

        return results

    def clear(self) -> None:
        """Clear all indexed documents."""
        try:
            self.client.delete_collection("legal_docs")
        except Exception:
            pass
        self.collection = self.client.get_or_create_collection("legal_docs")
        self.bm25 = None
        self.chunk_map = {}
        self.tokenized_corpus = []
