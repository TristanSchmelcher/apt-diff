#!/usr/bin/python

from distutils.core import setup

setup(name = "apt-diff",
      version = "0.9.1",
      description = "Diff filesystem content against the APT installation sources.",
      maintainer = "Tristan Schmelcher",
      maintainer_email = "tristan_schmelcher@alumni.uwaterloo.ca",
      url = "https://github.com/TristanSchmelcher/apt-diff",
      packages = ['apt_diff'],
      license = "GPL-2")
