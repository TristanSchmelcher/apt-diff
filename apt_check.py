#!/usr/bin/python
#
# Check for differences between on-disk files and their original content from
# APT.

import warnings
warnings.filterwarnings("ignore", "apt API not stable yet",
                        FutureWarning)

import apt_fetcher_process
import apt_helper
import differ_process
import dpkg_helper
import getopt
import os
import parallel_md5sum_process
import shutil
import stat
import sys
import tempfile
import time

VERSION = "0.9"

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
_NO_IGNORE_EXTRAS = "no-ignore-extras"
_NO_IGNORE_CONFFILES = "no-ignore-conffiles"
_NO_OVERRIDE_CACHE = "no-override-cache"
_REPORT_UNVERIFIABLE = "report-unverifiable"
_TEMPDIR = "tempdir"

_USAGE = """
Usage: apt-check [OPTION]... [PATH|PACKAGE]...

Check filesystem content against the APT installation sources and display any
discrepancies as a diff.

Options:
    --package       -p <name>          Check the named package.
    --path          -f <path>          Check the given path (recursively).
    --apt-option    -o <name>=<value>  Set an arbitrary APT option.
    --help          -h                 Show this help.
    --version       -V                 Show the version.

    --no-ignore-extras                 Do not ignore extra files/directories.
    --no-ignore-conffiles              Do not ignore conffiles.
    --no-override-cache                Do not override the package cache
                                       directory when running as non-root.
    --report-unverifiable              Report unverifiable directories and
                                       symbolic links.
    --tempdir          <dir>           Use <dir> as the temp directory instead
                                       of creating one automatically."""

def _launch(function, input_read_handles, close_in_child):
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
      try:
        function(inputs, os.fdopen(out_write, "w"))
        exitcode = 0
      except KeyboardInterrupt:
        raise
      except BaseException, e:
        print >> sys.stderr, "Exception while executing child:", e
        exitcode = 1
    except KeyboardInterrupt:
      exitcode = 130
    sys.exit(exitcode)
  else:
    # Parent.
    for in_read in input_read_handles:
      os.close(in_read)
    os.close(out_write)
    return out_read

def _launch_pipeline(apt_helper, tree, extraction_dir):
  (md5sum_in_read, md5sum_in_write) = os.pipe()
  md5sum_out_read = _launch(
      parallel_md5sum_process.run,
      [md5sum_in_read],
      [md5sum_in_write])
  (apt_fetcher_in_read, apt_fetcher_in_write) = os.pipe()
  apt_fetcher_out_read = _launch(
      apt_fetcher_process.AptFetcher(apt_helper, tree).run,
      [md5sum_out_read, apt_fetcher_in_read],
      [md5sum_in_write, apt_fetcher_in_write])
  differ_out_read = _launch(
      differ_process.create(extraction_dir),
      [apt_fetcher_out_read],
      [md5sum_in_write, apt_fetcher_in_write])
  return (os.fdopen(md5sum_in_write, "w"),
          os.fdopen(apt_fetcher_in_write, "w"),
          os.fdopen(differ_out_read, "r"))

