from ascender.common import BaseDTO
from pydantic import Field


class IExtWorkspace(BaseDTO):
    default_subdir: str | None = None
    absolute_path: str | None = None


class IExtManifest(BaseDTO):
    version: str

    name: str
    description: str = ""
    author: str | None = None
    homepage: str | None = None
    min_hyprchan_version: str | None = None
    requirements: list[str] = Field(default_factory=list)
    readme: str | None = None
    tags: list[str] = Field(default_factory=list)
    workspace: IExtWorkspace | None = None
    setup: str | None = None
