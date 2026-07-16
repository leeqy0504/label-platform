from __future__ import annotations

import stat
from dataclasses import dataclass
from collections.abc import Iterator
from pathlib import Path, PurePosixPath


SUPPORTED_SOURCE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".json", ".zip"})


class SourcePathError(ValueError):
    pass


@dataclass(frozen=True)
class SourceEntry:
    name: str
    relative_path: str
    is_directory: bool


def resolve_approved_root(root: Path) -> Path:
    if root.is_symlink():
        raise SourcePathError("approved root cannot be a symbolic link")
    try:
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise SourcePathError("approved root does not exist") from exc
    if not resolved.is_dir():
        raise SourcePathError("approved root is not a directory")
    return resolved


def resolve_source_path(root: Path, relative: str) -> Path:
    if "\x00" in relative or "\\" in relative:
        raise SourcePathError("source path is not a valid POSIX relative path")

    relative_path = PurePosixPath(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise SourcePathError("source path escapes the approved root")

    resolved_root = resolve_approved_root(root)
    candidate = resolved_root
    for part in relative_path.parts:
        if part in {"", "."}:
            continue
        candidate = candidate / part
        if candidate.is_symlink():
            raise SourcePathError("source path escapes the approved root through a symbolic link")

    try:
        resolved_candidate = candidate.resolve(strict=True)
    except OSError as exc:
        raise SourcePathError("source path does not exist") from exc
    if not resolved_candidate.is_relative_to(resolved_root):
        raise SourcePathError("source path escapes the approved root")
    if not resolved_candidate.is_dir():
        raise SourcePathError("source path is not a directory")
    return resolved_candidate


def iter_safe_files(root: Path) -> Iterator[Path]:
    resolved_root = resolve_approved_root(root)

    def walk(directory: Path) -> Iterator[Path]:
        for entry in sorted(directory.iterdir(), key=lambda path: path.as_posix()):
            if entry.is_symlink():
                raise SourcePathError(f"symbolic link is not allowed: {entry}")
            try:
                mode = entry.stat(follow_symlinks=False).st_mode
            except OSError as exc:
                raise SourcePathError(f"cannot inspect source entry: {entry}") from exc
            if stat.S_ISDIR(mode):
                yield from walk(entry)
            elif stat.S_ISREG(mode):
                yield entry
            else:
                raise SourcePathError(f"source entry is not a regular file: {entry}")

    yield from walk(resolved_root)


def list_safe_children(root: Path, relative: str = "") -> tuple[SourceEntry, ...]:
    directory = resolve_source_path(root, relative)
    prefix = PurePosixPath(relative)
    entries: list[SourceEntry] = []

    try:
        children = directory.iterdir()
        for child in children:
            if child.is_symlink():
                raise SourcePathError(f"symbolic link is not allowed: {child.name}")
            try:
                mode = child.stat(follow_symlinks=False).st_mode
            except OSError as exc:
                raise SourcePathError(f"cannot inspect source entry: {child.name}") from exc

            child_relative = child.name if str(prefix) == "." else (prefix / child.name).as_posix()
            if stat.S_ISDIR(mode):
                entries.append(SourceEntry(child.name, child_relative, True))
            elif stat.S_ISREG(mode):
                if child.suffix.lower() in SUPPORTED_SOURCE_EXTENSIONS:
                    entries.append(SourceEntry(child.name, child_relative, False))
            else:
                raise SourcePathError(f"source entry is not a regular file: {child.name}")
    except SourcePathError:
        raise
    except OSError as exc:
        raise SourcePathError("cannot browse source directory") from exc

    return tuple(
        sorted(
            entries,
            key=lambda entry: (not entry.is_directory, entry.name.casefold(), entry.name),
        )
    )
