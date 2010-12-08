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
_LIST_FILE_EXT = ".list"
_LIST_FILE_EXT_LEN = len(_LIST_FILE_EXT)
_CONFFILES_FILE_EXT = ".conffiles"
_CONFFILES_FILE_EXT_LEN = len(_CONFFILES_FILE_EXT)
_MULTIPLE = "(multiple packages)"

def extract_archive(archive_path, destdir):
  """Extracts an archive file on disk to the given directory."""
  devnull = open(os.devnull, "r")
  try:
    subprocess.check_call(["dpkg-deb", "-x", archive_path, destdir],
                          stdin = devnull)
  finally:
    devnull.close()

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

  def load_conffiles_for_pkgname(self, pkgname):
    filename = _DPKG_INFO_DIR + pkgname + _CONFFILES_FILE_EXT
    if os.access(filename, os.F_OK):
      self.__load_list(filename, pkgname, None)

  def load_files_for_paths(self, paths):
    for filename in os.listdir(_DPKG_INFO_DIR):
      if filename.endswith(_LIST_FILE_EXT):
        pkgname = filename[:-_LIST_FILE_EXT_LEN]
        self.__load_list(_DPKG_INFO_DIR + filename, pkgname, paths)

  def load_conffiles_for_paths(self, paths):
    for filename in os.listdir(_DPKG_INFO_DIR):
      if filename.endswith(_CONFFILES_FILE_EXT):
        pkgname = filename[:-_CONFFILES_FILE_EXT_LEN]
        self.__load_list(_DPKG_INFO_DIR + filename, pkgname, paths)
