from configparser import ConfigParser, ExtendedInterpolation
from json import load as json_load
from os import environ as os_environ
from pathlib import Path
from runpy import run_module
from shutil import rmtree
from sys import version as py_version, path as sys_path, stderr as sys_stderr
from typing import Final, Type
from unittest import TestSuite, TextTestRunner, defaultTestLoader

from setuptools import setup, find_namespace_packages, Command
from setuptools.errors import DistutilsError, OptionError

# CONSTANTS
# - project / sources / test paths
MAIN_FOLDER: Final[str] = 'src/main'
SRC_FOLDER: Final[str] = f'{MAIN_FOLDER}/python'
RESOURCES_FOLDER: Final[str] = f'{MAIN_FOLDER}/resources'
TEST_FOLDER: Final[str] = 'src/test'
TEST_SRC_FOLDER: Final[str] = f'{TEST_FOLDER}/python'
TEST_RESOURCES_FOLDER: Final[str] = f'{TEST_FOLDER}/resources'

# - ini file consts
PROJECT_INI_FILE_PATH: Final[str] = 'project.ini'
INIT_ENV_VAR_SECTION: Final[str] = 'ENV'
INI_PROJECT_SECTION: Final[str] = 'PROJECT'
INI_ENTRY_POINT_SECTION: Final[str] = f'{INI_PROJECT_SECTION}.ENTRY_POINTS'

# - properties default values
DEFAULT_TEST_FILE_PATTERN: Final[str] = '*[Tt]est*.py'
DEFAULT_USE_PIPENV: Final[bool] = True
DEFAULT_LONG_DESCRIPTION_FILE: Final[str] = 'README.md'
DEFAULT_LONG_DESCRIPTION_CONTENT_TYPE: Final[str] = 'text/markdown'


# SETUP FUNCTIONS
def read_file(file_path: str) -> str:
    with open(file_path) as file:
        return file.read()


def get_deps_from_pipfile(section: str = "default", pipfile_path: str = "Pipfile.lock") -> list[str]:
    with open(pipfile_path) as pipfile:
        pipfile_content = json_load(pipfile)

    return [package + detail.get('version', "") for package, detail in pipfile_content.get(section, {}).items()]


def get_deps_from_requirements(requirements_path: str = "requirements.txt") -> list[str]:
    return read_file(requirements_path).splitlines()


def get_deps(use_pipfile: bool = True) -> list[str]:
    return get_deps_from_pipfile() if use_pipfile else get_deps_from_requirements()


def load_project_ini_file(project_ini_file_path: str, environment_section: str) -> ConfigParser:
    esc_env_vars: Final[dict[str, str]] = {k: v.replace('$', '$$') for k, v in dict(os_environ).items()}
    config_parser: Final[ConfigParser] = ConfigParser(interpolation=ExtendedInterpolation())
    config_parser.read(project_ini_file_path)
    if config_parser.has_section(environment_section):
        config_parser[environment_section] = dict(config_parser[environment_section], **esc_env_vars)
    else:
        config_parser[environment_section] = esc_env_vars
    return config_parser


def find_resources_packages(resources_folder: str, excluded_packages: list[str]) -> list[str]:
    return [pkg for pkg in find_namespace_packages(where=resources_folder) if pkg not in excluded_packages]


def to_packages_dir(folder_path: str, packages: list[str]) -> dict[str, str]:
    return {pkg: Path(folder_path).joinpath(pkg.replace('.', '/')).as_posix() for pkg in packages}


def load_entry_points(config_parser: ConfigParser, entry_point_section: str) -> dict[str, list[str]] | None:
    if not config_parser.has_section(entry_point_section):
        return None

    return {k: v.splitlines() for k, v in config_parser.items(entry_point_section)}


def test_command_class_factory(test_src_folder: str, test_file_pattern: str) -> Type[Command]:
    class TestCmd(TestCommand):
        def __init__(self, dist, **kw):
            super().__init__(test_src_folder, test_file_pattern, dist, **kw)

    return TestCmd


