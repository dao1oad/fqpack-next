rm -rf build
rm -rf .xmake
pushd "%CD%\python"
rm -rf build dist .tox *.egg-info
rm -f *.cpp *.pyd *.so
popd
