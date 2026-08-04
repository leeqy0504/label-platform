from pathlib import Path

import yaml


def test_platform_services_support_host_native_unitrain():
    compose = yaml.safe_load(Path("compose.yaml").read_text(encoding="utf-8"))
    environment = compose["x-platform-environment"]
    platform_service = compose["x-platform-service"]

    assert environment["PLATFORM_UNITRAIN_MOUNT_ROOT"] == (
        "${PLATFORM_UNITRAIN_MOUNT_ROOT:-/datasets}"
    )
    assert "host.docker.internal:host-gateway" in platform_service["extra_hosts"]


def test_label_studio_uses_toolbar_extension_image():
    compose = yaml.safe_load(Path("compose.yaml").read_text(encoding="utf-8"))
    label_studio = compose["services"]["label-studio"]

    assert label_studio["image"] == "label-platform-label-studio:1.21.0"
    assert label_studio["build"] == {
        "context": ".",
        "dockerfile": "deploy/labelstudio.Dockerfile",
    }
    script = Path("deploy/labelstudio-delete-button.js").read_text(encoding="utf-8")
    assert "data-label-platform-delete-button" in script
    assert 'node.textContent.trim() === "删除图片"' in script
