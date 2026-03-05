mkdir %USERPROFILE%\.jupyter
echo y | jupyter lab --generate-config
cp -f %~dp0..\jupyter_server_config.json %USERPROFILE%\.jupyter\jupyter_server_config.json
jupyter lab --port 88 --no-browser --notebook-dir G:\vol\notebook