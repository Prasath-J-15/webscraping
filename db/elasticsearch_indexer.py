import hashlib
import threading

from elasticsearch import AsyncElasticsearch
from elasticsearch import BadRequestError, ConflictError, NotFoundError
from elasticsearch import ConnectionError as ESConnectionError

from core.config import settings
from core.exceptions import IndexingError
from core.logger import get_logger
from models.domain import ScrapedItem

logger = get_logger(__name__)

INDEX_MAPPING: dict = {
    "mappings": {
        "dynamic": False,
        "properties": {
            "internalRefid": {"type": "long"},
            "sourceRefid": {"type": "keyword"},
            "sourceURL": {"type": "keyword"},
            "domain": {"type": "keyword"},
            "extractedContent": {"type": "text"},
            "createdAt": {"type": "date"},
            "updatedAt": {"type": "date"},
        }
    }
}


class ElasticsearchIndexer:
    """Handles document upserts and index lifecycle for scraped items.

    Same identity contract as the production service this demo mirrors: the
    document `_id` is `md5(sourceURL)`, so re-crawling a URL always updates
    the same document instead of creating a duplicate. `internalRefid` and
    `createdAt` are assigned once on first insert and never overwritten.
    """

    def __init__(self, client: AsyncElasticsearch) -> None:
        self.client = client
        self._counter: int = 0
        self._counter_lock = threading.Lock()

    def next_refid(self) -> int:
        with self._counter_lock:
            self._counter += 1
            return self._counter

    async def _load_counter(self) -> None:
        """Seed the in-memory counter from max(internalRefid) already in the index."""
        try:
            resp = await self.client.search(
                index=settings.index_name,
                body={"size": 0, "aggs": {"max_refid": {"max": {"field": "internalRefid"}}}},
            )
            max_val = resp["aggregations"]["max_refid"]["value"]
            with self._counter_lock:
                self._counter = int(max_val) if max_val is not None else 0
            logger.info(f"internalRefid counter seeded at {self._counter}")
        except Exception as exc:
            logger.warning(f"Could not read max internalRefid — starting from 0: {exc}")
            with self._counter_lock:
                self._counter = 0

    async def ensure_index(self) -> None:
        """Create the index if missing, then seed the refid counter.

        Uses create-and-ignore instead of exists+create — `indices.exists`
        (a HEAD request) returns inconsistent status codes across some ES
        server configs/proxies.
        """
        index = settings.index_name
        try:
            await self.client.indices.create(index=index, mappings=INDEX_MAPPING["mappings"])
            logger.info(f"Created Elasticsearch index: {index}")
        except BadRequestError as exc:
            if "resource_already_exists_exception" in str(exc).lower():
                pass
            else:
                raise
        await self._load_counter()

    async def upsert(self, item: ScrapedItem) -> int:
        """Insert or update a document.

        New document — a refid is assigned via next_refid() just before the
        create call (so a re-crawl of an already-indexed URL never wastes a
        counter value), full document written, returns the assigned refid.
        Existing document — only content + updatedAt are overwritten;
        internalRefid/createdAt are preserved; returns 0.
        """
        index = settings.index_name
        doc_id = hashlib.md5(item.source_url.encode()).hexdigest()

        update_fields = {
            "extractedContent": item.extracted_content,
            "updatedAt": item.updated_at.isoformat(),
        }

        for conn_attempt in range(2):
            try:
                try:
                    await self.client.update(index=index, id=doc_id, doc=update_fields)
                    logger.info(f"Updated item '{item.source_refid}' from '{item.domain}'")
                    return 0

                except NotFoundError:
                    internal_refid = self.next_refid()
                    try:
                        await self.client.create(
                            index=index,
                            id=doc_id,
                            document={
                                "internalRefid": internal_refid,
                                "sourceRefid": item.source_refid,
                                "sourceURL": item.source_url,
                                "domain": item.domain,
                                "createdAt": item.created_at.isoformat(),
                                **update_fields,
                            },
                        )
                        logger.info(f"Indexed item '{item.source_refid}' from '{item.domain}' as internalRefid={internal_refid}")
                        return internal_refid

                    except ConflictError:
                        # Race: another task created the doc between our update
                        # attempt and our create attempt. Fall back to update.
                        await self.client.update(index=index, id=doc_id, doc=update_fields)
                        logger.info(f"Race-condition update for '{item.source_refid}' from '{item.domain}'")
                        return 0

                except ConflictError:
                    logger.warning(f"Conflict on document '{doc_id}'; skipping.")
                    return 0

            except ESConnectionError as exc:
                if conn_attempt == 0:
                    logger.warning(f"ES connection dropped, reconnecting: {exc}")
                    from db.elasticsearch_client import reconnect_elasticsearch
                    self.client = await reconnect_elasticsearch()
                else:
                    logger.error(f"ES connection error after retry for '{doc_id}': {exc}", exc_info=True)
                    raise IndexingError(f"Failed to index document into '{index}' after retry: {exc}") from exc

        return 0
