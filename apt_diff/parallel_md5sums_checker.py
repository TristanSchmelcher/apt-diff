# A helper process for executing md5sum checks for many files in parallel
# across different processes.
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

import distributor
import launch_helper
import md5sums_checker
import os

def _spawner():
  (in_read, in_write) = os.pipe()
  out_read = launch_helper.launch(md5sums_checker.run, [in_read], [in_write])
  return (os.fdopen(in_write, "w"), os.fdopen(out_read, "r"))

def run(input_files, output_file):
  distributor.run(input_files[0], output_file, _spawner)
