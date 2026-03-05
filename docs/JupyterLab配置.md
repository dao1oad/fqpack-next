# JupyterLab配置

主要是给JupyterLab配置使用哪个Python环境

首先激活freshquant的运行环境，根据不同的情况而已。比如virtualenv：

```
D:\py39\Scripts\activate
```

或者conda：

```
conda activate py39
```

然后把当前环境添加为ipykernel

```
python -m ipykernel install --user --name=freshquant --display-name="freshquant"
```