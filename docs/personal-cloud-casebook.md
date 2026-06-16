# 个人云端案例库设计

这一阶段的目标是先把个人版打穿：公开用户可以免费体验，本地保存和导出案例；老王自己输入个人口令后，可以把长期复盘案例同步到服务器。

## 当前形态

- 前端仍然是静态 H5。
- 本地案例继续保存在浏览器 `localStorage`。
- 云端案例通过 `/api/cases` 保存到服务器 SQLite。
- 服务器只保存口令哈希，不保存明文口令。
- 未输入口令的用户不能访问云端案例库。

## API

`GET /api/health`

用于确认服务是否存活。

`GET /api/cases`

需要请求头：

```http
Authorization: Bearer <个人口令>
```

返回云端所有案例。

`POST /api/cases`

需要请求头：

```http
Authorization: Bearer <个人口令>
Content-Type: application/json
```

请求体：

```json
{
  "cases": []
}
```

按案例 `id` 新增或更新。

## 商业化预留

这个实现先不做账号体系，但保留了升级路线：

- 单口令可以替换成多用户账号。
- SQLite 可以迁移到 PostgreSQL 或 MySQL。
- 案例表可以增加 `user_id`。
- 打赏入口可以从文案升级成二维码或支付链接。
- 后续可以增加公开案例、老师模式、付费复盘、学习课程。

## 备份

核心数据文件：

```text
/var/lib/liuren/cases.db
```

早期备份只需要定期复制这个文件。
