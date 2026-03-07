# JupyterLab配置

主要是给 JupyterLab 配置使用哪个 Python 环境。

> 当前目标仓运行环境已统一为项目根目录 `.venv`，不再推荐使用旧的 `py39` / conda 环境作为默认口径。

首先激活 FreshQuant 的项目虚拟环境：

```
D:\fqpack\freshquant-2026.2.23\.venv\Scripts\activate
```

或者直接使用项目 Python：

```
D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m ipykernel install --user --name=freshquant --display-name="freshquant"
```

如果已经激活了 `.venv`，再把当前环境添加为 ipykernel：

```
python -m ipykernel install --user --name=freshquant --display-name="freshquant"
```

安装完成后，JupyterLab 里选择 `freshquant` 内核即可。
