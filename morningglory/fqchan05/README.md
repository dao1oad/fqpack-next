# 缠中说缠插件(fqchan01)

## 如何编译

### 编译前提

#### 安装vcpkg

```
scoop install vcpkg
```

安装后设置环境变量，VCPKG_ROOT指向安装的根目录，如下是我的安装目录。

```
set VCPKG_ROOT=C:\Users\xxxxxxxx\scoop\apps\vcpkg\current
setx VCPKG_ROOT C:\Users\xxxxxxxx\scoop\apps\vcpkg\current
```

#### 使用vcpkg安装poco

```
vcpkg install poco
```

### Visual Studio 2019 或者 Visual Studio 2022

编译通达信/大智慧/交易师等32位版本用

```cmd
cmake -A Win32 -B build32
cmake --build build32 --config Release
```

编译金字塔64位版本用

```cmd
cmake . -B build64
cmake --build build64 --config Release
```

编译大智慧64位版本用

```cmd
cmake -D MAKE_DZH=1 . -B build64
cmake --build build64 --config Release
```

## 主图代码

把编译好的DLL放到通达信的T0002\dlls目录，绑定为5号函数。

tdx/CL05.txt的内容放到通达信公式里面。

dzh/CL05.txt的内容可以在大智慧/金字塔/交易师等软件中使用
