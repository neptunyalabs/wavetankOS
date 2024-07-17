import os
import setuptools
from setuptools import setup
import pathlib
import pkg_resources
import typing
import distutils
import distutils.text_file
from pathlib import Path
from typing import List
import platform

import re


__version__ = "0.1.0"


# Utility function to read the README file.
# Used for the long_description.  It's nice, because now 1) we have a top level
# README file and 2) it's easier to type in the README file than to put a raw
# string in below ...
def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()


# INFER REQUIREMENTS / DEPENDENCIES FROM GITHUB (GIT + EGG OK)
def _parse_requirements(filename: str) -> typing.List[str]:
    """Return requirements from requirements file."""
    # Ref: https://stackoverflow.com/a/42033122/
    canidates = distutils.text_file.TextFile(
        filename=str(pathlib.Path(__file__).with_name(filename))
    ).readlines()
    return [
        req
        for req in canidates
        if not req.startswith("git+") and req and not req.startswith("#")
    ]


def _parse_repos(filename: str) -> typing.List[str]:
    """Return requirements from requirements file."""
    # Ref: https://stackoverflow.com/a/42033122/
    candiates = (
        open(str(pathlib.Path(__file__).with_name(filename)), "r")
        .read()
        .splitlines()
    )
    # print(candiates)
    return [
        req
        for req in candiates
        if req.startswith("git+") and req and not req.startswith("#")
    ]


# To create new PIP URL Format, dependency_links ignored. Assuming egg in git+VCS source
exp = r"(?<=#egg=)(?P<module>[\w_]+)$"
#new_dep_fmt = "{module} @ {url_repo}"
new_dep_fmt = "{url_repo}"


def convert_url_fmt(git_repo):
    mtch = re.search(exp, git_repo)
    if mtch:
        assert len(mtch.groups()) == 1
        return new_dep_fmt.format(module=mtch.group(0), url_repo=git_repo)
    #else:
        #print(f"warning no match found for {git_repo}")
    return git_repo


# Parse Requirements
install_requires = _parse_requirements("requirements.txt")

new_pip_format = [
    convert_url_fmt(req) for req in _parse_repos("requirements.txt")
]
print(new_pip_format)
print(f'install requires:')
print(install_requires)
print('url format:')
print(new_pip_format)

install_requires = new_pip_format + install_requires  # add git repos


ignore_raspi = ['smbus','RPi.GPIO']
if platform.system() in ['Darwin','Windows'] or not platform.machine() in ('armv7l', 'armv6l'):
    #install_requires
    install_requires = [k for k in install_requires if not any([ig in k for ig in ignore_raspi])]


setup(
    name="waveware",
    version=__version__,
    author="Kevin Russell",
    author_email="kevin@ottermatics.com",
    description="Firmware For Neptunya Wave Tank",
    license="Neptunya Use Only",
    keywords="Neptunya Core Python Utilites",
    url="https://github.com/neptunya/waveware",
    packages=setuptools.find_packages(),
    install_requires=install_requires,
    #dependency_links = dependency_links, #DEPRICIATED PIP >19
    include_package_data=True,
    long_description=read("README.md"),
    classifiers=[
        "Development Status :: 1 - Beta",
        "Topic :: Utilities",
        "Topic :: Networking Framework",
        "Topic :: Distributed Systems",
        "License :: CONFIDENTIAL | SMARTX USE ONLY",
    ],
    entry_points={
        "console_scripts": ["wavedaq=waveware.fw_main:cli",
                            "wavedash=waveware.live_dashboard:main",
                            "wavepost=waveware.post_processing:main"]
                            #"hwstream=waveware.hardware:main"]
    },
)
