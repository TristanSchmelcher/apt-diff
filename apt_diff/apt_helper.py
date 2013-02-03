# A helper class that provides APT package fetching functionality.
#
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

import apt
import apt_pkg
import os
import sys

def initialize():
  apt_pkg.InitConfig()
  apt_pkg.InitSystem()

def set_option(name, value):
  apt_pkg.Config.Set(name, value)

class AptHelper:
  def __init__(self):
    # Have to explicitly create an unused OpProgress or else GetCache()
    # does text progress logging by default.
    self.__cache = apt_pkg.GetCache(apt.progress.OpProgress())
    self.__pkg_records = apt_pkg.GetPkgRecords(self.__cache)
    self.__dep_cache = apt_pkg.GetDepCache(self.__cache)
    self.__src_list = apt_pkg.GetPkgSourceList()
    self.__src_list.ReadMainList()

  def is_installed(self, pkgname):
    return pkgname in self.__cache and bool(self.__cache[pkgname].CurrentVer)

  def fetch_archive(self, pkgname):
    """Downloads the archive for the named package's currently-installed version
       and returns the path to the downloaded file."""
    if pkgname not in self.__cache:
      print >> sys.stderr, ("Can't fetch package %s because there is no record "
          "of it in the archives" % pkgname)
      return None
    pkg = self.__cache[pkgname]
    ver = pkg.CurrentVer
    try:
      if ver:
        # Package is installed. Diff against the same version.
        # First check if this version is available in the repo.
        available = False
        for package_file, index in ver.FileList:
          if package_file.NotSource == 0:
            available = True
            break
        if not available:
          # Nope.
          print >> sys.stderr, ("Can't fetch package %s because the installed "
              "version (%s) is not available in the archives"
              % (pkgname, ver.VerStr))
          return None
        self.__dep_cache.SetCandidateVer(pkg, ver)
        self.__dep_cache.SetReInstall(pkg, True)
      else:
        # Package is not installed. Diff against the version that would be
        # installed if the user were to install the package.
        ver = self.__dep_cache.GetCandidateVer(pkg)
        if not ver:
          print >> sys.stderr, ("Can't fetch package %s because it is not "
              "installed and there is no installation candidate available in "
              "the archives" % pkgname)
          return None
        self.__dep_cache.MarkInstall(pkg, False)
      fetcher = apt_pkg.GetAcquire()
      pm = apt_pkg.GetPackageManager(self.__dep_cache)
      # Return value from this seems to be meaningless, since I get
      # ResultFailed even when everything works.
      pm.GetArchives(fetcher, self.__src_list, self.__pkg_records)
      fetcher.Run()
      # There may be multiple items in the case of a multi-arch package where
      # both architectures are installed (they must be reinstalled in tandem).
      # Scan for the one we want.
      for item in fetcher.Items:
        if item.DestFile:
          filename = os.path.basename(item.DestFile)
          parts = filename.rsplit(".", 1)
          if len(parts) != 2:
            raise Exception("Unrecognized package file name format " + filename)
          parts = parts[0].split("_")
          if len(parts) != 3:
            raise Exception("Unrecognized package file name format " + filename)
          if parts[0] == pkg.Name and parts[2] == ver.Arch:
            # Found it.
            if item.Status != apt_pkg.AcquireItem.StatDone:
              print >> sys.stderr, ("Failed to fetch package %s: %s" %
                  (pkgname, item.ErrorText))
              return None
            return item.DestFile
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
        self.__dep_cache.SetReInstall(pkg, False)
      else:
        self.__dep_cache.MarkDelete(pkg)
