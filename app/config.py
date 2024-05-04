import os
import platform
import sys
from pydantic_settings import BaseSettings
from pydantic import FilePath
from pathlib import Path


class Settings(BaseSettings):
    refresh_seconds: int = 60 * 2

    socket: FilePath | str | None = None

    workers: int = 6

    reload_bad: bool = True

    @property
    def ygg(self) -> Path | str:
        if self.socket:
            if isinstance(self.socket, str) and ":" not in self.socket:
                return Path(self.socket)

            return self.socket
        match platform.system():
            case "Windows":
                return "127.0.0.1:9001"
            case "Linux":
                return Path("/var/run/yggdrasil.sock")
            case "Darwin":
                return Path("")  # FIXME: and this

        raise Exception("No control path")


settings = Settings()

if platform.system() == "Windows":
    from graphviz.backend import dot_command

    dot_command.DOT_BINARY = Path(r"C:\Program Files\Graphviz\bin\dot.exe")
