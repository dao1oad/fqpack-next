# dagster配置说明

## 安装mysql

使用mysql做数据库，前提先安装mysql数据库，并且把mysql安装为windows服务。

mysql中配置好用户名（xxx）、密码（xxx），创建好数据库（dagster）。

## 配置环境

查看dagster.yaml文件，里面有env:前缀的引用的环境变量，根据自己的环境设置完成.

另外设置一个DAGSTER_HOME的环境变量, 指向此项目文件的目录. dagit和dagster-daemon启动的时候读取该环境变量所指向目录下的配置文件.

使用supervisord保活的时候，环境变量设置到program-default下的environment中.

另外注意dagster.yaml配置文件中一些目录的指向做相应的调整, 使适合自己电脑的环境.
