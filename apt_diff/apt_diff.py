# Diff filesystem content against the APT installation sources.
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

import warnings
warnings.filterwarnings("ignore", "apt API not stable yet",
                        FutureWarning)

import apt_fetcher_process
import apt_helper
import differ_process
import dpkg_helper
import getopt
import launch_helper
import os
import parallel_md5sums_checker
import shutil
import stat
import sys
import tempfile
import time

VERSION = "0.9.6"

# Constants for our command-line argument names.
_PACKAGE = "package"
_SHORT_PACKAGE = "p"
_PATH = "path"
_SHORT_PATH = "f"
_APT_OPTION = "apt-option"
_SHORT_APT_OPTION = "o"
_HELP = "help"
_SHORT_HELP = "h"
_VERSION = "version"
_SHORT_VERSION = "V"
_IGNORE_CONFFILES = "ignore-conffiles"
_NO_IGNORE_EXTRAS = "no-ignore-extras"
_NO_OVERRIDE_CACHE = "no-override-cache"
_REPORT_UNVERIFIABLE = "report-unverifiable"
_TEMPDIR = "tempdir"
_NO_REMOVE_EXTRACTED = "no-remove-extracted"

_USAGE = """
Usage: apt-diff [OPTION]... [PATH|PACKAGE]...

Diff filesystem content against the APT installation sources. The content to
diff can be specified either by path or by package. Specifying a package is
equivalent to specifying the list of all innermost paths that it owns.

Options:
    --package       -p <name>          Check the named package.
    --path          -f <path>          Check the given path (recursively).
    --apt-option    -o <name>=<value>  Set an arbitrary APT option.
    --help          -h                 Show this help.
    --version       -V                 Show the version.

    --ignore-conffiles                 Ignore conffiles.
    --no-ignore-extras                 Do not ignore extra files/directories.
    --no-override-cache                Do not override the package cache
                                       directory when running as non-root.
    --report-unverifiable              Report unverifiable directories and
                                       symbolic links.
    --tempdir          <dir>           Use <dir> as the temp directory instead
                                       of creating one automatically.
    --no-remove-extracted              Don't remove extracted packages from the
                                       temp directory after completion."""

def _launch_pipeline(apt_helper, extraction_dir):
  (md5sum_in_read, md5sum_in_write) = os.pipe()
  md5sum_out_read = launch_helper.launch(
      parallel_md5sums_checker.run,
      [md5sum_in_read],
      [md5sum_in_write])
  (apt_fetcher_in_read, apt_fetcher_in_write) = os.pipe()
  apt_fetcher_out_read = launch_helper.launch(
      apt_fetcher_process.AptFetcher(apt_helper).run,
      [md5sum_out_read, apt_fetcher_in_read],
      [md5sum_in_write, apt_fetcher_in_write])
  differ_out_read = launch_helper.launch(
      differ_process.create(extraction_dir),
      [apt_fetcher_out_read],
      [md5sum_in_write, apt_fetcher_in_write])
  return (os.fdopen(md5sum_in_write, "w"),
          os.fdopen(apt_fetcher_in_write, "w"),
          os.fdopen(differ_out_read, "r"))

