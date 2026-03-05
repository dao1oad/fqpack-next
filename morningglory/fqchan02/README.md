# ChanlunX2

## 如何编译

### Visual Studio 2019

通达信插件需要编译成32位，下面以Visual Studio 2019举例，作者用的是Visual Studio 2019社区版。

```cmd
mkdir build
cd build
cmake -G "Visual Studio 16 2019" -A Win32 ..
cmake --build . --config Release
```

大智慧64位编译

```cmd
mkdir build
cd build
cmake -G "Visual Studio 16 2019" ..
cmake --build . --config Release
```

### Visual Studio 2015 或者 Visual Studio 2017

其它编译工具请参考对应工具文档。

## 主图代码

把编译好的DLL放到通达信的T0002\dlls目录，绑定为2号函数。

tdx/缠论2号.txt的内容放到通达信公式里面。

```

## 交流

QQ群方便大家交流，但是入群设置了门槛，收取1个毛爷爷费用作为项目的持续维护，工具本身会提供给大家免费使用。有意向加群的可以通过下面的方式先联系作者。入群还能下载其他未开源的版本的源码。不会从源码编译安装也可以入群获得帮助。

- WeChat: kldcty
- QQ: 1106628276 9394908
- 微信公众号: zeroquant

## 开源版效果图

![](效果图.png)
