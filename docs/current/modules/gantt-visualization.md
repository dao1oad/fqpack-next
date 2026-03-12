# 甘特图展示

## 职责

负责通用甘特图读模型查询与页面展示。

## 入口

- API：`freshquant.rear.gantt.routes`
- 前端：Gantt 系列页面与 `GanttHistory`

## 依赖

- Gantt 读模型
- Dagster 产物

## 数据流

read model -> gantt routes -> Vue views

## 存储

依赖读模型集合，不直接读取原始写模型。

## 配置

关注查询窗口、plate / stock 视图与图例语义。

## 部署/运行

改动后通常同时影响 API 与 Web UI。

## 排障点

- 接口为空
- 图例错位
- 视图切换异常
