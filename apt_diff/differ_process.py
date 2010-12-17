# A helper process for unpacking downloaded packages and diff'ing the files in
# them to the ones on disk.
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

import dpkg_helper
import os
import subprocess
import sys

def create(extraction_dir):
  def run(input_files, output_file):
    input_file = input_files[0]
    discrepancies = 0
    for line in input_file:
      if line[-1] != "\n":
        print >> sys.stderr, "Unexpected line from APT fetch stage: " + line
        continue
      parts = line[:-1].split(" ")
      first = (parts[0] == "T")
      pkgname = parts[1]
      path = parts[2]
      filename = " ".join(parts[3:])
      extract_path = os.path.join(extraction_dir, pkgname)
      if first:
        # Unpack the package.
        dpkg_helper.extract_archive(path, extract_path)
      # See if it actually contains this file. (It is possible that the
      # installed package came from a different repository and thus could have
      # a different set of files.)
      extracted_filename = extract_path + filename
      if not os.path.lexists(extracted_filename):
        print ("File %s supposedly owned by package %s was not found in it" %
               (filename, pkgname))
        discrepancies = discrepancies + 1
      else:
        # Diff the file.
        ret = subprocess.call(["diff", "-u", extracted_filename, filename])
        if ret != 0:
          # Increment the count of the number of discrepancies.
          discrepancies = discrepancies + 1
    # Write the final count to our output.
    output_file.write(str(discrepancies))
  return run
