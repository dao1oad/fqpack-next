from setuptools import find_packages, setup

INSTALL_REQUIRES = []

setup(
    name="xtquant",
    version="2024.5.16",
    packages=find_packages(),
    install_requires=INSTALL_REQUIRES,
    package_data={'': ['*.pyd', '*.so', '*.dll', '*.yaml', '*.md', '*.ini', '*.log4cxx']},
)
