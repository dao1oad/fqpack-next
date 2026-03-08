import os
from pathlib import Path

from Cython.Build import cythonize
from pybind11.setup_helpers import Pybind11Extension
from setuptools import setup
from setuptools.command.build_ext import build_ext
from setuptools.extension import Extension

ROOT = Path(__file__).resolve().parent
DEFINE_MACROS = [
    ("_FORCE_SWELL_WHEN_9WAVE", "1"),
    ("_GAP_COUNT_AS_ONE_BAR", "1"),
    ("_RIPPLE_REVERSE_WAVE_NO_MERGE", "1"),
]
COMPILE_ARGS_BY_COMPILER: dict[str, dict[str, list[str]]] = {
    "msvc": {
        "fqcopilot": ["/utf-8"],
        "fullcalc": ["/utf-8"],
    },
    "mingw32": {
        "fqcopilot": ["-std=c++14"],
        "fullcalc": [],
    },
    "unix": {
        "fqcopilot": ["-std=c++14"],
        "fullcalc": [],
    },
}
LINK_ARGS_BY_COMPILER: dict[str, dict[str, list[str]]] = {
    "mingw32": {"fqcopilot": [], "fullcalc": []}
}

INSTALL_REQUIRES = ["setuptools", "wheel"]


def _resolve_extension_args(
    arg_map: dict[str, dict[str, list[str]]],
    compiler_type: str,
    extension_name: str,
) -> list[str]:
    compiler_args = arg_map.get(compiler_type, {})
    return list(compiler_args.get(extension_name, []))


class build_ext_subclass(build_ext):
    def build_extensions(self):
        compiler_type = getattr(self.compiler, "compiler_type", "")
        for extension in self.extensions:
            extension.extra_compile_args = _resolve_extension_args(
                COMPILE_ARGS_BY_COMPILER, compiler_type, extension.name
            )
            link_args = _resolve_extension_args(
                LINK_ARGS_BY_COMPILER, compiler_type, extension.name
            )
            if link_args:
                extension.extra_link_args = link_args
        build_ext.build_extensions(self)


cython_files = ["*.pyx"]


def gather_cpp_files(directories, *, exclude_dirs=None):
    exclude_roots = {(ROOT / directory).resolve() for directory in (exclude_dirs or [])}
    cpp_files = []
    for directory in directories:
        base_dir = (ROOT / directory).resolve()
        for root, _, files in os.walk(base_dir):
            root_path = Path(root).resolve()
            if any(
                root_path == exclude or exclude in root_path.parents
                for exclude in exclude_roots
            ):
                continue
            for file in files:
                if file.endswith(".cpp"):
                    cpp_files.append(os.path.relpath(os.path.join(root, file), ROOT))
    return cpp_files


fqcopilot_cpp_files = gather_cpp_files(
    [
        "../cpp/chanlun",
        "../cpp/common",
        "../cpp/copilot",
        "../cpp/indicator",
    ]
)
fullcalc_cpp_files = [
    os.path.relpath(ROOT / "../cpp/func_set.cpp", ROOT)
] + gather_cpp_files(
    [
        "../fullcalc",
        "../cpp/common",
        "../cpp/copilot",
        "../cpp/indicator",
        "../../fqchan04/cpp/chanlun",
    ]
)

extensions = [
    Extension(
        name="fqcopilot",
        sources=cython_files + fqcopilot_cpp_files,
        include_dirs=[str((ROOT / "../cpp").resolve())],
        language="c++",
        define_macros=DEFINE_MACROS,
    ),
    Pybind11Extension(
        name="fullcalc",
        sources=fullcalc_cpp_files,
        include_dirs=[
            str((ROOT / "../fullcalc").resolve()),
            str((ROOT / "../cpp").resolve()),
            str((ROOT / "../../fqchan04/cpp").resolve()),
        ],
        language="c++",
        define_macros=DEFINE_MACROS + [("MAKE_X64", "1")],
        cxx_std=17,
    ),
]

setup(
    ext_modules=cythonize([extensions[0]]) + [extensions[1]],
    cmdclass={"build_ext": build_ext_subclass},
    install_requires=INSTALL_REQUIRES,
)
