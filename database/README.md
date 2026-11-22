# 数据库结构管理

`production.sql` 是全新生产环境的唯一完整建表入口，使用 MySQL 8.0+。它创建独立数据库 `copyright_workspace`，不会重置或清空既有数据，亦不包含本机密码、演示业务数据或固定生产账号。

运行项目根目录的 `python3 scripts/init_db.py`，或使用有建库权限的账号执行：

```sh
mysql -h 127.0.0.1 -u root -p < database/production.sql
```

任何数据库结构变更必须同步更新 `production.sql`。已有部署需要升级结构时，在 `migrations/` 增加按顺序执行的增量 SQL；不要以删除表后重建的方式升级。`schema_versions` 记录已应用的版本。当前为 V007。

新上传附件原件保存在 `data/attachments/`（可用 `ATTACHMENT_DIR` 配置），MySQL 保存附件元数据、提取文本和历史内联原件。备份时同时保留数据库和附件目录。应用的运行账号只需该数据库内的读写权限，建库建表可由独立维护账号执行。

官网账号密文和 `OFFICIAL_CREDENTIAL_KEY` 需分别备份。恢复数据库后使用原密钥解密。
