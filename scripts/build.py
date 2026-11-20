"""Produce the deployable Spring Boot jar containing the current Vue build."""
from pathlib import Path
import shutil
import subprocess
from init_db import ROOT, load_env

env = load_env()
subprocess.run(["npm", "run", "build"], cwd=ROOT / "frontend", env=env, check=True)
target = ROOT / "backend/src/main/resources/static"
if target.exists():
    shutil.rmtree(target)
shutil.copytree(ROOT / "frontend/dist", target)
subprocess.run(["mvn", "-q", "clean", "package"], cwd=ROOT / "backend", env=env, check=True)
print("生产构建完成：backend/target/copyright-workspace-1.0.0.jar")
