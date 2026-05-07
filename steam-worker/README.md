# Steam Data API (Railway)

后端通过 Steam Web API 获取个人资料、游戏时长 Top10 和白金游戏。Steam API Key 只放在服务端环境变量中，不要写进前端或仓库。

## 本地运行

```bash
cd steam-worker
STEAM_API_KEY=你的密钥 npm start
# 访问 http://localhost:8787/all
```

## API 端点

| 端点 | 说明 |
|------|------|
| `/all` | 一次性获取 profile + games + achievements（推荐） |
| `/games` | 游戏库统计，包含 `top10` |
| `/achievements` | 白金游戏 |
| `/profile` | Steam 公开资料 |

## Railway 部署后端

1. 在 Railway 新建服务，Root Directory 选择 `steam-worker`。
2. 设置环境变量：
   - `STEAM_API_KEY`：你的 Steam Web API Key
   - `STEAM_ID`：可选，默认当前 Steam ID
3. Start Command 使用 `npm start`。
4. 使用 Railway 生成的服务域名作为前端的 `STEAM_API`。

## Vercel 部署前端

1. 将仓库导入 Vercel。
2. 当前前端是静态 `index.html`，Root Directory 保持仓库根目录即可。
3. 如果 Railway 后端域名变化，更新 `index.html` 中的 `STEAM_API` 后重新部署。

## Steam 隐私要求

Steam 个人资料和游戏详情需要公开；如果某个游戏成就数据不可见，后端会跳过该游戏。
