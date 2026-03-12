# 运行观测

## 职责

负责 runtime trace、event、原始日志与观测页面展示。

## 入口

- API：`/api/runtime/*`
- 页面：`/runtime-observability`

## 依赖

- runtime event assembler
- 本地日志 / trace 文件

## 数据流

runtime events -> assembler -> API -> UI

## 存储

观测数据是旁路产物，不是主交易事实。

## 配置

关注 dashboard 开关、刷新周期、日志目录。

## 部署/运行

可与主交易链解耦部署，但通常随 API 一起发布。

## 排障点

- trace 不生成
- API 返回空
- 页面刷新异常
