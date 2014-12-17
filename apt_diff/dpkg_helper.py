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

"""Helper routines for interacting with dpkg."""

import os
import shutil
import subprocess
import sys


_DPKG_INFO_DIR = "/var/lib/dpkg/info/"
_LIST_FILE_EXT = ".list"
_LIST_FILE_EXT_LEN = len(_LIST_FILE_EXT)
_MD5SUMS_FILE_EXT = ".md5sums"
_MD5SUMS_FILE_EXT_LEN = len(_MD5SUMS_FILE_EXT)
_MORE_PACKAGES = "..."
_MAX_DIR_OWNERS_TO_RECORD = 3


def extract_archive(archive_path, destdir):
  """Extracts an archive file on disk to the given directory."""
  if os.path.lexists(destdir):
    # May have been extracted during a previous run. Re-extract cleanly.
    shutil.rmtree(destdir)
  with open(os.devnull) as devnull:
    subprocess.check_call(["dpkg-deb", "-x", archive_path, destdir],
                          stdin = devnull)


def expand_package_to_leaf_paths(pkgname):
  """Expands a package name to all leaf paths owned by it.

  Returns an array of all leaf paths owned by pkgname. A leaf path is defined as
  a path for which the package does not own any subpath.
  """
  listpath = _DPKG_INFO_DIR + pkgname + _LIST_FILE_EXT
  paths = []
  if not os.path.lexists(listpath):
    return paths
  lines = []
  with open(listpath) as f:
    for line in f:
      line = line.rstrip("\n")
      if line == "/.":
        line = "/"
      lines.append(line)
  lines.sort()
  lines.reverse()
  last = None
  for line in lines:
    if last and last.startswith(line):
      continue
    last = line
    paths.append(line)
  paths.reverse()
  return paths


def _path_components(normpath):
  """Gets a list of the path components in a normalized path."""
  if normpath == "/":
    # The code below would return [''], which is not what we want for the root.
    return []
  else:
    return normpath.lstrip("/").split("/")


class PathFilter:
  """A PathFilter represents a set of paths to filter.

  The paths that will be diff'ed are specified as an argument. The filter
  includes precisely all paths that are equal or are subpaths.
  """

  def __init__(self, paths):
    # We store the filter as a tree of the outermost paths (i.e., paths that are
    # not subpaths of any other path in the filter). Non-outermost paths are
    # superfluous because all subpaths are automatically included.
    # First identify the outermost paths.
    paths = sorted(paths)
    last = None
    outermost_paths = []
    for p in paths:
      if last and p.startswith(last):
        continue
      last = p
      outermost_paths.append(p)
    # Now build the tree.
    if not outermost_paths:
      # Special case where no paths were specified.
      self.__paths = None
      return
    self.__paths = {}
    for p in outermost_paths:
      current = self.__paths
      for component in _path_components(p):
        if component not in current:
          next_dict = current[component] = {}
        else:
          next_dict = current[component]
        current = next_dict

  def includes(self, p):
    """Checks if this filter includes the given path."""
    current = self.__paths
    if current == None:
      # Special case where no paths were specified.
      return False
    for component in _path_components(p):
      if component not in current:
        # If no more components, then this is an included path and we're a
        # subpath of it. Otherwise, we're not an included path.
        return not current
      current = current[component]
    # If we found all nodes, then either this is a parent of an included path or
    # exactly equal to an included path. The latter is the case whenever there
    # are no more children.
    return not current


class PackageInfo:
  """A PackageInfo represents the per-package info for a FilesystemNode."""

  def __init__(self):
    self._md5sum = None
    self._conffile_status = None

  def md5sum(self):
    """Gets the md5sum specified in the .md5sums file, if any."""
    return self._md5sum

  def conffile_status(self):
    """Gets the conffile status, if any.

    The conffile status is specified in the Conffiles field of the dpkg status
    file. The return value is None if there is no Conffiles entry for this file
    in this package, else a 2-tuple of md5sum and a boolean obsolete flag.
    """
    return self._conffile_status


class FilesystemNode:
  """A FilesystemNode is a representation of the dpkg info for a path."""

  def __init__(self):
    self.__owners = []
    self.__children = {}
    self.__package_info = {}

  def _record_owner(self, pkgname):
    if self.__children and len(self.__owners) >= _MAX_DIR_OWNERS_TO_RECORD:
      # Cap the number of recorded owners for directories since that info is
      # only used for logging and there could be thousands.
      if len(self.__owners) == _MAX_DIR_OWNERS_TO_RECORD:
        self.__owners.append(_MORE_PACKAGES)
      return
    self.__owners.append(pkgname)

  def _add_child(self, name):
    if not self.__children and len(self.__owners) > _MAX_DIR_OWNERS_TO_RECORD:
      # This is now a directory, so discard owner info above the cap.
      del self.__owners[_MAX_DIR_OWNERS_TO_RECORD:]
      self.__owners.append(_MORE_PACKAGES)
    child = self.__children[name] = FilesystemNode()
    return child

  def _get_package_info(self, pkgname):
    if pkgname in self.__package_info:
      return self.__package_info[pkgname]
    pkg_info = self.__package_info[pkgname] = PackageInfo()
    return pkg_info

  def owners(self):
    """Gets the owners as an array."""
    return self.__owners

  def owners_str(self):
    """Gets the owners as a human-readable string."""
    if self.__owners:
      return ", ".join(self.__owners)
    else:
      return "no package"

  def children(self):
    """Gets the map of child nodes."""
    return self.__children

  def package_info(self):
    """Gets the map of package information."""
    return self.__package_info


