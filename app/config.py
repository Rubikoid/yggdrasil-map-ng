import os
import platform
import sys
from pydantic_settings import BaseSettings
from pydantic import FilePath
from pathlib import Path


class Settings(BaseSettings):
    socket: FilePath | str | None = None

    @property
    def ygg(self) -> Path | str:
        if self.socket:
            return self.socket
        match platform.system():
            case "Windows":
                return "127.0.0.1:9001"
            case "Linux":
                return Path("")  # FIXME: fill this
            case "Darwin":
                return Path("")  # FIXME: and this

        raise Exception("No control path")


settings = Settings()
