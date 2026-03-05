# MongoDB实时同步备份数据

## MongoDB单机开始Oplog

### 修改配置文件

找到自己的mongod.cfg文件，添加如下配置：

```
replication:
  oplogSizeMB: 1024
  replSetName: rs
```

### 初始化副本集

如果没有安装mongosh，先用scoop安装一下：

```
scoop install mongosh
```

登录数据库：

```
mongosh
```

执行初始化命令：

```
rs.initiate({ _id: 'rs', members: [{ _id: 0, host: '127.0.0.1:27017' }] })
```

有多个mongodb实例，就添加到members中。

稍后副本集就会初始化完成。

只有可以使用rs.add来添加新的节点。