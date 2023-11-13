from typing import NewType

from devtools import debug
from loguru import logger
from pydantic import BaseModel, Field

from .ygg import Addr, EmptyKey, Key, RequestException, Yggdrasil, GetSelfResponse

UNK = "unknown"

NodeId = NewType("NodeId", int)


def get_id(key: Key) -> NodeId:
    return NodeId(int(key, 16))


class PeerData(BaseModel):
    key: Key

    name: str

    buildname: str
    buildversion: str

    buildarch: str
    buildplatform: str

    @property
    def id(self) -> NodeId:
        return get_id(self.key)


class XNodeInfo(BaseModel):
    ip: Addr
    key: Key | EmptyKey

    name: str

    path: list[int]

    @property
    def label(self) -> str:
        return f"{self.name} - {self.ip[:8]}"

    @property
    def parent(self) -> list[int]:
        return self.path[:-1] if len(self.path) > 0 else []

    @property
    def link(self) -> int:
        if len(self.path) > 0:
            return self.path[-1]
        else:
            return 0


class Export(BaseModel):
    class Node(BaseModel):
        id: NodeId
        label: str

    class Edge(BaseModel):
        from_: NodeId = Field(serialization_alias="from")
        to: NodeId

        dashes: bool = False
        # arrows: str = "to"

    nodes: list[Node] = []
    edges: list[Edge] = []


class Context:
    ygg: Yggdrasil

    root_ygg: GetSelfResponse

    peers: dict[Key, PeerData] = {}

    peers_connections: dict[Key, list[Key]] = {}
    # trees_connections: dict[Key, list[Key]] = {}

    def __init__(self) -> None:
        self.peers = {}
        # self.peers_connections = {}
        # self.trees_connections = {}

    async def run(self):
        self.root_ygg = await self.ygg.get_self()
        self.peers[self.root_ygg.key] = PeerData(
            key=self.root_ygg.key,
            name="idk, root",
            buildname=self.root_ygg.build_name,
            buildversion=self.root_ygg.build_version,
            buildarch=UNK,
            buildplatform=UNK,
        )

        root_peers = await self.ygg.get_peers()
        for peer in root_peers.peers:
            if not peer.up:
                continue

            await self.fill(peer.key)

    async def fill(self, key: Key):
        if key == self.root_ygg.key:
            return

        if key in self.peers:
            return

        try:
            _, raw_remote_peers = (await self.ygg.remote_get_peers(key)).popitem()
            _, raw_remote_trees = (await self.ygg.remote_get_tree(key)).popitem()
            remote_peers = raw_remote_peers.keys
            remote_trees = raw_remote_trees.keys
        except RequestException as ex:
            logger.warning(f"{key} -> {ex!r}")
            
            remote_peers = []
            remote_trees = []

        self.peers_connections[key] = remote_peers
        # trees_list = self.trees_connections.setdefault(key, [])

        remote_trees.remove(key)  # WTF: remove self tree

        # trees_list.extend(remote_trees.keys)

        peer_info = (await self.ygg.remote_get_info(key))[key].model_dump()
        peer_info["key"] = key

        peer_data = PeerData.model_validate(peer_info)
        self.peers[peer_data.key] = peer_data

        for possible_key in remote_peers + remote_trees:
            await self.fill(possible_key)

        # # todo: make it optimal with sets
        # for key in remote_peers.keys + remote_trees.keys:
        #     if key not in peers and key not in not_found_keys:
        #         not_found_keys.append(key)

    async def export(self) -> Export:
        ret = Export()
        lookups = await self.ygg.lookups()

        raw_nodes: list[XNodeInfo] = []
        for lookup in lookups.infos:
            node_info = self.peers[lookup.key]

            node = XNodeInfo(
                ip=Addr(lookup.addr),
                key=lookup.key,
                name=node_info.name,
                path=lookup.path,
            )
            raw_nodes.append(node)

        nodes: dict[tuple[int, ...], XNodeInfo] = dict()

        def add_shit(info: XNodeInfo):
            parent_coords = info.parent

            parent = XNodeInfo(
                ip=Addr(""),
                key=EmptyKey(""),
                name="?",
                path=parent_coords,
            )

            nodes[tuple(parent_coords)] = parent
            if parent.path != parent.parent:
                add_shit(parent)

        for info in raw_nodes:
            add_shit(info)

        for info in raw_nodes:
            nodes[tuple(info.path)] = info

        for node in nodes.values():
            if node.parent == node.path:
                continue
            e = nodes[tuple(node.parent)]
            to = get_id(e.key)
            ret.edges.append(Export.Edge(from_=get_id(node.key), to=to))

        for node in nodes.values():
            ret.nodes.append(
                Export.Node(
                    id=get_id(node.key),
                    label=node.label,
                )
            )

        return ret


async def crawl():
    ygg = Yggdrasil()

    context = Context()
    context.ygg = ygg

    async with ygg:
        await context.run()

        return (await context.export()).model_dump_json(by_alias=True)

        # for peer in peers.values():
        #     if peer.key == root_ygg.key:
        #         continue

        # for unk_key in not_found_keys:
        #     try:
        #         peer_info = (await ygg.remote_get_info(unk_key))[unk_key].model_dump()
        #         peer_info["key"] = unk_key

        #         peer_data = PeerData.model_validate(peer_info)
        #         peers[peer_data.key] = peer_data

        #     except RequestException:
        #         peers[unk_key] = PeerData(
        #             key=unk_key,
        #             buildarch=UNK,
        #             buildname=UNK,
        #             buildplatform=UNK,
        #             buildversion=UNK,
        #             name=UNK,
        #         )