class AptDiff:

  def __init__(self,
               ignore_conffiles,
               no_ignore_extras,
               report_unverifiable,
               extraction_dir):
    self.ignore_conffiles = ignore_conffiles
    self.no_ignore_extras = no_ignore_extras
    self.report_unverifiable = report_unverifiable
    self.extraction_dir = extraction_dir
    self.discrepancy_count = 0
    self.error_count = 0
    self.ignored_extras_count = 0
    self.ignored_conffiles_count = 0
    self.unverifiable_link_count = 0
    self.unverifiable_dir_count = 0
    self.__paths = []

  def check_path(self, path):
    normpath = os.path.normpath(os.path.join(os.getcwd(), path))
    self.__paths.append(normpath)

  def check_package(self, pkgname):
    paths = dpkg_helper.expand_package_to_leaf_paths(pkgname)
    if not paths:
      print "Package %s does not own any installed paths" % pkgname
      return
    self.__paths.extend(paths)

  def execute(self):
    time1 = time.time()
    self.__dpkg_helper = dpkg_helper.DpkgHelper(dpkg_helper.PathFilter(
        self.__paths))
    self.__apt_helper = apt_helper.AptHelper()
    # Start our processing pipeline.
    (self.__md5sum_in,
     self.__apt_fetcher_in,
     self.__differ_out) = _launch_pipeline(
        self.__apt_helper, self.extraction_dir)
    # Perform all requested diffs.
    if not self.__paths:
      print "Warning: no paths to diff. This is a no-op."
    else:
      for path in self.__paths:
        self.__do_check_path(path)
    # Close processing input handles so that the pipeline knows the data is
    # over and the processes will exit.
    self.__md5sum_in.close()
    self.__apt_fetcher_in.close()
    # Wait for all summing to be finished and the count of modified files to be
    # available.
    self.discrepancy_count = (self.discrepancy_count +
        int(self.__differ_out.readline()))
    self.__differ_out.close()
    # Summarize findings.
    print "--------------------------------"
    print ("Found %d differences between filesystem state and package state" %
        self.discrepancy_count)
    if 0 != self.error_count:
      print ("Encountered %d errors that prevented a complete check" %
          self.error_count)
    if 0 != self.ignored_conffiles_count:
      print "Ignored %d conffiles" % self.ignored_conffiles_count
    if 0 != self.ignored_extras_count:
      print ("Ignored %d extra paths not owned by any package" %
          self.ignored_extras_count)
    if 0 != self.unverifiable_dir_count:
      print "Skipped %d unverifiable directories" % self.unverifiable_dir_count
    if 0 != self.unverifiable_link_count:
      print (
          "Skipped %d unverifiable symbolic links"
          % self.unverifiable_link_count)
    time2 = time.time()
    print "Finished in %g seconds" % (time2 - time1)

  def __discrepancy(self):
    self.discrepancy_count = self.discrepancy_count + 1

  def __error(self):
    self.error_count = self.error_count + 1

  def __do_check_path(self, normpath):
    # Find the right node for this path.
    node = self.__dpkg_helper.lookup(normpath)
    # We do not check if a directory crossed in this step was a symlink--we
    # always use False. (This allows a user to effectively suppress the special
    # symlink logic by starting the traversal below the symlink.)
    self.__do_check(normpath, node, False)

  def __do_check(self,
                 normpath,
                 node,
                 within_symlink):
    try:
      lst = os.lstat(normpath)
    except:
      lst = None
    try:
      st = os.stat(normpath)
    except:
      st = None
    lexists = bool(lst)
    exists = bool(st)
    isdir = exists and stat.S_ISDIR(st.st_mode)
    isfile = exists and stat.S_ISREG(st.st_mode)
    islink = lexists and stat.S_ISLNK(lst.st_mode)
    path = normpath
    if isdir and path[-1] != "/":
      # Add a trailing slash so that the user can distinguish between
      # files and directories in the output.
      path = path + "/"
    if node and not lexists:
      print "Missing path %s owned by %s" % (path, node.owners_str())
      self.__discrepancy()
    elif not node and lexists:
      if within_symlink:
        # If this path crosses a symbolic directory link at any parent level
        # then any extra files/directories are most likely owned by other
        # packages through the real, non-symlinked path to this directory, so
        # reporting them as extras would be inaccurate. Any real extras will be
        # reported anyway when we traverse the non-symlinked path.
        return
      if not self.no_ignore_extras:
        # Unfortunately even a fresh OS installation contains many hundreds of
        # extra files/directories that are not owned by any package, so by
        # default we suppress printing a message about such paths.
        self.ignored_extras_count = self.ignored_extras_count + 1
        return
      print "Extra path %s not owned by any package" % path
      self.__discrepancy()
    elif not node and not lexists:
      # (We will only reach this case if the user explicitly started us at this
      # path.)
      print "Path %s not found in filesystem nor in any package" % path
    else:
      # Else it exists on disk and in packages. Figure out what filetype it
      # should have.
      # Package info is created only for things with an md5sum or conffiles, so
      # if there is any package info then this should be a file.
      expect_file = bool(node.package_info())
      # If this path has children, then it must be shipped as a directory.
      expect_dir = bool(node.children())
      # Sanity check that these are consistent.
      if expect_file and expect_dir:
        print ("Warning: Inconsistent dpkg state: path %s owned by %s has an "
               "md5sum and children") % (path, node.owners_str())
        # Continue and treat it as a directory.
      if expect_dir:
        if isdir:
          # It's a directory, so recurse and check the contents.
          if islink:
            # But if it is actually a _symlink_ to a directory then there is
            # another issue. If one package ships a directory at this path and
            # another ships a symlink, dpkg permits both to be installed and
            # whichever one installs the path first "wins". Any installed paths
            # that are recorded as being beneath this one must have been
            # intended to go into the directory version, so the fact that the
            # dpkg node has children indicates that a directory/link conflict
            # occurred at some point. Since this may have resulted in different
            # on-disk content than the packagers intended, we report it even
            # though it is not really a discrepancy.
            print ("Warning: Package content installed under %s crosses "
                   "unexpected symlink") % path
            within_symlink = True
          try:
            ents = os.listdir(normpath)
          except OSError, e:
            print >> sys.stderr, "Can't recurse into %s: %s" % (path, e)
            self.__error()
            return
          ents.extend(node.children())
          ents.sort()
          last = None
          for ent in ents:
            if ent != last:
              self.__do_check(
                os.path.join(normpath, ent),
                node.children().get(ent),
                within_symlink)
            last = ent
        else:
          # Not a directory on disk, so it's either a regular file, a special
          # file, or a symlink to a non-directory. Regardless, that's a
          # discrepancy
          print "Non-directory %s is supposed to be a directory owned by %s" % (
              path,
              node.owners_str())
          self.__discrepancy()
      elif expect_file:
        if islink:
          if not exists:
            print "Broken symlink %s is supposed to be a file owned by %s" % (
                path, node.owners_str())
            self.__discrepancy()
          elif isfile:
            # Symlink-to-file, but expected to be a regular file. This is
            # somewhat anomalous, but there are packages out there that ship
            # files and then change them to symlinks in their postinst, so
            # warn but do not count a discrepancy.
            print "Warning: Unexpected symlink for file %s owned by %s" % (
                path, node.owners_str())
            # If the target of the symlink compares as equal to the expected
            # content, then we don't count a discrepancy.
            self.__check_file(normpath, node)
          elif isdir:
            print ("Symlinked directory %s is supposed to be a file owned by "
                   "%s") % (path, node.owners_str())
            self.__discrepancy()
          else:
            print ("Symlinked special file %s is supposed to be a regular "
                   "file owned by %s") % (path, node.owners_str())
            self.__discrepancy()
        elif isfile:
          self.__check_file(normpath, node)
        elif isdir:
          print "Directory %s is supposed to be a file owned by %s" % (path,
              node.owners_str())
          self.__discrepancy()
        else:
          print ("Special file %s is supposed to be a regular file owned by %s"
                 % (path, node.owners_str()))
          self.__discrepancy()
      else:
        # Else we have no way of knowing what filetype it should be. The lack
        # of an md5sum suggests that it is a non-file, but some packages ship
        # incomplete .md5sums files or no md5sum file at all. The lack of
        # children suggests that it is a non-directory, but some packages ship
        # empty directories. So we assume that whatever filetype it has on-disk
        # is correct. For files, we skip the md5sum stage and download the
        # owning package to verify them. For other types, we just report that we
        # can't verify them.
        if islink:
          self.unverifiable_link_count = self.unverifiable_link_count + 1
          if self.report_unverifiable:
            print "Skipping unverifiable symbolic link %s owned by %s" % (
                path,
                node.owners_str())
        elif isdir:
          self.unverifiable_dir_count = self.unverifiable_dir_count + 1
          if self.report_unverifiable:
            print "Skipping unverifiable directory %s owned by %s" % (
                path,
                node.owners_str())
        elif isfile:
          self.__check_file(normpath, node)
        else:
          # No way to know if it's actually supposed to be a special file, but
          # it's very likely not. Warn the user but don't count a discrepancy.
          print "Warning: Special file installed at %s owned by %s" % (
              path,
              node.owners_str())

  def __access(self, normpath):
    if not os.access(normpath, os.R_OK):
      print >> sys.stderr, "Don't have read permission for " + normpath
      self.__error()
      return False
    return True

  def __check_file(self, normpath, node):
    if not self.__access(normpath):
      return
    # For every md5sum that we have for this file, we check its md5sum against
    # that. On mismatch, we download and diff against an arbitrary package
    # chosen from those that contain that file and that record that md5sum.
    # For every owning package that records no md5sum, we download and diff
    # immediately.
    # We skip obsolete conffiles because they may be changed automatically in
    # the case where a conffile is removed from one package and added to a
    # different package with the same path, and there is no way to download the
    # obsolete conffile anyway.
    md5sums_so_far = {}
    for pkgname in node.owners():
      if pkgname in node.package_info():
        self.__check_file_with_package_info(md5sums_so_far, normpath, pkgname,
            node.package_info()[pkgname])
      else:
        # No md5sum for this file in this package. Have to download it.
        self.__check_file_without_md5sum(normpath, pkgname)
    # Also check package info for packages not listed as owners in case the
    # .md5sums file or conffiles status are out of sync with the .list. 
    for pkgname in node.package_info():
      if pkgname in node.owners():
        continue
      pkg_info = node.package_info()[pkgname]
      if pkg_info.conffile_status() and (pkg_info.conffile_status()[1] or
          not self.__apt_helper.is_installed(pkgname)):
        # It is normal to have a conffile status for a file we don't own if
        # either it's an obsolete conffile or the package has been
        # de-installed. This is because if a conffile is moved to a different
        # package, dpkg removes it from the original's .list file but does not
        # remove the conffile status.
        # Note that if the new package owning the conffile is later purged,
        # the original does not regain ownership; the file is simply deleted
        # and the conffile status remains the same. In this case, we would
        # have reported it as missing earlier.
        continue
      print "Warning: Package %s has md5sum for file %s not owned by it" % (
          pkgname, normpath)
      self.__check_file_with_package_info(md5sums_so_far, normpath, pkgname,
          pkg_info)
    # Report conflicting md5sums.
    if len(md5sums_so_far) > 1:
      # This may be due to dpkg-divert. Ideally we should check for diversions.
      print ("Warning: Conflicting md5sums for file %s in different packages: "
          "%s" % (normpath, md5sums_so_far))

  def __check_file_with_package_info(self, md5sums_so_far, normpath, pkgname,
      pkg_info):
    if self.ignore_conffiles and pkg_info.conffile_status():
      self.ignored_conffiles_count = self.ignored_conffiles_count + 1
      return
    # For packages created with debhelper, the .md5sums file will not contain
    # data for conffiles, but for some non-debhelper-based packages it does, so
    # we handle the case where both the .md5sums file and the Conffiles field
    # contain data for the same path.
    if (pkg_info.md5sum() and pkg_info.conffile_status() and
        pkg_info.md5sum() != pkg_info.conffile_status()[0]):
      print ("Warning: Package %s has conflicting md5sums for %s: %s vs. %s"
          % (pkgname, normpath, pkg_info.md5sum(),
             pkg_info.conffile_status()[0]))
    # Arbitrarily prefer the .md5sums value over the conffiles value.
    if pkg_info.md5sum():
      md5sum = pkg_info.md5sum()
    elif not pkg_info.conffile_status()[1]:
      md5sum = pkg_info.conffile_status()[0]
    else:
      # Obsolete conffile. Skip.
      return
    if md5sum in md5sums_so_far:
      # A previous owner had this same md5sum. No need to check it twice.
      md5sums_so_far[md5sum].append(pkgname)
      return
    md5sums_so_far[md5sum] = [pkgname]
    self.__check_file_with_md5sum(md5sum, normpath, pkgname)

  def __check_file_with_md5sum(self, md5sum, normpath, pkgname):
    self.__md5sum_in.write("%s %s %s\n" % (pkgname, md5sum, normpath))
    self.__md5sum_in.flush()

  def __check_file_without_md5sum(self, normpath, pkgname):
    self.__apt_fetcher_in.write("%s %s\n" % (pkgname, normpath))
    self.__apt_fetcher_in.flush()

