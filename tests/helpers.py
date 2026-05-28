import shutil
from pathlib import Path

from golden_vector.app.paths import ProjectPaths


def build_test_paths(root: Path) -> ProjectPaths:
    root.mkdir(parents=True, exist_ok=True)
    data_dir = root / "data"
    paths = ProjectPaths(
        repo_root=root,
        config_dir=root / "config",
        data_dir=data_dir,
        raw_dir=data_dir / "raw",
        intermediate_dir=data_dir / "intermediate",
        output_dir=data_dir / "output",
        manual_dir=data_dir / "manual",
        runs_dir=data_dir / "runs",
        reviews_dir=root / "reviews",
        tests_dir=root / "tests",
    )
    shutil.copytree(
        ProjectPaths.discover().config_dir,
        paths.config_dir,
        dirs_exist_ok=True,
    )
    return paths