# SETUP CLASSES
# - COMMAND CLASSES
# -- Test command
class TestCommand(Command):
    """Run all unittest in `src/test/python` by using the configured `test_file_pattern` (default: `*[Tt]est*.py`)"""

    description = \
        "Run all unittest in 'src/test/python' by using the configured `test_file_pattern` (default: '*[Tt]est*.py')"

    user_options = []

    def __init__(self, test_src_folder: str, test_file_pattern: str, dist, **kw):
        self.__test_src_folder: Final[Path] = Path(test_src_folder)
        self.__test_file_pattern: Final[str] = test_file_pattern
        super().__init__(dist, **kw)

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        # Prepare tests
        test_suite: TestSuite = self._discover()

        # - Workaround for namespace package (See: https://bugs.python.org/issue23882)
        self._add_namespace_pkg_tests_workaround(test_suite)

        # Run tests
        test_result = TextTestRunner().run(test_suite)

        if not test_result.wasSuccessful():
            raise DistutilsError('Test failed: %s' % test_result)

    def _discover(self, pkg_path: Path = None) -> TestSuite:
        test_dir: str = (pkg_path or self.__test_src_folder).as_posix()
        return defaultTestLoader.discover(start_dir=test_dir, top_level_dir=test_dir, pattern=self.__test_file_pattern)

    def _add_namespace_pkg_tests_workaround(self, default_test_suite: TestSuite) -> None:
        """Workaround for namespace package (See: https://bugs.python.org/issue23882)"""
        for pkg in find_namespace_packages(self.__test_src_folder):
            pkg_path: Path = self.__test_src_folder.joinpath(pkg.replace('.', '/'))
            if not pkg_path.joinpath('__init__.py').is_file():
                self._namespace_pkg_workaround_version_warning(pkg)
                namespace_suite: TestSuite = self._discover(pkg_path)
                if namespace_suite.countTestCases() > 0:
                    default_test_suite.addTests(namespace_suite)

    @staticmethod
    def _namespace_pkg_workaround_version_warning(namespace_package: str) -> None:
        version = py_version.split('.')
        if version:
            major: Final[int] = int(version[0])
            minor: Final[int] = int(version[1]) if len(version) > 1 else 0
            # Should be fixed in python 3.11
            if major > 3 or (major == 3 and minor >= 11):
                msg: Final[str] = "WARNING: Your python version is >= 3.11. So your tests in your namespace package" \
                                  f" '{namespace_package}' will probably run twice\n" \
                                  "   This is due to an issue that should be fixed in python 3.11." \
                                  " In this case it means issue https://bugs.python.org/issue23882 is fixed" \
                                  " and you can remove the _add_namespace_pkg_tests_workaround method from" \
                                  " TestCommand class in setup.py file"
                print(msg, file=sys_stderr)


# -- Clean command
class CleanCommand(Command):
    """Remove directories generated by the 'build' command"""
    BUILD_PATH: Final[Path] = Path('./build')
    DIST_PATH: Final[Path] = Path('./dist')
    EGG_INFO_PATTERN: Final[str] = '*.egg-info'

    description = "Remove directories generated by the 'build' command"

    user_options = [
        ('build', 'b', "Remove the 'build' directory"),
        ('dist', 'd', "Remove the 'dist' directory"),
        ('egg-info', 'e', "Remove the '.egg-info' directory"),
        ('all', 'a', '(default) remove all directories')
    ]

    def __init__(self, dist, **kw):
        self.build: bool = False
        self.dist: bool = False
        self.egg_info: bool = False
        self.all: bool = False
        super().__init__(dist, **kw)

    def initialize_options(self):
        self.build: bool = False
        self.dist: bool = False
        self.egg_info: bool = False
        self.all: bool = False

    def finalize_options(self):
        # Default action is ALL
        if not (self.build or self.dist or self.egg_info or self.all):
            self.all = True

        if self.all:
            self.build = self.dist = self.egg_info = True

    def run(self):
        print("Running clean command...")
        if self.build:
            CleanCommand._rmdir_if_exists(CleanCommand.BUILD_PATH)

        if self.dist:
            CleanCommand._rmdir_if_exists(CleanCommand.DIST_PATH)

        if self.egg_info:
            for path in Path(".").rglob(CleanCommand.EGG_INFO_PATTERN):
                CleanCommand._rmdir_if_exists(path)

        print("Clean command done")

    @staticmethod
    def _rmdir_if_exists(dir_path: Path) -> None:
        if dir_path.is_dir():
            print(" |- Remove %s directory" % dir_path)
            rmtree(dir_path)


