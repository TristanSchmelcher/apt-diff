# Helper function to launch child Python processes.
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
import sys

def launch(function, input_read_handles, close_in_child):
  (out_read, out_write) = os.pipe()
  if os.fork() == 0:
    # Child.
    try:
      for fileno in close_in_child:
        os.close(fileno)
      inputs = []
      for in_read in input_read_handles:
        inputs.append(os.fdopen(in_read, "r"))
      os.close(out_read)
      function(inputs, os.fdopen(out_write, "w"))
      exitcode = 0
    except KeyboardInterrupt:
      exitcode = 130
    except SystemExit, e:
      # Emulate the termination behaviour of SystemExit.
      if type(e.code) is int:
        exitcode = e.code
      elif None == e.code:
        exitcode = 0
      else:
        exitcode = 1
        print >> sys.stderr, e.code
    except BaseException, e:
      print >> sys.stderr, "Exception while executing child: %s: %s" % (type(e),
          e)
      exitcode = 1
    finally:
      os._exit(exitcode)
  else:
    # Parent.
    for in_read in input_read_handles:
      os.close(in_read)
    os.close(out_write)
    return out_read
