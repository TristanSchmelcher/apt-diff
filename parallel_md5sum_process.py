# A helper process for executing md5sum checks for many files in parallel
# across different processes.

import distributor
import os
import subprocess
import sys

def _spawner():
  devnull = open(os.devnull, "r")
  proc = subprocess.Popen(["md5sum", "--quiet", "-c"],
                          stdin = subprocess.PIPE,
                          stdout = subprocess.PIPE,
                          stderr = devnull)
  devnull.close()
  return (proc.stdin, proc.stdout)

def run(input_files, output_file):
  distributor.run(input_files[0], output_file, _spawner)
