# Docker常用说明

## Docker常用命令

```
# 查看镜像列表
docker images

# 删除单个镜像
docker rmi image-id

# 删除所有镜像
docker rmi $(docker images -q)

# 查看运行中的容器
docker ps

# 查看所有容器
docker ps -a

# 停止单个容器
docker stop container-id

# 停止所有容器
docker stop $(docker ps -a -q)

# 删除单个容器
docker rm container-id

# 删除所有容器
docker rm $(docker ps -a -q)

# 清理没有使用的镜像
docker image prune -a -f

# 清楚缓存等
docker system prune -a -f
```

## Docker国内镜像地址
```
{
    "registry-mirrors": [
        "https://docker.1panel.live",
        "https://hub.rat.dev",
        "https://docker.m.daocloud.io",
        "https://docker.actima.top",
        "https://atomhub.openatom.cn",
        "https://docker.nastool.de",
        "https://dockerpull.org",
        "https://docker.1ms.run"
    ]
}
```
