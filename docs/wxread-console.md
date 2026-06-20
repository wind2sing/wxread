# wxread Console

这是在原 wxread 脚本旁边新增的轻量控制台。它不会导入或重构 main.py，而是通过环境变量和子进程运行原脚本，尽量降低以后合并 upstream 更新时的冲突。

## 功能

- 单管理员密码登录
- 粘贴微信读书 read 接口的完整 curl bash
- 全局配置 Cookie 与推送渠道
- 运行前自动刷新并保存 `wr_skey`，运行中也会捕获原脚本刷新结果
- 手动运行时输入本次阅读次数
- 每日自动运行可独立配置阅读次数
- 手动停止正在运行的阅读任务
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

## Cookie 续期

每次手动或自动运行前，控制台会先用已保存的 curl 调用微信读书 renewal 接口，拿到新的 `wr_skey` 后写回 `data/secrets.json`。这样保存的 Cookie 会随运行持续更新。

原 upstream `main.py` 启动后仍会执行自己的刷新逻辑。控制台现在通过自己的启动包装器运行原脚本：不修改 `main.py`，但会捕获原脚本调用 renewal 接口时返回的 `wr_skey`，并把这一轮运行中刷新的值继续写回 `data/secrets.json`。日志只展示类似 `qN***` 的掩码，不会输出完整密钥。

## 每日自动运行

在「配置」页面的“每日自动运行”区域：

1. 先保存有效的微信读书 curl 配置。
2. 打开自动运行开关。
3. 选择每日运行时间和自动运行阅读次数并保存。

时间固定使用北京时间 Asia/Shanghai。控制台服务或容器必须持续运行；如果计划已经启用，而当天计划时间服务未启动，稍后在同一天启动时会补跑一次。刚开启自动运行时，如果当天时间点已经过去，会从明天开始。如果触发时已有手动或自动任务运行，当天的自动任务会跳过，不重复执行。

自动任务会进入同一份运行历史，并标记为“自动”。

## 手动运行与停止

在总览页输入本次阅读次数后点击“立即运行”。每次约 30 秒，例如 40 次约 20 分钟。

运行中可以在总览页或运行详情页点击“停止运行”。停止后本次运行会标记为 cancelled，并在脱敏日志中记录“用户手动停止运行”。

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
