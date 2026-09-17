"""Activate one verified Oracle release with one atomic data-symlink switch.

Research releases remain immutable. Access storage stays at its original private
path, outside the release. No data file or previous release is deleted.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.error import URLError
from urllib.request import urlopen
from uuid import uuid4

from golden_vector.common.files import atomic_write_text, sha256_file


def activate(root: Path) -> dict:
    root = root.resolve(strict=True)
    base = Path("/srv/golden-vector")
    releases = (base / "releases").resolve(strict=True)
    if root.parent != releases:
        raise ValueError("Only an immediate child of the reviewed releases directory may be activated")
    publication = json.loads((root / "publication.json").read_text())
    for relative, entry in publication["files"].items():
        path = (root / relative).resolve(strict=True)
        if not path.is_relative_to(root / "data") or sha256_file(path) != entry["sha256"]:
            raise ValueError(f"Unverified research file: {relative}")
    active = base / "app/data"
    if not active.is_symlink():
        raise ValueError("Refusing to replace a real data directory")
    previous = active.resolve(strict=True)
    access = base / "data/access"
    if not (access / "access.sqlite3").is_file():
        raise FileNotFoundError("Existing invitation store must remain intact")
    if (root / "data/access").exists() or (root / "data/access").is_symlink():
        raise FileExistsError("Unexpected access directory in research release")
    (root / "data/access").symlink_to(access, target_is_directory=True)
    temporary = active.with_name(f".data-activate-{uuid4().hex}")
    temporary.symlink_to(root / "data", target_is_directory=True)
    subprocess.run(["systemctl", "stop", "golden-vector-web"], check=True)
    try:
        os.replace(temporary, active)
        subprocess.run(["systemctl", "start", "golden-vector-web"], check=True)
        subprocess.run(["systemctl", "is-active", "--quiet", "golden-vector-web"], check=True)
        # Type=simple becomes active before Python has finished importing.
        # Wait for real HTTPS readiness; don't report a transient proxy 502 as success.
        for attempt in range(20):
            try:
                with urlopen("https://golden-vector.141.147.94.215.sslip.io/healthz", timeout=5) as response:
                    if response.status == 200 and response.read() == b"ok":
                        break
            except (URLError, TimeoutError):
                pass
            time.sleep(1)
        else:
            raise RuntimeError("Website did not become healthy after publication")
    except BaseException:
        rollback = active.with_name(f".data-rollback-{uuid4().hex}")
        rollback.symlink_to(previous, target_is_directory=True)
        os.replace(rollback, active)
        subprocess.run(["systemctl", "start", "golden-vector-web"], check=False)
        raise
    result = {"active_data": str(active.resolve()), "previous_data_preserved": str(previous),
              "access_storage_unchanged": str(access), "research_files": len(publication["files"])}
    atomic_write_text(root / "activation.json", json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    print(json.dumps(activate(parser.parse_args().release), indent=2))
