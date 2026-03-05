import os
from setuptools.command.build_ext import build_ext
from setuptools import setup
from Cython.Build import cythonize
from setuptools.extension import Extension

copt = {'msvc': ['/utf-8'], 'mingw32': ['-std=c++14'], 'unix': ['-std=c++14']}
lopt = {'mingw32': []}

INSTALL_REQUIRES = ['setuptools', 'wheel']


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


def gather_cpp_files(directories):
    cpp_files = []
    for directory in directories:
        for root, _, files in os.walk(directory):
            for file in files:
                if file.endswith(".cpp"):
                    cpp_files.append(os.path.join(root, file))
    return cpp_files

directories_to_include = [
    '../cpp/chanlun',
    '../cpp/common',
    '../cpp/copilot',
    '../cpp/indicator'
]

cpp_files = gather_cpp_files(directories_to_include)

extensions = [
    Extension(
        name="fqcopilot",
        sources=cython_files + cpp_files,
        include_dirs=["../cpp"],
        language="c++",
        define_macros=[
            ("_FORCE_SWELL_WHEN_9WAVE", "1"),
            ("_GAP_COUNT_AS_ONE_BAR", "1"),
            ("_RIPPLE_REVERSE_WAVE_NO_MERGE", "1"),
        ],
    )
]

setup(
    ext_modules=cythonize(extensions),
    cmdclass={'build_ext': build_ext_subclass},
    install_requires=INSTALL_REQUIRES,
)
