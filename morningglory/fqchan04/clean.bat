rm -rf build
rm -rf .xmake
rm -rf wheelhouse
pushd "%CD%\python"
rm -rf build dist .tox *.egg-info
rm -f *.cpp *.pyd *.so
popd
