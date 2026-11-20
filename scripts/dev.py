"""Start Java, Vue and Python together. Only stop child processes owned by this run."""
from pathlib import Path
import os
import signal
import socket
import subprocess
import sys
import time
from init_db import ROOT, load_env


def main():
    env = load_env()
    java_home = env.get("JAVA_HOME", "")
    java = str(Path(java_home) / "bin/java") if java_home else "java"
    py = ROOT / "ai-service/.venv/bin/python"
    jars = list((ROOT / "backend/target").glob("copyright-workspace-*.jar"))
    if not py.exists() or not jars or not (ROOT / "frontend/node_modules").exists():
        raise SystemExit("请先按README安装依赖并构建Java项目。")
    for port in (8080, 8090, 5173):
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                raise SystemExit(f"端口{port}已被占用；请先停止对应服务，避免启动重复实例。")
    run = ROOT / ".run"
    run.mkdir(exist_ok=True)
    children, logs = [], []
    commands = [("assistant", [str(py), "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8090"], ROOT / "ai-service"),
                ("backend", [java, "-jar", str(jars[0])], ROOT),
                ("frontend", ["npm", "run", "dev", "--", "--port", "5173"], ROOT / "frontend")]
    try:
        for name, cmd, cwd in commands:
            log = open(run / f"{name}.log", "w")
            logs.append(log)
            children.append(subprocess.Popen(cmd, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True))
        print("工作空间：http://127.0.0.1:5173", flush=True)
        print("日志目录：.run/；按Ctrl+C停止本次启动的服务。", flush=True)
        while True:
            for child in children:
                if child.poll() is not None:
                    raise SystemExit("有服务退出，请检查.run/中的日志。")
            time.sleep(1)
    finally:
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
        for child in children:
            try:
                child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
        for log in logs:
            log.close()


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        main()
    except KeyboardInterrupt:
        pass
