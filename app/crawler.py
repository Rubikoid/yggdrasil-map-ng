from types import TracebackType
from typing import AsyncContextManager, Literal, NewType, Self, TypeAlias

from devtools import debug
from loguru import logger
from pydantic import BaseModel, Field

from .ygg import Addr, EmptyKey, Key, RequestError, Yggdrasil, GetSelfResponse

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
    def id(self) -> int:
        return get_id(self.key)

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

    class Edge(BaseModel):
        from_: NodeId = Field(serialization_alias="from")
        to: NodeId

        dashes: bool = False
        arrows: Literal["to"] | str | None = None

    nodes: list[Node] = []
    edges: list[Edge] = []


class Crawler(AsyncContextManager):
    ygg: Yggdrasil

    self_info: GetSelfResponse

    peers: dict[Key, PeerData]
    enriched_peers: dict[Key, EnrichedPeerData]

    peers_connections: dict[Key, list[Key]]

    def __init__(self) -> None:
        self.ygg = Yggdrasil()

    async def init(self) -> None:
        self.self_info = await self.ygg.get_self()
        await self.refresh()

    async def refresh(self):
        self.peers = {}
        self.enriched_peers = {}

        self.peers_connections = {}

        try:
            peer_info = (await self.ygg.remote_get_info(self.self_info.key))[self.self_info.key].model_dump()
            peer_info["key"] = self.self_info.key
            peer_data = PeerData.model_validate(peer_info)
            self.peers[peer_data.key] = peer_data
        except Exception as ex:
            # FIXME: temporary?? solution b/c (only windows??) ygg client refuses to do remote_* with self key
            self.peers[self.self_info.key] = PeerData(
                key=self.self_info.key,
                name="idk, root",
                buildname=self.self_info.build_name,
                buildversion=self.self_info.build_version,
                buildarch=UNK,
                buildplatform=UNK,
            )

        root_peers = await self.ygg.get_peers()
        for peer in root_peers.peers:
            if not peer.up:
                continue

            await self.fill(peer.key)

        lookups = await self.ygg.lookups()
        for lookup in lookups.infos:
            node_info = self.peers.get(lookup.key, None)
            if not node_info:
                logger.warning(f"{lookup} not found in nodes cache, reloading")
                await self.fill(lookup.key)
                node_info = self.peers.get(lookup.key, PeerData(key=lookup.key))

            node = EnrichedPeerData.model_validate(lookup.model_dump() | node_info.model_dump())
            self.enriched_peers[node.key] = node

    async def fill(self, key: Key):
        if key == self.self_info.key:
            return

        if key in self.peers:
            return

        try:
            _, raw_remote_peers = (await self.ygg.remote_get_peers(key)).popitem()
            _, raw_remote_trees = (await self.ygg.remote_get_tree(key)).popitem()
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

        try:
            peer_info = (await self.ygg.remote_get_info(key))[key].model_dump()
            peer_info["key"] = key
            peer_data = PeerData.model_validate(peer_info)
        except RequestError as ex:
            logger.warning(f"{key} -> {ex!r}")

            peer_data = PeerData(key=key)

        self.peers[peer_data.key] = peer_data

        for possible_key in remote_peers + remote_trees:
            await self.fill(possible_key)

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
                    to = get_id(e.key)

                    ret.edges.append(Export.Edge(from_=get_id(node.key), to=to))

            case "peers":
                for root_key, children in self.peers_connections.items():
                    for child in children:
                        ret.edges.append(
                            Export.Edge(
                                from_=get_id(child),
                                to=get_id(root_key),
                            )
                        )

        for node in nodes.values():
            ret.nodes.append(
                Export.Node(
                    id=get_id(node.key),
                    label=node.label,
                )
            )

        return ret

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
