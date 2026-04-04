# Hyprchan Extensions & Plugins Roadmap

This roadmap tracks the extension system work from the earliest design through future milestones.
Items are marked with `[X]` when completed.

## Completed

- [X] Extension manifest schema defined (`manifest.yml`) with metadata fields.
- [X] Extension loader reads `manifest.yml` and validates schema.
- [X] Extension loader imports extension module from path.
- [X] Extension class resolution by subclass of `HyprchanExtension`.
- [X] Extension lifecycle hooks (`on_init`, `on_shutdown`).
- [X] Hook system foundation (`HookManager`, `HookName`, interception/mutation).
- [X] Passive executor hooks wired (`on_ponder`, `on_passive_enter`, `on_passive_leave`, `on_ai_inference`, `on_ai_response`).
- [X] Tool registry with built-in tools, dynamic register/unregister.
- [X] Workspace helpers for extensions (`get_extension_workspace`, `get_extension_data_dir`).
- [X] Extension workspace injection (`workspace_dir`, `data_dir`) in loader.
- [X] Manifest support for extension `requirements`.
- [X] Manifest support for `min_hyprchan_version`.
- [X] Public SDK surface `hyprchan.extensions` exported.

## Planned (Short Term)

- [ ] Roadmap: document extension author guide with examples.
- [ ] Extension manifest `entrypoint` (module:ClassName) for explicit class resolution.
- [ ] Extension config surface (YAML or TOML) for extension-specific settings.
- [ ] Extension enable/disable list in personalization config.
- [ ] Extension loader safe-unload with rollback/cleanup hooks.
- [ ] Extension CLI manager (load/list/unload) for local dev testing.
- [ ] Extension setup wizard/TUI framework for per-extension configuration.

## Planned (Mid Term)

- [ ] Extension isolation mode: optional per-extension venv.
- [ ] Extension isolation mode: optional subprocess execution.
- [ ] Extension dependency installer / bootstrapper.
- [ ] Extension compatibility checker (runtime + install-time).
- [ ] Extension permissions model (capabilities / resource access).

## Planned (Long Term)

- [ ] Extension marketplace or registry mechanism.
- [ ] Signed extensions / integrity verification.
- [ ] Extension update management and version pinning.
