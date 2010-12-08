# Tools to manage a poll-loop in Python.
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

import fcntl
import os
import select
import sys

# Max size of data to read from pipes at once
_READ_SIZE = 4096

class Poller:
  def __init__(self):
    self.__poll = select.poll()
    self.__map = {}

  def register(self, fileobj, event, handler_function):
    self.__poll.register(fileobj, event)
    self.__map[fileobj.fileno()] = handler_function

  def unregister(self, fileobj):
    del self.__map[fileobj.fileno()]
    self.__poll.unregister(fileobj)

  def poll(self, timeout = None):
    for fileno, event in self.__poll.poll(timeout):
      # Call handler
      self.__map[fileno](fileno, event)

  def has_pollers(self):
    return 0 != len(self.__map)

def _set_non_blocking(f):
  fileno = f.fileno()
  flags = fcntl.fcntl(fileno, fcntl.F_GETFL, 0)
  flags |= os.O_NONBLOCK
  fcntl.fcntl(fileno, fcntl.F_SETFL, flags)

class LineSource:
  def __init__(self, fileobj, poller, consumer_function, close_function = None):
    self.__fileobj = fileobj
    self.__poller = poller
    self.__consumer_function = consumer_function
    self.__close_function = close_function
    self.__partial_input = ""
    _set_non_blocking(self.__fileobj)
    self.__poller.register(self.__fileobj,
                           select.POLLIN,
                           self.__on_pollin)

  def __on_pollin(self, fileno, event):
    text = os.read(self.__fileobj.fileno(), _READ_SIZE)
    if 0 == len(text):
      # fd is ready but returns no data. This means it's EOF.
      self.__poller.unregister(self.__fileobj)
      self.__fileobj.close()
      # If we have a partial final line, give it to our consumer.
      if "" != self.__partial_input:
        self.__consumer_function(self, self.__partial_input)
        self.__partial_input = ""
      # Notify that we have closed.
      if None != self.__close_function:
        self.__close_function(self)
      return
    # Else it has more data.
    self.__partial_input += text
    nl = self.__partial_input.rfind("\n")
    if -1 != nl:
      # Have complete line(s) to pass to the consumer
      nl = nl + 1
      self.__consumer_function(self, self.__partial_input[:nl])
      self.__partial_input = self.__partial_input[nl:]

class LineSink:
  def __init__(self, fileobj, poller):
    self.__fileobj = fileobj
    self.__poller = poller
    self.__partial_output = ""
    self.__closed = False
    _set_non_blocking(self.__fileobj)

  def __on_pollout(self, fileno, event):
    try:
      written = os.write(self.__fileobj.fileno(), self.__partial_output)
    except OSError, e:
      # Probably broken pipe. Have to force-close the file. :(
      print >> sys.stderr, "Unable to write to pipe:", e
      self.__closed = True
      self.__poller.unregister(self.__fileobj)
      self.__fileobj.close()
      return
    self.__partial_output = self.__partial_output[written:]
    if not self.has_data_pending():
      # Don't need to be listening on this fd anymore.
      self.__poller.unregister(self.__fileobj)
      if self.__closed:
        # Now that all data has been flushed, we can actually close.
        self.__fileobj.close()

  def has_data_pending(self):
    return "" != self.__partial_output

  def write_lines(self, lines):
    if self.__closed:
      return
    had_pending = self.has_data_pending()
    self.__partial_output += lines
    if not had_pending:
      # Register to find out when we can write the data.
      self.__poller.register(self.__fileobj,
                             select.POLLOUT,
                             self.__on_pollout)

  def close(self):
    if self.__closed:
      return
    self.__closed = True
    if not self.has_data_pending():
      # Can close now.
      self.__fileobj.close()