# -- Exec command
class RunCommand(Command):
    """
    Run a python module which can be in the Maven Standard Directory Layout tree without having to configure the
    PYTHONPATH
    """

    description = "Run a python module which can be in the Maven Standard Directory Layout tree without having to " \
                  + "configure the PYTHONPATH"

    user_options = [
        ('module=', 'm', "Module to run")
    ]

    def __init__(self, dist, **kw):
        self.module: str = None
        super().__init__(dist, **kw)

    def initialize_options(self):
        self.module: str = None

    def finalize_options(self):
        if not self.module:
            raise OptionError("You must specify a module to run")

    def run(self):
        try:
            run_module(self.module, run_name='__main__')
        except Exception as e:
            raise DistutilsError(e)


# SETUP MAIN
if __name__ == '__main__':
    # Configure sys.path for commands execution
    sys_path.append(Path(SRC_FOLDER).absolute().as_posix())
    sys_path.append(Path(RESOURCES_FOLDER).absolute().as_posix())
    sys_path.append(Path(TEST_SRC_FOLDER).absolute().as_posix())
    sys_path.append(Path(TEST_RESOURCES_FOLDER).absolute().as_posix())

    # Sources and resources packages & package_dir configuration
    src_packages: Final[list[str]] = find_namespace_packages(where=SRC_FOLDER)
    resources_packages: Final[list[str]] = find_resources_packages(RESOURCES_FOLDER, src_packages)
    #   --> {'': SRC_FOLDER} workaround for pip install -e but resources & tests will not work
    #   --> see: https://github.com/pypa/setuptools/issues/230
    src_packages_dir: Final[dict[str, str]] = {'': SRC_FOLDER}
    resources_packages_dir: Final[dict[str, str]] = to_packages_dir(RESOURCES_FOLDER, resources_packages)

    # Configurable properties parser (ConfigParser)
    cfg_parser: Final[ConfigParser] = load_project_ini_file(PROJECT_INI_FILE_PATH, INIT_ENV_VAR_SECTION)

    # Execute setup
    setup(
        name=cfg_parser.get(INI_PROJECT_SECTION, 'name', fallback=None),
        version=cfg_parser.get(INI_PROJECT_SECTION, 'version', fallback=None),
        author=cfg_parser.get(INI_PROJECT_SECTION, 'author', fallback=None),
        url=cfg_parser.get(INI_PROJECT_SECTION, 'url', fallback=None),
        author_email=cfg_parser.get(INI_PROJECT_SECTION, 'email', fallback=None),
        description=cfg_parser.get(INI_PROJECT_SECTION, 'description', fallback=None),
        long_description=read_file(
            cfg_parser.get(INI_PROJECT_SECTION, 'long_description_file', fallback=DEFAULT_LONG_DESCRIPTION_FILE)
        ),
        long_description_content_type=cfg_parser.get(
            INI_PROJECT_SECTION, 'long_description_content_type', fallback=DEFAULT_LONG_DESCRIPTION_CONTENT_TYPE
        ),
        license=cfg_parser.get(INI_PROJECT_SECTION, 'license', fallback=None),
        packages=src_packages + resources_packages,
        package_dir=dict(resources_packages_dir, **src_packages_dir),
        package_data={'': ['*']},
        include_package_data=True,
        install_requires=get_deps(
            cfg_parser.getboolean(INI_PROJECT_SECTION, 'use_pipenv', fallback=DEFAULT_USE_PIPENV)
        ),
        entry_points=load_entry_points(cfg_parser, INI_ENTRY_POINT_SECTION),
        cmdclass={
            'clean': CleanCommand,
            'run': RunCommand,
            'test': test_command_class_factory(
                TEST_SRC_FOLDER,
                cfg_parser.get(INI_PROJECT_SECTION, 'test_file_pattern', fallback=DEFAULT_TEST_FILE_PATTERN)
            )
        }
    )
