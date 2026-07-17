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

