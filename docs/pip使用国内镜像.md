# pip使用国内镜像

国内源：

清华：<https://pypi.tuna.tsinghua.edu.cn/simple>

阿里云：<http://mirrors.aliyun.com/pypi/simple/>

中国科技大学 <https://pypi.mirrors.ustc.edu.cn/simple/>

华中理工大学：<http://pypi.hustunique.com/>

山东理工大学：<http://pypi.sdutlinux.org/>

豆瓣：<https://pypi.douban.com/simple/>

note：新版ubuntu要求使用https源，要注意。

临时使用：

可以在使用pip的时候加参数-i https://pypi.tuna.tsinghua.edu.cn/simple

例如：pip install -i https://pypi.tuna.tsinghua.edu.cn/simple pyspider，这样就会从清华这边的镜像去安装pyspider库。

永久修改，一劳永逸：

Linux下，修改 ~/.pip/pip.conf (没有就创建一个文件夹及文件。文件夹要加“.”，表示是隐藏文件夹)

内容如下：

[global]
index-url = https://pypi.tuna.tsinghua.edu.cn/simple

[install]
trusted-host=pypi.tuna.tsinghua.edu.cn

windows下，直接在user目录中创建一个pip目录，再新建文件pip.ini。（例如：C:\Users\WQP\pip\pip.ini）内容同上。