def version(fileobj):
  print >> fileobj, "apt-diff " + VERSION

def usage(fileobj):
  version(fileobj)
  print >> fileobj, _USAGE

def _ensure_dir(path):
  if not os.path.isdir(path):
    os.mkdir(path, 0755)
  else:
    os.chmod(path, 0755)

def main(argv):
  try:
    try:
      opts, args = getopt.getopt(
          argv,
          _SHORT_PACKAGE + ":" +
          _SHORT_PATH + ":" +
          _SHORT_APT_OPTION + ":" +
          _SHORT_HELP +
          _SHORT_VERSION,
          [_PACKAGE + "=",
           _PATH + "=",
           _APT_OPTION + "=",
           _HELP,
           _VERSION,
           _IGNORE_CONFFILES,
           _NO_IGNORE_EXTRAS,
           _NO_OVERRIDE_CACHE,
           _REPORT_UNVERIFIABLE,
           _TEMPDIR + "=",
           _NO_REMOVE_EXTRACTED])
    except getopt.GetoptError, err:
      print >> sys.stderr, str(err)
      usage(sys.stderr)
      return 2
    apt_helper.initialize()
    apt_diff = AptDiff(False,
                       False,
                       False,
                       None)
    no_override_cache = False
    tempdir = None
    no_remove_extracted = False
    for (opt, arg) in opts:
      opt = opt.lstrip("-")
      if opt == _PACKAGE or opt == _SHORT_PACKAGE:
        apt_diff.check_package(arg)
      elif opt == _PATH or opt == _SHORT_PATH:
        apt_diff.check_path(arg)
      elif opt == _APT_OPTION or opt == _SHORT_APT_OPTION:
        parts = arg.split("=")
        apt_helper.set_option(parts[0], "=".join(parts[1:]))
      elif opt == _HELP or opt == _SHORT_HELP:
        usage(sys.stdout)
        return 0
      elif opt == _VERSION or opt == _SHORT_VERSION:
        version(sys.stdout)
        return 0
      elif opt == _IGNORE_CONFFILES:
        apt_diff.ignore_conffiles = True
      elif opt == _NO_IGNORE_EXTRAS:
        apt_diff.no_ignore_extras = True
      elif opt == _NO_OVERRIDE_CACHE:
        no_override_cache = True
      elif opt == _REPORT_UNVERIFIABLE:
        apt_diff.report_unverifiable = True
      elif opt == _TEMPDIR:
        tempdir = arg
      elif opt == _NO_REMOVE_EXTRACTED:
        no_remove_extracted = True
      else:
        # Shouldn't happen because getopt should have thrown an error.
        raise Exception("Unexpected option")
    for arg in args:
      # Try to guess what the user meant by this.
      if arg[0] == "/":
        # Treat it like --path
        apt_diff.check_path(arg)
      elif arg[0].isalnum():
        # Treat it like --package
        apt_diff.check_package(arg)
      else:
        print >> sys.stderr, "Don't know what to do with \"%s\"" % arg
        usage(sys.stderr)
        return 2
    # Create default tempdir if none specified.
    if not tempdir:
      tempdir = os.path.join(tempfile.gettempdir(),
                             "apt-diff_" + str(os.getuid()))
      _ensure_dir(tempdir)
    if tempdir.find(" ") != -1:
      # This would mess up our processing pipeline.
      raise Exception("Spaces are not supported in the tempdir path")
    if not no_override_cache and os.getuid():
      # Set default archive dir to one we can actually write to.
      archive_dir = os.path.join(tempdir, "archives")
      _ensure_dir(archive_dir)
      _ensure_dir(os.path.join(archive_dir, "partial"))
      apt_helper.set_option("Dir::Cache::Archives", archive_dir)
    extraction_dir = os.path.join(tempdir, "extracted")
    _ensure_dir(extraction_dir)
    apt_diff.extraction_dir = extraction_dir
    apt_diff.execute()
    if not no_remove_extracted:
      # Recursively delete the extracted packages.
      shutil.rmtree(extraction_dir)
  except KeyboardInterrupt:
    return 130
