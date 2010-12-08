# A helper process for downloading the packages containing files with incorrect
# md5sums.

import pollingtools
import sys

class AptFetcher:
  def __init__(self, apt_helper, tree):
    self.__apt_helper = apt_helper
    self.__tree = tree

  def __fetch_owning_package(self, filename):
    node = self.__tree.lookup(filename)[1]
    if node.has_multiple_owners():
      print >> sys.stderr, (
          "Unable to fully check file %s because multiple packages claim to "
          "own it" % filename)
      return
    pkgname = node.pkgname()
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
    if path == None:
      if first == "T":
        print >> sys.stderr, (
            "Unable to fully check package %s because it could not be fetched"
            % pkgname)
    else:
      # Tell the next stage that it can unpack the package and diff the file.
      self.__output_file.write("%s %s %s %s\n" %
                               (first, pkgname, path, filename))
      self.__output_file.flush()

  def __on_failed_md5sums(self, source, lines):
    for line in lines.splitlines():
      # The input comes from md5sum --quiet -c, so it should end in ": FAILED".
      # Strip it.
      if not line.endswith(": FAILED"):
        print >> sys.stderr, "Unexpected line from md5sum stage: " + line
        continue
      filename = line[:-8]
      self.__fetch_owning_package(filename)

  def __on_missing_md5sums(self, source, lines):
    for line in lines.splitlines():
      # The input comes directly from the AptCheck class and is simply a list of
      # files that are missing their md5sums, so pass it directly to the fetch
      # function.
      self.__fetch_owning_package(line)

  def run(self, input_files, output_file):
    failed_md5sums_input_file = input_files[0]
    missing_md5sums_input_file = input_files[1]
    self.__pkg_paths = {}
    self.__output_file = output_file
    poller = pollingtools.Poller()
    pollingtools.LineSource(failed_md5sums_input_file, poller,
                            self.__on_failed_md5sums)
    pollingtools.LineSource(missing_md5sums_input_file, poller,
                            self.__on_missing_md5sums)
    while poller.has_pollers():
      poller.poll()
