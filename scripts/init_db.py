"""Apply the single canonical production schema; never log database credentials."""
from pathlib import Path
import os
import subprocess

ROOT = Path(__file__).resolve().parent.parent


def load_env():
    values = {}
    path = ROOT / ".env.local"
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip() and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key] = value
    return {**values, **os.environ}


if __name__ == "__main__":
    env = load_env()
    name = env.get("DB_NAME", "copyright_workspace")
    if name != "copyright_workspace":
        raise SystemExit("production.sql当前使用独立数据库copyright_workspace，请保持DB_NAME一致。")
    command = ["mysql", "--host=" + env.get("DB_HOST", "127.0.0.1"),
               "--port=" + env.get("DB_PORT", "3306"), "--user=" + env.get("DB_USERNAME", "root"),
               "--default-character-set=utf8mb4"]
    result = subprocess.run(command, input=(ROOT / "database/production.sql").read_bytes(),
                            env={**os.environ, "MYSQL_PWD": env.get("DB_PASSWORD", "")})
    if result.returncode:
        raise SystemExit(result.returncode)
    print("生产建表SQL执行完成：copyright_workspace / V006")
