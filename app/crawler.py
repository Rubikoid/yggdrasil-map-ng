import asyncio
from types import TracebackType
from typing import AsyncContextManager, Literal, NewType, Self, TypeAlias

from loguru import logger
from pydantic import BaseModel, Field

from .config import settings
from .ygg import Addr, EmptyKey, GetSelfResponse, Key, RequestError, Yggdrasil

UNK = "unknown"

NodeId = NewType("NodeId", int)
MODE: TypeAlias = Literal["path"] | Literal["peers"]


def get_id(key: Key) -> NodeId:
    return NodeId(int(key, 16))


class PeerData(BaseModel):
    key: Key

    name: str = UNK

    buildname: str = UNK
    buildversion: str = UNK

    buildarch: str = UNK
    buildplatform: str = UNK

    cluster: str | None = None


class EnrichedPeerData(PeerData):
    addr: Addr
    key: Key | EmptyKey

    path: list[int]

    @property
    def label(self) -> str:
        return f"{self.name} - {self.addr[:8]}"

    @property
    def parent(self) -> list[int]:
        return self.path[:-1] if len(self.path) > 0 else []

    @property
    def tpath(self) -> tuple[int, ...]:
        return tuple(self.path)

    @property
    def id(self) -> NodeId:
        if self.key != "":
            return get_id(self.key)
        else:
            return NodeId(
                hash(
                    (
                        self.addr,
                        self.key,
                        self.name,
                        tuple(self.path),
                    )
                )
            )

    @classmethod
    def empty(cls: type[Self], path: list[int]) -> Self:
        return cls(
            addr=Addr(""),
            key=EmptyKey(""),
            path=path,
        )


class Export(BaseModel):
    class Node(BaseModel):
        id: NodeId
        label: str
        buildplatform: str = UNK
        buildversion: str = UNK
        cluster: str | None = None

    class Edge(BaseModel):
        from_: NodeId = Field(serialization_alias="from")
        to: NodeId

        dashes: bool = False
        arrows: Literal["to"] | Literal["from"] | Literal["to;from"] | str | None = None

    nodes: list[Node] = []
    edges: list[Edge] = []

    clusters: set[str] = set()


