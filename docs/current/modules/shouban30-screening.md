# 首板筛选

## 职责

负责首板标的筛选、盘后快照与页面工作区。

## 入口

- 前端：Shouban30 页面
- 后端：gantt / shouban30 相关接口与服务

## 依赖

- read model
- 股票池 / pre_pool / blk 同步逻辑

## 数据流

snapshot / filters -> routes -> page workspace

## 存储

依赖盘后快照和读模型投影。

## 配置

关注筛选按钮、候选/通过/失败字段语义。

## 部署/运行

改动后通常影响 API、Dagster、Web UI。

## 排障点

- 快照缺失
- 筛选条件失效
- pool / blk 同步不一致
