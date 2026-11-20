"""Serve the production jar (with Vue assets) and the Python assistant."""
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from init_db import ROOT, load_env

env = load_env()
java = str(Path(env["JAVA_HOME"]) / "bin/java") if env.get("JAVA_HOME") else "java"
jar = ROOT / "backend/target/copyright-workspace-1.0.0.jar"
if not jar.exists():
    raise SystemExit("请先运行python3 scripts/build.py")
for port in (8080, 8090):
    with socket.socket() as sock:
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit(f"端口{port}已占用，请先停止对应服务。")
children = []
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
try:
    children.append(subprocess.Popen([str(ROOT / "ai-service/.venv/bin/python"), "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8090"], cwd=ROOT / "ai-service", env=env, start_new_session=True))
    children.append(subprocess.Popen([java, "-jar", str(jar)], cwd=ROOT, env=env, start_new_session=True))
    print("生产工作空间：http://127.0.0.1:8080", flush=True)
    while all(p.poll() is None for p in children):
        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    for p in children:
        if p.poll() is None:
            os.killpg(p.pid, signal.SIGTERM)
    for p in children:
        try:
            p.wait(timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