class Crawler(AsyncContextManager):
    ygg: Yggdrasil

    self_info: GetSelfResponse

    peers: dict[Key, PeerData]
    enriched_peers: dict[Key, EnrichedPeerData]

    peers_connections: dict[Key, list[Key]]

    refresh_lock: asyncio.Lock

    key_locks: dict[Key, bool]
    keys_queue: asyncio.Queue[Key]

    workers: list

    def __init__(self) -> None:
        self.ygg = Yggdrasil()
        self.refresh_lock = asyncio.Lock()

    async def init(self) -> None:
        self.self_info = await self.ygg.get_self()
        self.keys_queue = asyncio.Queue()

        self.workers = []
        for _ in range(settings.workers):
            ygg = Yggdrasil()
            worker = asyncio.create_task(self.worker(ygg))
            self.workers.append(worker)

        logger.info(f"Created {len(self.workers)} workers")

    def reset(self):
        assert self.refresh_lock.locked()

        self.peers = {}
        self.enriched_peers = {}
        self.peers_connections = {}
        self.key_locks = {}

    async def refresh(self):
        if self.refresh_lock.locked():
            logger.warning(f"Refresh already requested: {self.refresh_lock = }")
            return

        async with self.refresh_lock:
            # reset arrs
            self.reset()

            # find self info
            peer_data = await self.remote_get_info(self.self_info.key, ygg=self.ygg)
            # FIXME: temporary?? solution b/c (only windows??) ygg client refuses to do remote_* with self key
            peer_data = peer_data or PeerData(
                key=self.self_info.key,
                name="idk, root",
                buildname=self.self_info.build_name,
                buildversion=self.self_info.build_version,
                buildarch=UNK,
                buildplatform=UNK,
            )
            self.peers[peer_data.key] = peer_data
            logger.info(f"Got self: {peer_data}")

            # get peers, which i connected to
            root_peers = await self.ygg.get_peers()
            for peer in root_peers.peers:
                if not peer.up:
                    continue

                # for every peer - add to queue.
                await self.put_key_to_queue(peer.key)

            logger.info(f"{self.keys_queue.qsize() = }")
            await self.keys_queue.join()
            logger.info(f"Done waiting {self.keys_queue.qsize() = }")

            # get all lookups...
            lookups = await self.ygg.lookups()
            for lookup in lookups.infos:
                node_info = self.peers.get(lookup.key, None)
                if not node_info:
                    if settings.reload_bad:
                        logger.warning(f"{lookup} not found in nodes cache, reloading")
                        await self.fill_for_key(lookup.key, self.ygg)

                    node_info = self.peers.get(lookup.key, PeerData(key=lookup.key))

                node = EnrichedPeerData.model_validate(lookup.model_dump() | node_info.model_dump())
                self.enriched_peers[node.key] = node

    async def put_key_to_queue(self, key: Key) -> None:
        # don't put self to queue
        if key == self.self_info.key:
            return

        # if we already got everything about this key
        if key in self.peers:
            return

        # if we now resolving this key
        if key in self.key_locks:
            return

        await self.keys_queue.put(key)

    def crawling_status(self) -> None:
        def _format(self: asyncio.Queue):  # WTF: DITRY
            result = f"maxsize={self._maxsize!r}"  # type: ignore
            if getattr(self, "_queue", None):
                result += f" _queue={len(self._queue)!r}"  # type: ignore
            if self._getters:  # type: ignore
                result += f" _getters[{len(self._getters)}]"  # type: ignore
            if self._putters:  # type: ignore
                result += f" _putters[{len(self._putters)}]"  # type: ignore
            if self._unfinished_tasks:  # type: ignore
                result += f" tasks={self._unfinished_tasks}"  # type: ignore
            return result

        logger.info(f"Now in db: {len(self.peers)} peers, ")
        logger.info(f"Waiting for: {self.keys_queue.qsize()!r} in queue (and {_format(self.keys_queue)})")
        for key in self.key_locks:
            if key not in self.peers:
                logger.info(f"and for {key}")

    async def worker(self, ygg: Yggdrasil) -> None:
        async with ygg:
            while True:
                key = await self.keys_queue.get()

                # logger.info(f"Got {key}")

                # check and set lock
                if self.key_locks.get(key, False):
                    self.keys_queue.task_done()
                    continue
                self.key_locks[key] = True

                await self.fill_for_key(key, ygg)

                self.keys_queue.task_done()

                # logger.info(f"{key} done")
                # self.waiting_for()

    async def fill_for_key(self, key: Key, ygg: Yggdrasil) -> None:
        try:
            _, raw_remote_peers = (await ygg.remote_get_peers(key)).popitem()
            _, raw_remote_trees = (await ygg.remote_get_tree(key)).popitem()
            remote_peers = raw_remote_peers.keys
            remote_trees = raw_remote_trees.keys
        except RequestError as ex:
            logger.warning(f"{key} -> {ex!r}")

            remote_peers = []
            remote_trees = []

        self.peers_connections[key] = remote_peers

        # trees_list = self.trees_connections.setdefault(key, [])

        if key in remote_trees:
            remote_trees.remove(key)  # WTF: remove self tree

        # trees_list.extend(remote_trees.keys)

        peer_data = (await self.remote_get_info(key, ygg)) or PeerData(key=key)
        self.peers[peer_data.key] = peer_data

        for possible_key in remote_peers + remote_trees:
            if ygg == self.ygg:
                logger.info(f"WTF new leaf from {key = } going to recursion")
                await self.fill_for_key(key, ygg=ygg)
            else:
                await self.put_key_to_queue(possible_key)

    def export(self, mode: MODE) -> Export:
        ret = Export()
        nodes: dict[tuple[int, ...], EnrichedPeerData] = dict()

        for info in self.enriched_peers.values():
            nodes[info.tpath] = info

        match mode:
            case "path":
                # TODO: this is copypasted from old cringe graph gen.
                # make it normal
                def resolve_parents(info: EnrichedPeerData):
                    parent_coords = info.parent

                    parent = EnrichedPeerData.empty(parent_coords)

                    if parent.tpath not in nodes:
                        nodes[parent.tpath] = parent

                    if parent.path != parent.parent:
                        resolve_parents(parent)

                for info in self.enriched_peers.values():
                    resolve_parents(info)

                for node in nodes.values():
                    if node.parent == node.path:
                        continue

                    e = nodes[tuple(node.parent)]
                    to = e.id

                    ret.edges.append(Export.Edge(from_=node.id, to=to))

            case "peers":
                for root_key, children in self.peers_connections.items():
                    for child in children:
                        edge = Export.Edge(
                            from_=get_id(child),
                            to=get_id(root_key),
                        )
                        ret.edges.append(edge)

                        antiedge = Export.Edge(
                            to=get_id(child),
                            from_=get_id(root_key),
                        )
                        if edge in ret.edges and antiedge in ret.edges:
                            ret.edges.remove(edge)
                            ret.edges.remove(antiedge)
                            edge.arrows = "to;from"
                            ret.edges.append(edge)

        for node in nodes.values():
            cluster = node.cluster or node.name.rsplit(".", maxsplit=1)[0]
            ret.clusters.add(cluster)

            ret.nodes.append(
                Export.Node(
                    id=node.id,
                    label=node.label,
                    buildplatform=node.buildplatform,
                    buildversion=node.buildversion,
                    cluster=cluster,
                )
            )

        return ret

    async def remote_get_info(self, key: Key, ygg: Yggdrasil) -> PeerData | None:
        try:
            src_model = (await ygg.remote_get_info(key))[key]
        except RequestError as ex:
            logger.warning(f"{key = } -> {ex!r}")
            return None
        except Exception as ex:
            logger.error(f"{key = } -> {ex!r}")
            raise
        else:
            dumped_model = src_model.model_dump()
            dumped_model["key"] = key
            return PeerData.model_validate(dumped_model)

    async def __aenter__(self):
        self.ygg = await self.ygg.__aenter__()
        await self.init()

    async def __aexit__(
        self,
        __exc_type: type[BaseException] | None,
        __exc_value: BaseException | None,
        __traceback: TracebackType | None,
    ) -> bool | None:
        await self.ygg.__aexit__(__exc_type, __exc_value, __traceback)
        return None


crawler = Crawler()
