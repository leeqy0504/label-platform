import os

import pytest

from label_platform.datasets.paths import SourcePathError, iter_safe_files, resolve_source_path


def test_resolve_source_path_rejects_symlink_escape(tmp_path):
    root = tmp_path / "approved"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(SourcePathError, match="approved root"):
        resolve_source_path(root, "escape")


@pytest.mark.parametrize("relative", ["../outside", "/etc", "a/../../outside"])
def test_resolve_source_path_rejects_traversal(tmp_path, relative):
    root = tmp_path / "approved"
    root.mkdir()

    with pytest.raises(SourcePathError):
        resolve_source_path(root, relative)


def test_resolve_source_path_returns_existing_child_directory(tmp_path):
    root = tmp_path / "approved"
    child = root / "incoming" / "warehouse"
    child.mkdir(parents=True)

    assert resolve_source_path(root, "incoming/warehouse") == child.resolve()


def test_iter_safe_files_rejects_symlink(tmp_path):
    root = tmp_path / "approved"
    root.mkdir()
    target = tmp_path / "outside.jpg"
    target.write_bytes(b"image")
    (root / "linked.jpg").symlink_to(target)

    with pytest.raises(SourcePathError, match="symbolic link"):
        list(iter_safe_files(root))


def test_iter_safe_files_rejects_fifo(tmp_path):
    root = tmp_path / "approved"
    root.mkdir()
    os.mkfifo(root / "pipe")

    with pytest.raises(SourcePathError, match="regular file"):
        list(iter_safe_files(root))


def test_iter_safe_files_returns_sorted_regular_files(tmp_path):
    root = tmp_path / "approved"
    (root / "nested").mkdir(parents=True)
    second = root / "z.json"
    first = root / "nested" / "a.jpg"
    second.write_text("{}", encoding="utf-8")
    first.write_bytes(b"image")

    assert list(iter_safe_files(root)) == [first, second]
