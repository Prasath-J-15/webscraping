import hashlib
import uuid
from typing import Optional

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
            "internalRefid": {"type": "keyword"},
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
    the same document instead of creating a duplicate. `internalRefid` is a
    time-ordered UUID (`uuid1`) assigned once on first insert; `createdAt` is
    likewise assigned once — neither is ever overwritten on a re-crawl.
    """

    def __init__(self, client: AsyncElasticsearch) -> None:
        self.client = client

    async def ensure_index(self) -> None:
        """Create the index if it does not already exist.

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

    async def upsert(self, item: ScrapedItem) -> Optional[str]:
        """Insert or update a document.

        New document — a fresh `uuid1` is assigned as `internalRefid`, the
        full document is created, and that id is returned so the caller can
        stamp it onto the response. Existing document — only
        `extractedContent` and `updatedAt` are overwritten; `internalRefid`/
        `createdAt` are left untouched in the stored document, and this
        returns `None` (the caller keeps whatever id it already had).
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
                    return None

                except NotFoundError:
                    internal_refid = str(uuid.uuid1())
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
                        return None

                except ConflictError:
                    logger.warning(f"Conflict on document '{doc_id}'; skipping.")
                    return None

            except ESConnectionError as exc:
                if conn_attempt == 0:
                    logger.warning(f"ES connection dropped, reconnecting: {exc}")
                    from db.elasticsearch_client import reconnect_elasticsearch
                    self.client = await reconnect_elasticsearch()
                else:
                    logger.error(f"ES connection error after retry for '{doc_id}': {exc}", exc_info=True)
                    raise IndexingError(f"Failed to index document into '{index}' after retry: {exc}") from exc

        return None
