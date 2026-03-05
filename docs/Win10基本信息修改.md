用PowerShell修改计算机名

方法一：
```
Rename-Computer -NewName
```

设置静态ip：
```
netsh interface ip set addr "本地连接" static 192.168.0.1 255.255.255.0 192.168.0.254 1

netsh interface ip set dns "本地连接" static 202.103.24.68

netsh interface ip add dns "本地连接" 8.8.8.8      #手动设置多个dns
```

设置动态ip：
```
netsh interface ip set addr "本地连接" dhcp

netsh interface ip set dns "本地连接" dhcp
```

加域：
```
add-computer -domain "域名" -cred "域名\授权用户" -passthru
```

退域：
```
remove-computer -credential "域名\授权用户" -passthru -verbose; restart-computer
```