class AptCheck:
  __CHECK_PATH = 0
  __CHECK_PACKAGE = 1

  def __init__(self,
               no_ignore_extras,
               no_ignore_conffiles,
               report_unverifiable,
               extraction_dir):
    self.no_ignore_extras = no_ignore_extras
    self.no_ignore_conffiles = no_ignore_conffiles
    self.report_unverifiable = report_unverifiable
    self.extraction_dir = extraction_dir
    self.discrepancy_count = 0
    self.error_count = 0
    self.ignored_extras_count = 0
    self.ignored_conffiles_count = 0
    self.unverifiable_link_count = 0
    self.unverifiable_dir_count = 0
    self.__actions = []
    self.__package_md5sums = {}
    self.__tree = dpkg_helper.FilesystemNode()

  def check_path(self, path):
    normpath = os.path.normpath(os.path.join(os.getcwd(), path))
    self.__actions.append((AptCheck.__CHECK_PATH, normpath))

  def check_package(self, pkgname):
    self.__actions.append((AptCheck.__CHECK_PACKAGE, pkgname))

  def execute(self):
    time1 = time.time()
    # Build the list of paths that we care about and load a file tree for them.
    paths = [
        arg for action, arg in self.__actions if AptCheck.__CHECK_PATH == action
    ]
    if len(paths) > 0:
      # At least one path check requested, so we need to load by path.
      if "/" in paths:
        # This will match every path, so use no filter at all for marginally
        # improved speed.
        paths = None
      self.__tree.load_files_for_paths(paths)
      if self.no_ignore_conffiles:
        # Don't need to load the list.
        self.__conftree = None
      else:
        self.__conftree = dpkg_helper.FilesystemNode()
        self.__conftree.load_conffiles_for_paths(paths)
    # Also load all files for package checks into the same tree. We don't need
    # that for this class because we load the .list in __do_check_package,
    # but apt_fetcher_process needs them in the main tree so that it knows which
    # package to fetch for their files.
    for action, arg in self.__actions:
      if AptCheck.__CHECK_PACKAGE == action:
        self.__tree.load_files_for_pkgname(arg)
    self.__apt_helper = apt_helper.AptHelper()
    # Start our processing pipeline.
    (self.__md5sum_in,
     self.__apt_fetcher_in,
     self.__differ_out) = _launch_pipeline(
        self.__apt_helper, self.__tree, self.extraction_dir)
    # Execute all requested actions.
    if len(self.__actions) == 0:
      print "Warning: no actions specified. This is a no-op."
    else:
      for action, arg in self.__actions:
        if AptCheck.__CHECK_PATH == action:
          self.__do_check_path(arg)
        else:  # i.e., AptCheck.__CHECK_PACKAGE
          self.__do_check_package(arg)
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
    # Find the right node for this path in the tree.
    (last_node, node) = self.__tree.lookup(normpath)
    if self.no_ignore_conffiles:
      confnode = None
    else:
      confnode = self.__conftree.lookup(normpath)[1]
    # We do not check if a directory crossed in this step was a symlink--we
    # always use False. (This allows a user to effectively suppress the special
    # symlink logic by starting the traversal below the symlink.)
    self.__do_check(normpath, node, last_node, confnode, False, True)

  def __do_check_package(self, pkgname):
    tree = dpkg_helper.FilesystemNode()
    tree.load_files_for_pkgname(pkgname)
    if not tree.has_children():
      print "Package %s does not own any installed paths" % pkgname
      return
    if self.no_ignore_conffiles:
      conftree = None
    else:
      conftree = dpkg_helper.FilesystemNode()
      conftree.load_conffiles_for_pkgname(pkgname)
    self.__do_check("/", tree, None, conftree, False, False)

  def __do_check(self,
                 normpath,
                 node,
                 parent,
                 confnode,
                 within_symlink,
                 check_extras):
    try:
      st = os.stat(normpath)
    except:
      st = None
    try:
      lst = os.lstat(normpath)
    except:
      lst = None
    exists = lst != None
    isdir = st != None and stat.S_ISDIR(st.st_mode)
    isfile = st != None and stat.S_ISREG(st.st_mode)
    islink = lst != None and stat.S_ISLNK(lst.st_mode)
    path = normpath
    if isdir and path[-1] != "/":
      # Add a trailing slash so that the user can distinguish between
      # files and directories in the output.
      path = path + "/"
    if node != None and not exists:
      print "Missing path %s owned by %s" % (path, node.pkgname())
      self.__discrepancy()
    elif node == None and exists:
      if not check_extras:
        # If called from check_package() then we don't want to count or report
        # any extras because we will only have loaded one package's file tree,
        # so every other installed path will look like an "extra".
        return
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
      if parent != None:
        print "Extra path %s in directory owned by %s" % (
            path,
            parent.pkgname())
      else:
        print "Extra path " + path
      self.__discrepancy()
    elif node == None and not exists:
      # (We will only reach this case if the user explicitly started us at this
      # path.)
      print "Path %s not found in filesystem nor in any package" % path
    else:
      # Else it exists on disk and in packages.
      if node.has_children():
        # Then this path is supposed to be a directory. See if that's the case.
        if isdir:
          # Yes, so recurse and check the contents.
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
            print (
                "Warning: Package content installed under %s crosses "
                "unexpected symlink" % path)
            within_symlink = True
          try:
            ents = os.listdir(normpath)
          except OSError, e:
            print >> sys.stderr, "Can't recurse into %s:" % path, e
            self.__error()
            return
          ents.extend(node.children())
          ents.sort()
          last = None
          for ent in ents:
            if ent != last:
              if None != confnode:
                child_confnode = confnode.find_child(ent)
              else:
                child_confnode = None
              self.__do_check(
                os.path.join(normpath, ent),
                node.find_child(ent),
                node,
                child_confnode,
                within_symlink,
                check_extras)
            last = ent
        else:
          # Not a directory on disk, so it's either a regular file, a special
          # file, or a symlink to a non-directory. Regardless, that's a
          # discrepancy
          print "File %s is supposed to be a directory owned by %s" % (
              path,
              node.pkgname())
          self.__discrepancy()
      else:
        # dpkg node does not have children, so this path is not supposed to be
        # a directory with content, but unfortunately that doesn't distinguish
        # between the case of an empty directory, a regular file, or a symlink.
        # Regular files will be verified by virtue of the md5sum + diff check,
        # but for directories and symlinks there's no way for us to verify them.
        # In practice though it's unlikely that a path would get clobbered with
        # a different filetype.
        if islink:
          self.unverifiable_link_count = self.unverifiable_link_count + 1
          if self.report_unverifiable:
            print "Skipping unverifiable symbolic link %s owned by %s" % (
                path,
                node.pkgname())
        elif isdir:
          # The dpkg info says this directory should be empty, but an empty
          # directory is pointless, so most likely it's actually meant to be
          # filled with content that is created by the app or user after
          # installation. So we don't check for unowned files within this
          # directory.
          self.unverifiable_dir_count = self.unverifiable_dir_count + 1
          if self.report_unverifiable:
            print "Skipping unverifiable directory %s owned by %s" % (
                path,
                node.pkgname())
        elif isfile:
          # It is a regular file, so check its content. 
          if None != confnode:
            # Although we'd love to display diffs for conffiles, most packages
            # do not ship md5sums for their conffiles, so checking each conffile
            # usually requires re-downloading the package. Since there are tons
            # of conffiles on even a basic system, this is too costly, so by
            # default we don't check conffiles.
            self.ignored_conffiles_count = self.ignored_conffiles_count + 1
            return
          # Due to our above assumption, this path may not actually be a regular
          # file in the package, but if so then we will find that out when we
          # diff it.
          self.__check_file(node.pkgname(), normpath, path)
        else:
          # Special file. It's odd for a package to ship a special file, but not
          # impossible, so we warn about this but we don't consider a
          # discrepancy.
          print "Warning: Special file installed at %s owned by %s" % (
            path,
            node.pkgname())

  def __check_file(self, package, normpath, path):
    if not os.access(normpath, os.R_OK):
      print >> sys.stderr, "Don't have read permission for " + path
      self.__error()
      return
    if package not in self.__package_md5sums:
      # Haven't loaded this md5sums file yet. Do it now.
      try:
        f = open("/var/lib/dpkg/info/%s.md5sums" % package, "r")
      except:
        f = None
      if f != None:
        file_md5sums = {}
        for line in f:
          if line[-1] == "\n":
            end = -1
          else:
            end = 0
          file_md5sums["/" + line[34:end]] = line[:32]
        f.close()
      else:
        file_md5sums = None
      self.__package_md5sums[package] = file_md5sums
    else:
      file_md5sums = self.__package_md5sums[package]
    if file_md5sums == None or normpath not in file_md5sums:
      # Either this package does not ship an md5sums file or it does but doesn't
      # contain an md5sum for this file. In either case, we need to bypass the
      # md5sum verification stage and skip right to downloading the package for
      # comparison.
      self.__apt_fetcher_in.write(normpath + "\n")
      self.__apt_fetcher_in.flush()
    else:
      # We have the md5sum, so verify it first to avoid having to download
      # packages in the common case.
      md5sum = file_md5sums[normpath]
      self.__md5sum_in.write("%s  %s\n" % (md5sum, normpath))
      self.__md5sum_in.flush()

