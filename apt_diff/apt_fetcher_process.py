# A helper process for downloading the packages to be diff'ed.
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

import pollingtools
import sys

class AptFetcher:
  def __init__(self, apt_helper):
    self.__apt_helper = apt_helper
    self.__pkg_paths = {}

  def __fetch_package(self, pkgname, filename):
    if pkgname not in self.__pkg_paths:
      # Haven't downloaded this package archive yet. Get it now.
      path = self.__apt_helper.fetch_archive(pkgname)
      self.__pkg_paths[pkgname] = path
      # Informs the next stage that this is the first file to check in this
      # package.
      first = "T"
    else:
      path = self.__pkg_paths[pkgname]
      first = "F"
    if not path:
      if first == "T":
        print >> sys.stderr, (
            "Unable to fully check package %s because it could not be fetched"
            % pkgname)
    else:
      # Tell the next stage that it can unpack the package and diff the file.
      self.__output_file.write("%s %s %s %s\n" %
                               (first, pkgname, path, filename))
      self.__output_file.flush()

  def __on_check_files(self, source, lines):
    for line in lines.splitlines():
      parts = line.split(' ', 1)
      if len(parts) != 2:
        print >> sys.stderr, "Invalid input line to APT fetch stage: " + line
        continue
      pkgname = parts[0]
      filename = parts[1]
      self.__fetch_package(pkgname, filename)

  def run(self, input_files, output_file):
    failed_md5sums_input_file = input_files[0]
    missing_md5sums_input_file = input_files[1]
    self.__output_file = output_file
    poller = pollingtools.Poller()
    pollingtools.LineSource(failed_md5sums_input_file, poller,
                            self.__on_check_files)
    pollingtools.LineSource(missing_md5sums_input_file, poller,
                            self.__on_check_files)
    while poller.has_pollers():
      poller.poll()
