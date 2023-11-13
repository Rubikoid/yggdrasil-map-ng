import datetime
from asyncio import StreamReader, StreamWriter, open_connection
from enum import Enum
from pathlib import Path
from types import TracebackType
from typing import Annotated, AsyncContextManager, Generic, Literal, NewType, TypeVar

from annotated_types import Len
from loguru import logger
from pydantic import BaseModel, Field, RootModel, TypeAdapter

from .config import settings

try:
    from asyncio import open_unix_connection  # type: ignore
except ImportError:
    logger.warning(f"open_unix_connection unavailable (it's okay, if you on windows)")

_Key = NewType("Key", str)
Key = Annotated[_Key, Len(min_length=64, max_length=64)]
EmptyKey = Annotated[_Key, Len(min_length=0, max_length=0)]
Addr = NewType("Addr", str)
T = TypeVar("T")  # , bound=BaseResponse | RootModel


# def key_to_ip(key: Key) -> Addr:
#     pass


class BaseException(Exception):
    pass


class RequestException(Exception):
    pass


class BaseResponse(BaseModel):
    pass


class GetSelfResponse(BaseResponse):
    build_name: str
    build_version: str

    key: Key
    address: str

    routing_entries: int
    subnet: str


class GetPeersResponse(BaseResponse):
    class BasePeer(BaseResponse):
        remote: str

        up: bool
        inbound: bool

        port: int
        priority: int

    class AlivePeer(BasePeer):
        key: Key

        bytes_recvd: int
        bytes_sent: int
        uptime: float

    class DeadPeer(BasePeer):
        key: EmptyKey

        # TODO: do something with it
        last_error: str | None = None
        last_error_time: datetime.datetime | None = None

    peers: list[AlivePeer | DeadPeer]


class GetTreeResponse(BaseResponse):
    class TreeEntry(BaseResponse):
        address: str
        key: Key
        parent: Key
        sequence: int

    tree: list[TreeEntry]


class LookupsResponse(BaseResponse):
    class Lookup(BaseResponse):
        addr: Addr
        key: Key
        path: list[int]
        time: datetime.datetime

    infos: list[Lookup]


class GetNodeInfoResponse(BaseResponse):
    buildarch: str
    buildname: str
    buildplatform: str
    buildversion: str
    name: str


class RemoteGetPeers(BaseResponse):
    keys: list[Key] = []


class RemoteGetSelf(BaseResponse):
    key: Key
    routing_entries: int


class Response(BaseModel):
    class Status(str, Enum):
        success = "success"
        error = "error"

    status: Status
    request: "BaseRequest"


class SuccessResponse(Response, Generic[T]):
    status: Literal[Response.Status.success]

    response: T


class ErrorResponse(Response):
    status: Literal[Response.Status.error]

    error: str


class BaseRequest(BaseModel, Generic[T]):
    request: str

    arguments: dict[str, str] = {}

    keepalive: bool = True

    response_model: type[T] | None = Field(None, exclude=True)


class BaseYggdrasil(AsyncContextManager):
    _connected: bool = False
    _rw: tuple[StreamReader, StreamWriter]

    socket_path: Path | str

    def __init__(
        self,
        socket_path: Path | str = settings.ygg,
    ) -> None:
        self.socket_path = socket_path

    async def __aenter__(self):
        if isinstance(self.socket_path, Path):
            self._rw = await open_unix_connection(self.socket_path)
        else:
            host, port = self.socket_path.split(":")
            self._rw = await open_connection(host=host, port=int(port))
        logger.info(f"Connected to {self.socket_path}")
        self._connected = True

        return self

    async def __aexit__(
        self,
        __exc_type: type[BaseException] | None,
        __exc_value: BaseException | None,
        __traceback: TracebackType | None,
    ) -> bool | None:
        self._connected = False

        r, w = self._rw
        w.close()

        return None

    async def do_request(self, req: BaseRequest[T]) -> SuccessResponse[T]:
        if not self._connected:
            raise Exception("Not connected")

        r, w = self._rw

        w.write(req.model_dump_json().encode())
        await w.drain()

        resp = await r.read(65535)
        resp.decode()
        logger.trace(f"{req} -> {resp.decode()}")

        if not req.response_model:
            raise Exception

        parsed = TypeAdapter(SuccessResponse[req.response_model] | ErrorResponse).validate_json(resp)
        if parsed.status == Response.Status.error:
            raise RequestException(parsed)

        logger.trace(f"{parsed}")
        return parsed


class Yggdrasil(BaseYggdrasil):
    async def get_self(self) -> GetSelfResponse:
        raw = await self.do_request(BaseRequest(request="getself", response_model=GetSelfResponse))
        return raw.response

    async def get_peers(self) -> GetPeersResponse:
        raw = await self.do_request(BaseRequest(request="getpeers", response_model=GetPeersResponse))
        return raw.response

    async def get_tree(self) -> GetTreeResponse:
        raw = await self.do_request(BaseRequest(request="gettree", response_model=GetTreeResponse))
        return raw.response

    async def lookups(self) -> LookupsResponse:
        raw = await self.do_request(BaseRequest(request="lookups", response_model=LookupsResponse))
        return raw.response

    async def get_paths(self) -> LookupsResponse:
        raw = await self.do_request(BaseRequest(request="getpaths", response_model=LookupsResponse))
        return raw.response

    async def remote_get_info(self, key: Key) -> dict[str, GetNodeInfoResponse]:
        raw = await self.do_request(
            BaseRequest(
                request="getnodeinfo",
                arguments={"key": key},
                response_model=RootModel[dict[str, GetNodeInfoResponse]],
            ),
        )
        return raw.response.root

    async def remote_get_peers(self, key: Key) -> dict[str, RemoteGetPeers]:
        raw = await self.do_request(
            BaseRequest(
                request="debug_remotegetpeers",
                arguments={"key": key},
                response_model=RootModel[dict[str, RemoteGetPeers]],
            ),
        )
        return raw.response.root

    async def remote_get_self(self, key: Key) -> dict[str, RemoteGetSelf]:
        raw = await self.do_request(
            BaseRequest(
                request="debug_remotegetself",
                arguments={"key": key},
                response_model=RootModel[dict[str, RemoteGetSelf]],
            ),
        )
        return raw.response.root

    async def remote_get_tree(self, key: Key) -> dict[str, RemoteGetPeers]:
        raw = await self.do_request(
            BaseRequest(
                request="debug_remotegettree",
                arguments={"key": key},
                response_model=RootModel[dict[str, RemoteGetPeers]],
            ),
        )
        return raw.response.root