def _bad_conffiles_line(package, line):
  print >> sys.stderr, ("Got malformed Conffiles line for package %s: %s" %
      (package, line))


class DpkgHelper:
  """Class for loading dpkg state."""

  def __init__(self, path_filter):
    self.__root = FilesystemNode()
    self.__path_filter = path_filter
    self.__load()

  def __load(self):
    # Load info from the dpkg info directory.
    for filename in os.listdir(_DPKG_INFO_DIR):
      if filename.endswith(_LIST_FILE_EXT):
        pkgname = filename[:-_LIST_FILE_EXT_LEN]
        self.__load_list(_DPKG_INFO_DIR + filename, pkgname)
      elif filename.endswith(_MD5SUMS_FILE_EXT):
        pkgname = filename[:-_MD5SUMS_FILE_EXT_LEN]
        self.__load_md5sums(_DPKG_INFO_DIR + filename, pkgname)
    # Load conffiles info from the dpkg status file.
    self.__load_conffiles()

  def __load_list(self, path, pkgname):
    with open(path) as f:
      for line in f:
        line = line.rstrip("\n")
        if line == "/.":
          normpath = "/"
        else:
          normpath = line
        if not self.__path_filter.includes(normpath):
          continue
        node = self.__get_node(normpath, True)
        if pkgname in node.owners():
          print >> sys.stderr, "Got redundant entry for %s in %s" % (normpath,
                                                                     path)
          continue
        node._record_owner(pkgname)

  def __load_md5sums(self, path, pkgname):
    with open(path) as f:
      for line in f:
        line = line.rstrip("\n")
        normpath = "/" + line[34:]
        if not self.__path_filter.includes(normpath):
          continue
        md5sum = line[:32]
        pkg_info = self.__get_node(normpath, True)._get_package_info(pkgname)
        if pkg_info._md5sum:
          print >> sys.stderr, "Got redundant entry for %s in %s" % (normpath,
                                                                     path)
        pkg_info._md5sum = md5sum

  def __load_conffiles(self):
    # Annoyingly, the conffiles entries do not have a newline on the last line,
    # so we ask dpkg-query to add one. Unfortunately this means that an empty
    # entry will become a one-line entry, so we ignore blank lines in the
    # output.
    # In some dpkg-query versions the architecture-qualified name field is
    # called PackageSpec, while in others it's called binary:Package.
    # Non-existent field references expand to the empty string, so we just
    # concatenate them as in
    # https://code.launchpad.net/~lool/getlicenses/fix-for-newer-dpkg-query-format/+merge/169508
    p = subprocess.Popen(
        ["dpkg-query", "-f=${PackageSpec}${binary:Package}\\n${Conffiles}\\n", "-W"],
        stdout=subprocess.PIPE)
    package = None
    for line in p.stdout:
      line = line.rstrip("\n")
      if not line:
        # Ignore blank lines.
        continue
      # The lines in the Conffiles field all start with a space, while lines
      # in the binary:Package field all start with a non-space.
      if line[0] != ' ':
        # Next package.
        package = line
      else:
        # Next conffile in current package.
        if not package:
          # Got conffile line before first package line. Should not happen.
          print >> sys.stderr, ("Got malformed line in dpkg-query output: " +
                                line)
          continue
        # This is reverse-engineered from the f_conffiles() dpkg function in
        # lib/dpkg/fields.c.
        pair = line.rsplit(' ', 1)
        if len(pair) != 2:
          _bad_conffiles_line(package, line)
          continue
        obsolete = pair[1] == "obsolete"
        if obsolete:
          pair = pair[0].rsplit(' ', 1)
          if len(pair) != 2:
            _bad_conffiles_line(package, line)
            continue
        normpath = pair[0][1:]
        if not self.__path_filter.includes(normpath):
          continue
        md5sum = pair[1]
        if md5sum == "newconffile":
          # It's not clear what this means or why it occurs.
          print ("Warning: Ignoring Conffiles line for package %s with hash of "
                 "\"newconffile\": %s" % (package, line))
          continue
        if len(md5sum) != 32:
          _bad_conffiles_line(package, line)
          continue
        status = (md5sum, obsolete)
        pkg_info = self.__get_node(normpath, True)._get_package_info(package)
        if pkg_info._conffile_status:
          print >> sys.stderr, (
              "Got redundant dpkg-query output for file %s in package %s: %s" %
              (normpath, package, line))
        pkg_info._conffile_status = status
    if p.wait():
      print >> sys.stderr, ("dpkg-query failed with exit status %s" %
                            p.returncode)

  def __get_node(self, normpath, create):
    node = self.__root
    for component in _path_components(normpath):
      child = node.children().get(component)
      if not child and create:
        child = node._add_child(component)
      node = child
      if not node:
        break
    return node

  def lookup(self, normpath):
    """Lookup and return the dpkg state for the given path."""
    if not self.__path_filter.includes(normpath):
      # We didn't load info for this path.
      raise Exception("Filter excluded path " + normpath)
    return self.__get_node(normpath, False)
