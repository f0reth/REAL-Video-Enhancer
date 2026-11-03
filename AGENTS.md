# Repository Instructions

These instructions apply to the entire repository.

## Development policy

This is an internal tool that is still under development, so do not keep backward compatibility or migrate data. Always rewrite the code into its ideal, KISS form.

- Prefer simple, direct implementations for video enhancement, frame interpolation, and upscaling in the Python application (`src/`) and inference backend (`backend/`).
- When changing internal APIs, settings, presets, or frontend/backend interfaces, update all affected callers to the new design in the same change. Remove obsolete code, options, and branches instead of retaining compatibility wrappers, aliases, or legacy fallbacks.
- Do not add migrations or conversion logic for old application settings, presets, caches, or other internal persisted formats. Use the current format and defaults; document any required reset when relevant.
- Keep abstractions minimal and tied to current requirements. Avoid speculative extension points and duplicate implementations.
- Preserve behavior needed by currently supported inference backends and platforms. Hardware-specific implementations and error handling should reflect current requirements rather than historical compatibility.
- Scope rewrites to the affected functionality. This policy does not authorize deleting user videos, model weights, or unrelated files.
