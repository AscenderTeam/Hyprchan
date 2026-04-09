import sys
from dataclasses import dataclass
from importlib import metadata
from importlib import util as importlib_util
import inspect
from pathlib import Path
from typing import Any

import yaml

from hyprchan.config.paths import builtins_extensions_dir, extensions_dir, repo_root
from hyprchan.core.extensions.executor import ExtensionExecutor
from hyprchan.core.extensions.errors import ExtensionNotLoaded
from hyprchan.core.extensions.extension import HyprchanExtension
from hyprchan.core.extensions.types.manifest import IExtManifest
from hyprchan.core.extensions.workspace import resolve_extension_workspace

@dataclass(slots=True)
class LoadedExtension:
    name: str
    path: Path
    manifest: IExtManifest
    instance: HyprchanExtension
    module_name: str
    workspace_dir: Path
    data_dir: Path


class ExtensionLoader:
    def __init__(self, kernel: Any) -> None:
        self.kernel = kernel
        self.executor = ExtensionExecutor(self.kernel)
        self.loaded: dict[str, LoadedExtension] = {}

    async def load(self, extension: str) -> LoadedExtension:
        extension_dir = self._resolve_extension_dir(extension)
        module_path = extension_dir / "extension.py"
        if not module_path.exists():
            raise ExtensionNotLoaded(f"Missing extension.py at {module_path}")

        if str(extension_dir) not in sys.path:
            sys.path.insert(0, str(extension_dir))

        module_name = f"hyprchan_ext_{extension_dir.name}"
        try:
            spec = importlib_util.spec_from_file_location(module_name, module_path)
            if spec is None or spec.loader is None:
                raise ExtensionNotLoaded(f"Unable to load extension at {module_path}")
            module = importlib_util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            manifest = self._load_manifest(extension_dir)
            self._check_requirements(manifest)
            extension_impl = self._resolve_extension_instance(module)
            workspace_dir, data_dir = self._prepare_workspace(
                manifest, extension_dir.name
            )
            extension_impl.workspace_dir = workspace_dir
            extension_impl.data_dir = data_dir
            setattr(module, "__hyprchan_workspace__", workspace_dir)
            setattr(module, "__hyprchan_data_dir__", data_dir)
            await extension_impl.on_init(self.executor)
            loaded = LoadedExtension(
                name=manifest.name,
                path=extension_dir,
                manifest=manifest,
                instance=extension_impl,
                module_name=module_name,
                workspace_dir=workspace_dir,
                data_dir=data_dir,
            )
            self.loaded[manifest.name] = loaded
            return loaded
        except ExtensionNotLoaded:
            raise
        except Exception as exc:
            raise ExtensionNotLoaded(
                f"Failed to load extension from {module_path}: {exc}"
            ) from exc

    def _resolve_extension_instance(self, module: object) -> HyprchanExtension:
        extension_obj = getattr(module, "extension", None)
        if isinstance(extension_obj, HyprchanExtension):
            return extension_obj

        candidates: list[type[HyprchanExtension]] = []
        for value in vars(module).values():
            if not inspect.isclass(value):
                continue
            if value is HyprchanExtension:
                continue
            if issubclass(value, HyprchanExtension):
                candidates.append(value)

        if not candidates:
            raise ExtensionNotLoaded(
                "extension.py must expose an instance or subclass of HyprchanExtension"
            )
        if len(candidates) > 1:
            raise ExtensionNotLoaded(
                "extension.py defines multiple HyprchanExtension subclasses"
            )

        return candidates[0]()

    async def unload(self, name: str) -> None:
        loaded = self.loaded.pop(name, None)
        if loaded is None:
            raise ExtensionNotLoaded(f"Extension not loaded: {name}")

        try:
            await loaded.instance.on_shutdown()
        finally:
            sys.modules.pop(loaded.module_name, None)

    def _resolve_extension_dir(self, extension: str) -> Path:
        # 1. Direct path (for local dev)
        candidate = Path(extension).expanduser()
        if candidate.exists():
            return candidate.resolve()

        # 2. User config (~/.config/hyprchan/extensions)
        user_candidate = (extensions_dir() / extension).resolve()
        if user_candidate.exists():
            return user_candidate

        # 3. Built-ins (repo/extensions or installed site-packages/extensions)
        builtins_candidate = (builtins_extensions_dir() / extension).resolve()
        if builtins_candidate.exists():
            return builtins_candidate

        # 4. Old repo candidate (fallback for backward compatibility in source runs)
        repo_candidate = (repo_root() / extension).expanduser()
        if repo_candidate.exists():
            return repo_candidate.resolve()

        # Final fallback
        return (extensions_dir() / extension).resolve()

    def _prepare_workspace(
        self, manifest: IExtManifest, fallback_name: str
    ) -> tuple[Path, Path]:
        workspace_dir = resolve_extension_workspace(manifest.name or fallback_name, manifest)
        workspace_dir.mkdir(parents=True, exist_ok=True)
        data_dir = workspace_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        return workspace_dir, data_dir

    @staticmethod
    def _load_manifest(extension_dir: Path) -> IExtManifest:
        manifest_path = extension_dir / "manifest.yml"
        if not manifest_path.exists():
            raise ExtensionNotLoaded(f"Missing manifest.yml at {manifest_path}")

        try:
            raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            raise ExtensionNotLoaded(
                f"Failed to read manifest.yml at {manifest_path}"
            ) from exc

        try:
            return IExtManifest.model_validate(raw)
        except Exception as exc:
            raise ExtensionNotLoaded(
                f"Invalid manifest.yml at {manifest_path}"
            ) from exc

    def _check_requirements(self, manifest: IExtManifest) -> None:
        if manifest.min_hyprchan_version:
            current = self._current_version()
            if current is None:
                raise ExtensionNotLoaded(
                    "Hyprchan version unknown; cannot verify extension compatibility"
                )
            if self._compare_versions(current, manifest.min_hyprchan_version) < 0:
                raise ExtensionNotLoaded(
                    f"Extension requires Hyprchan >= {manifest.min_hyprchan_version}"
                )

        missing = [
            req
            for req in manifest.requirements
            if importlib_util.find_spec(req) is None
        ]
        if missing:
            joined = ", ".join(missing)
            raise ExtensionNotLoaded(f"Missing extension requirements: {joined}")

    def _current_version(self) -> str | None:
        pyproject = repo_root() / "pyproject.toml"
        try:
            if pyproject.exists():
                import tomllib

                data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
                project = data.get("project", {})
                version = project.get("version")
                if isinstance(version, str) and version.strip():
                    return version.strip()
        except Exception:
            pass

        try:
            return metadata.version("hyprchan")
        except Exception:
            return None

    @staticmethod
    def _compare_versions(left: str, right: str) -> int:
        def normalize(value: str) -> list[int]:
            parts = value.strip().split(".")
            parsed: list[int] = []
            for part in parts:
                try:
                    parsed.append(int(part))
                except ValueError:
                    parsed.append(0)
            return parsed

        left_parts = normalize(left)
        right_parts = normalize(right)
        size = max(len(left_parts), len(right_parts))
        left_parts.extend([0] * (size - len(left_parts)))
        right_parts.extend([0] * (size - len(right_parts)))
        if left_parts < right_parts:
            return -1
        if left_parts > right_parts:
            return 1
        return 0
