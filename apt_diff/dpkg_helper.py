# Helper routines for interacting with dpkg.
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

import os
import subprocess

_DPKG_INFO_DIR = "/var/lib/dpkg/info/"
_DPKG_MD5SUM_FORMAT = "/var/lib/dpkg/info/%s.md5sums"
_LIST_FILE_EXT = ".list"
_LIST_FILE_EXT_LEN = len(_LIST_FILE_EXT)
_CONFFILES_FILE_EXT = ".conffiles"
_CONFFILES_FILE_EXT_LEN = len(_CONFFILES_FILE_EXT)
_MULTIPLE = "(multiple packages)"

def extract_archive(archive_path, destdir):
  """Extracts an archive file on disk to the given directory."""
  with open(os.devnull, "r") as devnull:
    subprocess.check_call(["dpkg-deb", "-x", archive_path, destdir],
                          stdin = devnull)

class FilesystemNode:
  """A FilesystemNode is a representation of a file or directory entry from a
     .list or .conffiles file."""

  def __init__(self):
    self.__children = None
    self.__pkgname = None

  def __record_owner(self, pkgname):
    if None == self.__pkgname:
      self.__pkgname = pkgname
    elif self.__pkgname != pkgname:
      self.__pkgname = _MULTIPLE

  def __add_child(self, name):
    if None == self.__children:
      self.__children = {}
    child = FilesystemNode()
    self.__children[name] = child
    return child

  def __load_list(self, path, pkgname, include_paths):
    fileobj = open(path)
    for line in fileobj:
      if None != include_paths:
        # See if this path is a child of one of the listed ones.
        include = False
        for include_path in include_paths:
          if line.startswith(include_path):
            include = True
            break
        if not include:
          continue
      normpath = line.rstrip("\n")
      if normpath == "/.":
        # Special case for the root directory.
        components = []
      else:
        components = normpath.lstrip("/").split("/")
      current = self
      for component in components:
        current.__record_owner(pkgname)
        child = current.find_child(component)
        if child == None:
          child = current.__add_child(component)
        current = child
      current.__record_owner(pkgname)
    fileobj.close()

  def has_children(self):
    return None != self.__children

  def children(self):
    return self.__children

  def pkgname(self):
    return self.__pkgname

  def find_child(self, name):
    if None == self.__children:
      return None
    else:
      return self.__children.get(name)

  def has_multiple_owners(self):
    return self.pkgname() == _MULTIPLE

  """The remaining methods below are all intended for use on the root node
     only."""

  def lookup(self, normpath):
    if normpath == "/":
      # Special case for the root directory.
      components = []
    else:
      components = normpath.lstrip("/").split("/")
    node = self
    last_node = None
    for component in components:
      last_node = node
      node = node.find_child(component)
      if node == None:
        break
    return (last_node, node)

  def load_files_for_pkgname(self, pkgname):
    filename = _DPKG_INFO_DIR + pkgname + _LIST_FILE_EXT
    if os.access(filename, os.F_OK):
      self.__load_list(filename, pkgname, None)

  def load_files_for_paths(self, paths):
    for filename in os.listdir(_DPKG_INFO_DIR):
      if filename.endswith(_LIST_FILE_EXT):
        pkgname = filename[:-_LIST_FILE_EXT_LEN]
        self.__load_list(_DPKG_INFO_DIR + filename, pkgname, paths)

  """These last two are not actually used anymore."""

  def load_conffiles_for_pkgname(self, pkgname):
    filename = _DPKG_INFO_DIR + pkgname + _CONFFILES_FILE_EXT
    if os.access(filename, os.F_OK):
      self.__load_list(filename, pkgname, None)

  def load_conffiles_for_paths(self, paths):
    for filename in os.listdir(_DPKG_INFO_DIR):
      if filename.endswith(_CONFFILES_FILE_EXT):
        pkgname = filename[:-_CONFFILES_FILE_EXT_LEN]
        self.__load_list(_DPKG_INFO_DIR + filename, pkgname, paths)

class MD5SumsInfo:
  """An MD5SumsInfo is an accessor for the information stored in dpkg's
     info/*.md5sums files."""

  def __init__(self):
    self.__package_md5sums = {}

  def load_md5sum(self, package, normpath):
    if package not in self.__package_md5sums:
      # Haven't loaded this md5sums file yet. Do it now.
      md5sums_path = _DPKG_MD5SUM_FORMAT % package
      try:
        f = open(md5sums_path, "r")
      except:
        f = None
      if f != None:
        file_md5sums = {}
        for line in f:
          if "\n" != line[-1]:
            print >> sys.stderr, "Malformed line in %s: %s" % (
                md5sums_path,
                line)
            continue
          file_md5sums["/" + line[34:-1]] = line[:32]
        f.close()
      else:
        file_md5sums = None
      self.__package_md5sums[package] = file_md5sums
    else:
      file_md5sums = self.__package_md5sums[package]
    if file_md5sums == None or normpath not in file_md5sums:
      # Either this package does not ship an md5sums file or it does but doesn't
      # contain an md5sum for this file.
      return None
    else:
      return file_md5sums[normpath]

class ConffilesStatus:
  """An MD5SumsInfo is an accessor for the Conffiles fields stored in dpkg's
     status file."""

  def __init__(self):
    self.__conffiles = {}

  def load_conffiles_for_packages(self, packages):
    """Loads the list of conffiles owned by the given packages. If None, it
       loads the conffiles for all packages."""
    if None != packages and len(packages) == 0:
      # With an empty list of packages, dpkg-query will query every package, but
      # we want to query none at all, so just return.
      return
    if None == packages:
      packages = []
    # Annoyingly, the conffiles entries do not have a newline on the last line,
    # so we ask dpkg-query to add one. Unfortunately this means that an empty
    # entry will become a one-line entry, so we ignore blank lines in the
    # output.
    p = subprocess.Popen(
        ["dpkg-query", "-f", "${Conffiles}\\n", "-W"] + packages,
        stdout = subprocess.PIPE)
    for line in p.stdout:
      if "\n" != line[-1]:
        print >> sys.stderr, "Malformed line in Conffiles field: " + line
        continue
      if "\n" == line:
        # Ignore blank lines.
        continue
      obsolete = line.endswith(" obsolete\n")
      if obsolete:
        trim = 9
      else:
        trim = 0
      filename = line[1:-34 - trim]
      md5sum = line[-33 - trim:-1 - trim]
      self.__conffiles[filename] = (md5sum, obsolete)

  def has_conffile(self, normpath):
    return normpath in self.__conffiles

  def get_conffile_status(self, normpath):
    if not self.has_conffile(normpath):
      # Either not a conffile or not loaded.
      return None
    else:
      return self.__conffiles[normpath]