def version(fileobj):
  print >> fileobj, "apt-check " + VERSION

def usage(fileobj):
  version(fileobj)
  print >> fileobj, _USAGE

def _ensure_dir(path):
  if not os.path.isdir(path):
    os.mkdir(path, 0700)
  else:
    os.chmod(path, 0700)

def main(argv):
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
         _NO_IGNORE_EXTRAS,
         _NO_IGNORE_CONFFILES,
         _NO_OVERRIDE_CACHE,
         _REPORT_UNVERIFIABLE,
         _TEMPDIR + "="])
  except getopt.GetoptError, err:
    print >> sys.stderr, str(err)
    usage(sys.stderr)
    return 2
  apt_helper.initialize()
  apt_check = AptCheck(False,
                       False,
                       False,
                       None)
  no_override_cache = False
  tempdir = None
  for (opt, arg) in opts:
    opt = opt.lstrip("-")
    if opt == _PACKAGE or opt == _SHORT_PACKAGE:
      apt_check.check_package(arg)
    elif opt == _PATH or opt == _SHORT_PATH:
      apt_check.check_path(arg)
    elif opt == _APT_OPTION or opt == _SHORT_APT_OPTION:
      parts = arg.split("=")
      apt_helper.set_option(parts[0], "=".join(parts[1:]))
    elif opt == _HELP or opt == _SHORT_HELP:
      usage(sys.stdout)
      return 0
    elif opt == _VERSION or opt == _SHORT_VERSION:
      version(sys.stdout)
      return 0
    elif opt == _NO_IGNORE_EXTRAS:
      apt_check.no_ignore_extras = True
    elif opt == _NO_IGNORE_CONFFILES:
      apt_check.no_ignore_conffiles = True
    elif opt == _NO_OVERRIDE_CACHE:
      no_override_cache = True
    elif opt == _REPORT_UNVERIFIABLE:
      apt_check.report_unverifiable = True
    elif opt == _TEMPDIR:
      tempdir = arg
    else:
      # Shouldn't happen because getopt should have thrown an error.
      raise Exception("Unexpected option")
  for arg in args:
    # Try to guess what the user meant by this.
    if arg[0] == "/":
      # Treat it like --path
      apt_check.check_path(arg)
    elif arg[0].isalnum():
      # Treat it like --package
      apt_check.check_package(arg)
    else:
      print >> sys.stderr, "Don't know what to do with \"%s\"" % arg
      usage(sys.stderr)
      return 2
  # Create default tempdir if none specified.
  if tempdir == None:
    tempdir = os.path.join(tempfile.gettempdir(),
                           "apt-check_" + str(os.getuid()))
    _ensure_dir(tempdir)
  if tempdir.find(" ") != -1:
    # This would mess up our processing pipeline.
    raise Exception("Spaces are not supported in the tempdir path")
  if not no_override_cache and os.getuid() != 0:
    # Set default archive dir to one we can actually write to.
    archive_dir = os.path.join(tempdir, "archives")
    _ensure_dir(archive_dir)
    _ensure_dir(os.path.join(archive_dir, "partial"))
    apt_helper.set_option("Dir::Cache::Archives", archive_dir)
  extraction_dir = os.path.join(tempdir, "extracted")
  _ensure_dir(extraction_dir)
  apt_check.extraction_dir = extraction_dir
  apt_check.execute()
  # Recursively delete the extracted packages.
  shutil.rmtree(extraction_dir)

if __name__ == "__main__":
  try:
    exitcode = main(sys.argv[1:])
  except KeyboardInterrupt:
    exitcode = 130
  sys.exit(exitcode)
