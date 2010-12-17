# Routines for distributing line-based processing across different processes.
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

_DEFAULT_MAX_PROCESSES = 5

def run(input_file, output_file, spawner_function,
        max_processes = _DEFAULT_MAX_PROCESSES):
  if max_processes < 1:
    raise ValueError("max_processes must be at least 1")
  poller = pollingtools.Poller()
  sink = pollingtools.LineSink(output_file, poller)
  process_sources = []

  def on_process_source_lines(source, lines):
    # Just write the lines to the output.
    sink.write_lines(lines)

  def on_process_source_closed(source):
    process_sources.remove(source)
    if len(process_sources) == 0:
      # No sources left, so close the output
      sink.close()

  process_sinks = []
  next_sink = [0]

  def on_source_lines(source, lines):
    if len(process_sinks) != 0:
      # See if there is an existing process sink that is ready to accept more
      # lines.
      index = next_sink[0]
      while True:
        next = (index + 1) % len(process_sinks)
        if not process_sinks[index].has_data_pending():
          # This one is ready.
          process_sinks[index].write_lines(lines)
          next_sink[0] = next
          return
        index = next
        if index == next_sink[0]:
          # We went all the way around and none were ready.
          break
    # No process is ready, so spawn another one if possible.
    if len(process_sinks) < max_processes:
      (in_pipe, out_pipe) = spawner_function()
      process_sources.append(
          pollingtools.LineSource(out_pipe,
                                  poller,
                                  on_process_source_lines,
                                  on_process_source_closed))
      process_sinks.append(
          pollingtools.LineSink(in_pipe,
                                poller))
      index = len(process_sinks) - 1
    else:
      # Else simply queue up the lines on whichever process is next.
      index = next_sink[0]
    process_sinks[index].write_lines(lines)
    next_sink[0] = (index + 1) % len(process_sinks)

  def on_source_closed(source):
    # No more data to give to the process sinks, so close them all.
    for process_sink in process_sinks:
      process_sink.close()

  pollingtools.LineSource(input_file,
                          poller,
                          on_source_lines,
                          on_source_closed)
  while poller.has_pollers():
    poller.poll()
