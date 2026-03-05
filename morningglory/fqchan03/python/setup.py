from distutils.command.build_ext import build_ext
from distutils.core import setup

from Cython.Build import cythonize
from setuptools.extension import Extension

copt = {'msvc': [], 'mingw32': ['-std=c++11']}
lopt = {'mingw32': []}

INSTALL_REQUIRES = []


class build_ext_subclass(build_ext):
    def build_extensions(self):
        c = self.compiler.compiler_type
        print("compiler type:", c)
        if copt.get(c):
            for e in self.extensions:
                e.extra_compile_args = copt[c]
        if lopt.get(c):
            for e in self.extensions:
                e.extra_link_args = lopt[c]
        build_ext.build_extensions(self)


cython_files = ["*.pyx"]

extensions = [
    Extension(
        name="fqchan03",
        sources=cython_files,
        include_dirs=[
            "../cpp",
        ],
        language="c++",
    )
]

setup(
    name="fqchan03",
    version="2025.2.1",
    ext_modules=cythonize(extensions),
    cmdclass={'build_ext': build_ext_subclass},
    install_requires=INSTALL_REQUIRES,
)
