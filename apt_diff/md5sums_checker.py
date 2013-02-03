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

"""Python implementation of "md5sum --quiet -c"."""

import hashlib
import mmap
import os
import stat
import sys

_READ_SIZE = 4096 * 16

def _compute_md5_by_syscalls(filename):
  with open(filename, "rb") as f:
    h = hashlib.md5()
    while True:
      data = f.read(_READ_SIZE)
      if not data:
        break
      h.update(data)
    return h.hexdigest()

def _compute_md5_by_mmap(filename):
  fileno = os.open(filename, os.O_RDONLY)
  try:
    h = hashlib.md5()
    st = os.fstat(fileno)
    size = st[stat.ST_SIZE]
    if size:
      mapping = mmap.mmap(fileno, size, mmap.MAP_PRIVATE, mmap.PROT_READ)
      try:
        h.update(mapping)
      finally:
        mapping.close()
    return h.hexdigest()
  finally:
    os.close(fileno)

def _compute_md5(filename):
  try:
    return _compute_md5_by_mmap(filename)
  except:
    # Silently fall back to a non-mmap'ed approach (mmap may fail for large
    # files on 32-bit machines).
    return _compute_md5_by_syscalls(filename)

def _verify_md5(filename, expected_md5):
  actual_md5 = _compute_md5(filename)
  return actual_md5 == expected_md5

def run(input_files, output_file):
  """Run this pipeline element."""
  for line in input_files[0]:
    line = line.rstrip('\n')
    parts = line.split(' ', 2)
    if len(parts) != 3:
      print >> sys.stderr, "Invalid input line to md5sum stage: " + line
      continue
    pkgname = parts[0]
    expected_md5 = parts[1]
    filename = parts[2]
    try:
      if not _verify_md5(filename, expected_md5):
        output_file.write("%s %s\n" % (pkgname, filename))
        output_file.flush()
    except Exception, e:
      print >> sys.stderr, "Failed to compute md5sum for %s: %s: %s" % (
          filename, type(e), e)
