rm -rf build
rm -f *.zip
pushd "%CD%\python"
rm -rf build dist .tox *.egg-info
rm -f *.zip *.cpp *.pyd *.so
popd