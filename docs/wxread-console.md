# wxread Console

这是在原 wxread 脚本旁边新增的轻量控制台。它不会导入或重构 main.py，而是通过环境变量和子进程运行原脚本，尽量降低以后合并 upstream 更新时的冲突。

## 功能

- 单管理员密码登录
- 粘贴微信读书 read 接口的完整 curl bash
- 配置 READ_NUM 与推送渠道
- 手动运行原 main.py
- SQLite 保存运行状态、耗时和完成进度
- 查看运行历史与脱敏日志
- 同一时间只允许一个任务运行

## 本地启动

建议使用虚拟环境：

    python -m venv .venv
    .venv/bin/python -m pip install -r requirements-console.txt

设置环境变量并启动：

    WXREAD_CONSOLE_ENV=development \
    WXREAD_ADMIN_PASSWORD=change-me \
    WXREAD_SESSION_SECRET=change-me-too \
    .venv/bin/python -m wxread_console

打开 http://127.0.0.1:8080。

## Docker 部署

构建独立镜像：

    docker build -f Dockerfile.console -t wxread-console .

启动：

    docker run -d \
      --name wxread-console \
      -p 8080:8080 \
      -v wxread-data:/app/data \
      -e WXREAD_ADMIN_PASSWORD='请替换为强密码' \
      -e WXREAD_SESSION_SECRET='请替换为随机长字符串' \
      --restart unless-stopped \
      wxread-console

## 环境变量

必须配置：

- WXREAD_ADMIN_PASSWORD：控制台管理员密码
- WXREAD_SESSION_SECRET：Flask session 签名密钥

可选：

- WXREAD_DATA_DIR：数据目录，默认仓库内 data/；容器内默认 /app/data
- WXREAD_RUN_TIMEOUT_SECONDS：单次运行超时秒数，默认 14400
- WXREAD_CONSOLE_ENV：development 或 production

微信读书 curl、READ_NUM 和推送 token 可登录控制台后填写，不需要再手工编辑 config.py。

## 公网安全

- production 模式的登录 Cookie 默认带 Secure 属性，请通过 HTTPS 访问。
- 建议使用 Nginx、Caddy 或 Cloudflare Tunnel/Access 提供 HTTPS。
- 不要把 data/、secrets.json、SQLite 文件或完整 curl 提交到 Git。
- 不要在 issue、聊天记录或普通日志中粘贴完整 curl。
- 请定期备份 data/，备份文件同样包含敏感配置。

## 同步原项目更新

如果当前仓库只有自己的 origin，可添加原项目为 upstream：

    git remote add upstream https://github.com/findmover/wxread.git
    git fetch upstream
    git merge upstream/main

控制台代码集中在 wxread_console/，并使用独立 Dockerfile.console；原 main.py、config.py、push.py、Dockerfile 和 GitHub Actions 流程仍可按原方式使用。
