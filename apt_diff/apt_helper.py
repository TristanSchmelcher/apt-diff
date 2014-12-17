# Copyright (c) 2010 Tristan Schmelcher <tristan_schmelcher@alumni.uwaterloo.ca>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301,
# USA.

"""Helpers that wrap APT functionality."""

import apt
import apt_pkg
import os
import sys

def initialize():
  """Initialize the apt_pkg module. Must be called before using anything else in
     this class."""
  apt_pkg.init_config()
  apt_pkg.init_system()

def set_option(name, value):
  """Set an arbitrary APT option."""
  apt_pkg.config.set(name, value)

class AptHelper:
  """Wrapper for the APT cache's state and package downloading capability."""

  def __init__(self):
    # Have to explicitly create an unused OpProgress or else Cache()
    # does text progress logging by default.
    self.__cache = apt_pkg.Cache(apt.progress.base.OpProgress())
    self.__pkg_records = apt_pkg.PackageRecords(self.__cache)
    self.__dep_cache = apt_pkg.DepCache(self.__cache)
    self.__src_list = apt_pkg.SourceList()
    self.__src_list.read_main_list()

  def is_installed(self, pkgname):
    """Checks if the given package is installed."""
    return pkgname in self.__cache and bool(self.__cache[pkgname].current_ver)

  def fetch_archive(self, pkgname):
    """Downloads the archive for the named package's currently-installed version
       and returns the path to the downloaded file."""
    if pkgname not in self.__cache:
      print >> sys.stderr, ("Can't fetch package %s because there is no record "
          "of it in the archives" % pkgname)
      return None
    pkg = self.__cache[pkgname]
    ver = pkg.current_ver
    try:
      if ver:
        # Package is installed. Diff against the same version.
        # First check if this version is available in the repo.
        available = False
        for package_file, _ in ver.file_list:
          if package_file.not_source == 0:
            available = True
            break
        if not available:
          # Nope.
          print >> sys.stderr, ("Can't fetch package %s because the installed "
                                "version (%s) is not available in the archives"
                                % (pkgname, ver.ver_str))
          return None
        self.__dep_cache.set_candidate_ver(pkg, ver)
        self.__dep_cache.set_reinstall(pkg, True)
      else:
        # Package is not installed. Diff against the version that would be
        # installed if the user were to install the package.
        ver = self.__dep_cache.get_candidate_ver(pkg)
        if not ver:
          print >> sys.stderr, ("Can't fetch package %s because it is not "
                                "installed and there is no installation "
                                "candidate available in the archives" % pkgname)
          return None
        self.__dep_cache.mark_install(pkg, False)
      fetcher = apt_pkg.Acquire()
      pkg_man = apt_pkg.PackageManager(self.__dep_cache)
      # Return value from this seems to be meaningless, since I get
      # ResultFailed even when everything works.
      pkg_man.get_archives(fetcher, self.__src_list, self.__pkg_records)
      fetcher.run()
      # There may be multiple items in the case of a multi-arch package where
      # both architectures are installed (they must be reinstalled in tandem).
      # Scan for the one we want.
      for item in fetcher.items:
        if item.destfile:
          filename = os.path.basename(item.destfile)
          parts = filename.rsplit(".", 1)
          if len(parts) != 2:
            raise Exception("Unrecognized package file name format " + filename)
          parts = parts[0].split("_")
          if len(parts) != 3:
            raise Exception("Unrecognized package file name format " + filename)
          if parts[0] == pkg.name and parts[2] == ver.arch:
            # Found it.
            if item.status != apt_pkg.AcquireItem.STAT_DONE:
              print >> sys.stderr, ("Failed to fetch package %s: %s" %
                                    (pkgname, item.error_text))
              return None
            return item.destfile
      # We didn't find any downloaded file that looks like the package.
      raise Exception("Couldn't find package file for %s in fetcher items list"
                      % pkgname)
    except Exception, e:
      print >> sys.stderr, "Failed to fetch package %s: %s: %s" % (pkgname,
                                                                   type(e), e)
      return None
    finally:
      # Revert the change (so as to not do a cumulative fetch in each
      # iteration).
      if ver:
        self.__dep_cache.set_reinstall(pkg, False)
      else:
        self.__dep_cache.mark_delete(pkg)
