#/usr/bin/python

## Amazon S3 manager
## Author: Michal Ludvig <michal@logix.cz>
##         http://www.logix.cz/michal
## License: GPL Version 2

import sys
import time
reload(sys)
sys.setdefaultencoding("utf-8")
sys.path.append('/home/adminuser/s3cfg/')
if float("%d.%d" %(sys.version_info[0], sys.version_info[1])) < 2.4:
    sys.stderr.write("ERROR: Python 2.4 or higher required, sorry.\n")
    sys.exit(1)

import logging
import time
import os
import re
import errno
import glob
import traceback
import codecs
import locale
import subprocess
import htmlentitydefs
import socket
import shutil
import tempfile
import S3.Exceptions

from copy import copy
from optparse import OptionParser, Option, OptionValueError, IndentedHelpFormatter
from logging import debug, info, warning, error
from distutils.spawn import find_executable

def output(message):
    sys.stdout.write(message + "\n")
    sys.stdout.flush()

def check_args_type(args, type, verbose_type):
    for arg in args:
        if S3Uri(arg).type != type:
            raise ParameterError("Expecting %s instead of '%s'" % (verbose_type, arg))

def cmd_du(args):
    s3 = S3(Config())
    if len(args) > 0:
        uri = S3Uri(args[0])
        if uri.type == "s3" and uri.has_bucket():
            subcmd_bucket_usage(s3, uri)
            return
    subcmd_bucket_usage_all(s3)

def subcmd_bucket_usage_all(s3):
    response = s3.list_all_buckets()
    buckets_size = 0
    for bucket in response["list"]:
        size = subcmd_bucket_usage(s3, S3Uri("s3://" + bucket["Name"]))
        if size != None:
            buckets_size += size
    total_size, size_coeff = formatSize(buckets_size, Config().human_readable_sizes)
    total_size_str = str(total_size) + size_coeff
    output(u"".rjust(8, "-"))
    output(u"%s Total" % (total_size_str.ljust(8)))

def subcmd_bucket_usage(s3, uri):
    bucket = uri.bucket()
    object = uri.object()

    if object.endswith('*'):
        object = object[:-1]

    bucket_size = 0
    # iterate and store directories to traverse, while summing objects:
    dirs = [object]
    while dirs:
        try:
            response = s3.bucket_list(bucket, prefix=dirs.pop())
        except S3Error, e:
            if S3.codes.has_key(e.info["Code"]):
                error(S3.codes[e.info["Code"]] % bucket)
                return
            else:
                raise

        # objects in the current scope:
        for obj in response["list"]:
            bucket_size += int(obj["Size"])

        # directories found in current scope:
        for obj in response["common_prefixes"]:
            dirs.append(obj["Prefix"])

    total_size, size_coeff = formatSize(bucket_size, Config().human_readable_sizes)
    total_size_str = str(total_size) + size_coeff
    output(u"%s %s" % (total_size_str.ljust(8), uri))
    return bucket_size

def cmd_ls(args):
    s3 = S3(Config())
    if len(args) > 0:
        uri = S3Uri(args[0])
        if uri.type == "s3" and uri.has_bucket():
            return subcmd_bucket_list(s3, uri)
    return subcmd_buckets_list_all(s3)

def cmd_buckets_list_all_all(args):
    s3 = S3(Config())

    response = s3.list_all_buckets()

    for bucket in response["list"]:
        subcmd_bucket_list(s3, S3Uri("s3://" + bucket["Name"]))
        output(u"")

def subcmd_buckets_list_all(s3):
    response = s3.list_all_buckets()
    for bucket in response["list"]:
        output(u"%s  s3://%s" % (
            formatDateTime(bucket["CreationDate"]),
            bucket["Name"],
            ))
    return response

def subcmd_bucket_list(s3, uri):
    bucket = uri.bucket()
    prefix = uri.object()

    debug(u"Bucket 's3://%s':" % bucket)
    if prefix.endswith('*'):
        prefix = prefix[:-1]
    try:
        response = s3.bucket_list(bucket, prefix = prefix)
    except S3Error, e:
        if S3.codes.has_key(e.info["Code"]):
            error(S3.codes[e.info["Code"]] % bucket)
            return
        else:
            raise

    if cfg.list_md5:
        format_string = u"%(timestamp)16s %(size)9s%(coeff)1s  %(md5)32s  %(uri)s"
    else:
        format_string = u"%(timestamp)16s %(size)9s%(coeff)1s  %(uri)s"

    for prefix in response['common_prefixes']:
        try:
            prefixprefix = prefix["Prefix"]
        except KeyError:
            prefixprefix =  ""
        output(format_string % {
            "timestamp": "",
            "size": "DIR",
            "coeff": "",
            "md5": "",
            "uri": uri.compose_uri(bucket, prefixprefix)})
    return response['list']
    for object in response["list"]:
        size, size_coeff = formatSize(object["Size"], Config().human_readable_sizes)
        output(format_string % {
            "timestamp": formatDateTime(object["LastModified"]),
            "size" : str(size),
            "coeff": size_coeff,
            "md5" : object['ETag'].strip('"'),
            "uri": uri.compose_uri(bucket, object["Key"]),
            })

def cmd_bucket_create(args):
    s3 = S3(Config())
    for arg in args:
        uri = S3Uri(arg)
        if not uri.type == "s3" or not uri.has_bucket() or uri.has_object():
            raise ParameterError("Expecting S3 URI with just the bucket name set instead of '%s'" % arg)
        try:
            response = s3.bucket_create(uri.bucket(), cfg.bucket_location)
            output(u"Bucket '%s' created" % uri.uri())
        except S3Error, e:
            if S3.codes.has_key(e.info["Code"]):
                error(S3.codes[e.info["Code"]] % uri.bucket())
                return
            else:
                raise

def cmd_website_info(args):
    s3 = S3(Config())
    for arg in args:
        uri = S3Uri(arg)
        if not uri.type == "s3" or not uri.has_bucket() or uri.has_object():
            raise ParameterError("Expecting S3 URI with just the bucket name set instead of '%s'" % arg)
        try:
            response = s3.website_info(uri, cfg.bucket_location)
            if response:
                output(u"Bucket %s: Website configuration" % uri.uri())
                output(u"Website endpoint: %s" % response['website_endpoint'])
                output(u"Index document:   %s" % response['index_document'])
                output(u"Error document:   %s" % response['error_document'])
            else:
                output(u"Bucket %s: Unable to receive website configuration." % (uri.uri()))
        except S3Error, e:
            if S3.codes.has_key(e.info["Code"]):
                error(S3.codes[e.info["Code"]] % uri.bucket())
                return
            else:
                raise

def cmd_website_create(args):
    s3 = S3(Config())
    for arg in args:
        uri = S3Uri(arg)
        if not uri.type == "s3" or not uri.has_bucket() or uri.has_object():
            raise ParameterError("Expecting S3 URI with just the bucket name set instead of '%s'" % arg)
        try:
            response = s3.website_create(uri, cfg.bucket_location)
            output(u"Bucket '%s': website configuration created." % (uri.uri()))
        except S3Error, e:
            if S3.codes.has_key(e.info["Code"]):
                error(S3.codes[e.info["Code"]] % uri.bucket())
                return
            else:
                raise

def cmd_website_delete(args):
    s3 = S3(Config())
    for arg in args:
        uri = S3Uri(arg)
        if not uri.type == "s3" or not uri.has_bucket() or uri.has_object():
            raise ParameterError("Expecting S3 URI with just the bucket name set instead of '%s'" % arg)
        try:
            response = s3.website_delete(uri, cfg.bucket_location)
            output(u"Bucket '%s': website configuration deleted." % (uri.uri()))
        except S3Error, e:
            if S3.codes.has_key(e.info["Code"]):
                error(S3.codes[e.info["Code"]] % uri.bucket())
                return
            else:
                raise

def cmd_bucket_delete(args):
    def _bucket_delete_one(uri):
        try:
            response = s3.bucket_delete(uri.bucket())
        except S3Error, e:
            if e.info['Code'] == 'BucketNotEmpty' and (cfg.force or cfg.recursive):
                warning(u"Bucket is not empty. Removing all the objects from it first. This may take some time...")
                subcmd_object_del_uri(uri.uri(), recursive = True)
                return _bucket_delete_one(uri)
            elif S3.codes.has_key(e.info["Code"]):
                error(S3.codes[e.info["Code"]] % uri.bucket())
                return
            else:
                raise

    s3 = S3(Config())
    for arg in args:
        uri = S3Uri(arg)
        if not uri.type == "s3" or not uri.has_bucket() or uri.has_object():
            raise ParameterError("Expecting S3 URI with just the bucket name set instead of '%s'" % arg)
        _bucket_delete_one(uri)
        output(u"Bucket '%s' removed" % uri.uri())

def cmd_object_put(args):
    cfg = Config()
    s3 = S3(cfg)

    if len(args) == 0:
        raise ParameterError("Nothing to upload. Expecting a local file or directory and a S3 URI destination.")
    print "arugment s pringint"
    print args
    ## Normalize URI to convert s3://bkt to s3://bkt/ (trailing slash)
    pop1 = args.pop()
    print "popping 1" 
    print pop1
    destination_base_uri = S3Uri(pop1)
    if destination_base_uri.type != 's3':
        raise ParameterError("Destination must be S3Uri. Got: %s" % destination_base_uri)
    destination_base = str(destination_base_uri)

    if len(args) == 0:
        raise ParameterError("Nothing to upload. Expecting a local file or directory.")
    print args
    fileobj = args.pop()
    local_list, single_file_local = fetch_local_list(fileobj)

    local_list, exclude_list = filter_exclude_include(local_list)

    local_count = len(local_list)
    local_list[fileobj.filename] = {}
    print "printing the list" 
    print local_list
#    local_list[args.pop().filename] = {} 
    #sys.exit()
    info(u"Summary: %d local files to upload" % local_count)

    if local_count > 0:
        if not single_file_local and '-' in local_list.keys():
            raise ParameterError("Cannot specify multiple local files if uploading from '-' (ie stdin)")
        elif single_file_local and local_list.keys()[0] == "-" and destination_base.endswith("/"):
            raise ParameterError("Destination S3 URI must not end with '/' when uploading from stdin.")
        elif not destination_base.endswith("/"):
            if not single_file_local:
                raise ParameterError("Destination S3 URI must end with '/' (ie must refer to a directory on the remote side).")
            local_list[local_list.keys()[0]]['remote_uri'] = unicodise(destination_base)
        else:
            for key in local_list:
                local_list[key]['remote_uri'] = unicodise(destination_base + key)

    if cfg.dry_run:
        for key in exclude_list:
            output(u"exclude: %s" % unicodise(key))
        for key in local_list:
            if key != "-":
                nicekey = local_list[key]['full_name_unicode']
            else:
                nicekey = "<stdin>"
            output(u"upload: %s -> %s" % (nicekey, local_list[key]['remote_uri']))

        warning(u"Exiting now because of --dry-run")
        return

    fileName = str(args.pop())
    seq = 0
    for key in local_list:
        seq += 1
	local_list[key]['remote_uri'] = destination_base + fileName
        uri_final = S3Uri(local_list[key]['remote_uri'])
	print "uri_final is " 
	print uri_final
        extra_headers = copy(cfg.extra_headers)
        #full_name_orig = local_list[key]['full_name']
        #full_name = full_name_orig
	full_name =  fileobj
        seq_label = "[%d of %d]" % (seq, local_count)
        if Config().encrypt:
            exitcode, full_name, extra_headers["x-amz-meta-s3tools-gpgenc"] = gpg_encrypt(full_name_orig)
        try:
            response = s3.object_put(full_name, uri_final, extra_headers, extra_label = seq_label)
        except S3UploadError, e:
            error(u"Upload of '%s' failed too many times. Skipping that file." % full_name_orig)
            continue
        except InvalidFileError, e:
            warning(u"File can not be uploaded: %s" % e)
            continue
        speed_fmt = formatSize(response["speed"], human_readable = True, floating_point = True)
        if not Config().progress_meter:
            output(u"File '%s' stored as '%s' (%d bytes in %0.1f seconds, %0.2f %sB/s) %s" %
                (unicodise(full_name_orig), uri_final, response["size"], response["elapsed"],
                speed_fmt[0], speed_fmt[1], seq_label))
        if Config().acl_public:
            output(u"Public URL of the object is: %s" %
                (uri_final.public_url()))
        if Config().encrypt and full_name != full_name_orig:
            debug(u"Removing temporary encrypted file: %s" % unicodise(full_name))
            os.remove(full_name)

def cmd_object_get(args):
    cfg = Config()
    s3 = S3(cfg)

    ## Check arguments:
    ## if not --recursive:
    ##   - first N arguments must be S3Uri
    ##   - if the last one is S3 make current dir the destination_base
    ##   - if the last one is a directory:
    ##       - take all 'basenames' of the remote objects and
    ##         make the destination name be 'destination_base'+'basename'
    ##   - if the last one is a file or not existing:
    ##       - if the number of sources (N, above) == 1 treat it
    ##         as a filename and save the object there.
    ##       - if there's more sources -> Error
    ## if --recursive:
    ##   - first N arguments must be S3Uri
    ##       - for each Uri get a list of remote objects with that Uri as a prefix
    ##       - apply exclude/include rules
    ##       - each list item will have MD5sum, Timestamp and pointer to S3Uri
    ##         used as a prefix.
    ##   - the last arg may be '-' (stdout)
    ##   - the last arg may be a local directory - destination_base
    ##   - if the last one is S3 make current dir the destination_base
    ##   - if the last one doesn't exist check remote list:
    ##       - if there is only one item and its_prefix==its_name
    ##         download that item to the name given in last arg.
    ##       - if there are more remote items use the last arg as a destination_base
    ##         and try to create the directory (incl. all parents).
    ##
    ## In both cases we end up with a list mapping remote object names (keys) to local file names.

    ## Each item will be a dict with the following attributes
    # {'remote_uri', 'local_filename'}
    download_list = []

    if len(args) == 0:
        raise ParameterError("Nothing to download. Expecting S3 URI.")

    if S3Uri(args[-1]).type == 'file':
        destination_base = args.pop()
    else:
        destination_base = "."

    if len(args) == 0:
        raise ParameterError("Nothing to download. Expecting S3 URI.")

    remote_list = fetch_remote_list(args, require_attribs = False)
    remote_list, exclude_list = filter_exclude_include(remote_list)

    remote_count = len(remote_list)

    info(u"Summary: %d remote files to download" % remote_count)

    if remote_count > 0:
        if destination_base == "-":
            ## stdout is ok for multiple remote files!
            for key in remote_list:
                remote_list[key]['local_filename'] = "-"
        elif not os.path.isdir(destination_base):
            ## We were either given a file name (existing or not)
            if remote_count > 1:
                raise ParameterError("Destination must be a directory or stdout when downloading multiple sources.")
            remote_list[remote_list.keys()[0]]['local_filename'] = deunicodise(destination_base)
        elif os.path.isdir(destination_base):
            if destination_base[-1] != os.path.sep:
                destination_base += os.path.sep
            for key in remote_list:
                remote_list[key]['local_filename'] = destination_base + key
        else:
            raise InternalError("WTF? Is it a dir or not? -- %s" % destination_base)

    if cfg.dry_run:
        for key in exclude_list:
            output(u"exclude: %s" % unicodise(key))
        for key in remote_list:
            output(u"download: %s -> %s" % (remote_list[key]['object_uri_str'], remote_list[key]['local_filename']))

        warning(u"Exiting now because of --dry-run")
        return

    seq = 0
    for key in remote_list:
        seq += 1
        item = remote_list[key]
        uri = S3Uri(item['object_uri_str'])
        ## Encode / Decode destination with "replace" to make sure it's compatible with current encoding
        destination = unicodise_safe(item['local_filename'])
        seq_label = "[%d of %d]" % (seq, remote_count)

        start_position = 0

        if destination == "-":
            ## stdout
            dst_stream = sys.__stdout__
        else:
            ## File
            try:
                file_exists = os.path.exists(destination)
                #try:
                #    dst_stream = open(destination, "ab")
                #except IOError, e:
                #    if e.errno == errno.ENOENT:
                #        basename = destination[:destination.rindex(os.path.sep)]
                #        info(u"Creating directory: %s" % basename)
                #        os.makedirs(basename)
                #        dst_stream = open(destination, "ab")
                #    else:
                #        raise
                #if file_exists:
                #    if Config().get_continue:
                #        start_position = dst_stream.tell()
                #    elif Config().force:
                #        start_position = 0L
                #        dst_stream.seek(0L)
                #        dst_stream.truncate()
                #    elif Config().skip_existing:
                #        info(u"Skipping over existing file: %s" % (destination))
                #        continue
                #    else:
                #        dst_stream.close()
                #        raise ParameterError(u"File %s already exists. Use either of --force / --continue / --skip-existing or give it a new name." % destination)
            except IOError, e:
                error(u"Skipping %s: %s" % (destination, e.strerror))
                continue
        try:
            response = s3.object_get(uri, "sai sif", start_position = start_position, extra_label = seq_label)
        except S3Error, e:
            if not file_exists: # Delete, only if file didn't exist before!
                debug(u"object_get failed for '%s', deleting..." % (destination,))
                os.unlink(destination)
            raise
	print response
        return response
        if response["headers"].has_key("x-amz-meta-s3tools-gpgenc"):
            gpg_decrypt(destination, response["headers"]["x-amz-meta-s3tools-gpgenc"])
            response["size"] = os.stat(destination)[6]
        if not Config().progress_meter and destination != "-":
            speed_fmt = formatSize(response["speed"], human_readable = True, floating_point = True)
            output(u"File %s saved as '%s' (%d bytes in %0.1f seconds, %0.2f %sB/s)" %
                (uri, destination, response["size"], response["elapsed"], speed_fmt[0], speed_fmt[1]))
        if Config().delete_after_fetch:
            s3.object_delete(uri)
            output(u"File %s removed after fetch" % (uri))

def cmd_object_del(args):
    for uri_str in args:
        uri = S3Uri(uri_str)
        if uri.type != "s3":
            raise ParameterError("Expecting S3 URI instead of '%s'" % uri_str)
        if not uri.has_object():
            if Config().recursive and not Config().force:
                raise ParameterError("Please use --force to delete ALL contents of %s" % uri_str)
            elif not Config().recursive:
                raise ParameterError("File name required, not only the bucket name. Alternatively use --recursive")
        subcmd_object_del_uri(uri_str)

def subcmd_object_del_uri(uri_str, recursive = None):
    s3 = S3(cfg)

    if recursive is None:
        recursive = cfg.recursive

    remote_list = fetch_remote_list(uri_str, require_attribs = False, recursive = recursive)
    remote_list, exclude_list = filter_exclude_include(remote_list)

    remote_count = len(remote_list)

    info(u"Summary: %d remote files to delete" % remote_count)

    if cfg.dry_run:
        for key in exclude_list:
            output(u"exclude: %s" % unicodise(key))
        for key in remote_list:
            output(u"delete: %s" % remote_list[key]['object_uri_str'])

        warning(u"Exiting now because of --dry-run")
        return

    for key in remote_list:
        item = remote_list[key]
        response = s3.object_delete(S3Uri(item['object_uri_str']))
        output(u"File %s deleted" % item['object_uri_str'])

def subcmd_cp_mv(args, process_fce, action_str, message):
    if len(args) < 2:
        raise ParameterError("Expecting two or more S3 URIs for " + action_str)
    dst_base_uri = S3Uri(args.pop())
    if dst_base_uri.type != "s3":
        raise ParameterError("Destination must be S3 URI. To download a file use 'get' or 'sync'.")
    destination_base = dst_base_uri.uri()

    remote_list = fetch_remote_list(args, require_attribs = False)
    remote_list, exclude_list = filter_exclude_include(remote_list)

    remote_count = len(remote_list)

    info(u"Summary: %d remote files to %s" % (remote_count, action_str))

    if cfg.recursive:
        if not destination_base.endswith("/"):
            destination_base += "/"
        for key in remote_list:
            remote_list[key]['dest_name'] = destination_base + key
    else:
        for key in remote_list:
            if destination_base.endswith("/"):
                remote_list[key]['dest_name'] = destination_base + key
            else:
                remote_list[key]['dest_name'] = destination_base

    if cfg.dry_run:
        for key in exclude_list:
            output(u"exclude: %s" % unicodise(key))
        for key in remote_list:
            output(u"%s: %s -> %s" % (action_str, remote_list[key]['object_uri_str'], remote_list[key]['dest_name']))

        warning(u"Exiting now because of --dry-run")
        return

    seq = 0
    for key in remote_list:
        seq += 1
        seq_label = "[%d of %d]" % (seq, remote_count)

        item = remote_list[key]
        src_uri = S3Uri(item['object_uri_str'])
        dst_uri = S3Uri(item['dest_name'])

        extra_headers = copy(cfg.extra_headers)
        response = process_fce(src_uri, dst_uri, extra_headers)
        output(message % { "src" : src_uri, "dst" : dst_uri })
        if Config().acl_public:
            info(u"Public URL is: %s" % dst_uri.public_url())

def cmd_cp(args):
    s3 = S3(Config())
    subcmd_cp_mv(args, s3.object_copy, "copy", "File %(src)s copied to %(dst)s")

def cmd_mv(args):
    s3 = S3(Config())
    subcmd_cp_mv(args, s3.object_move, "move", "File %(src)s moved to %(dst)s")

def cmd_info(args):
    s3 = S3(Config())

    while (len(args)):
        uri_arg = args.pop(0)
        uri = S3Uri(uri_arg)
        if uri.type != "s3" or not uri.has_bucket():
            raise ParameterError("Expecting S3 URI instead of '%s'" % uri_arg)

        try:
            if uri.has_object():
                info = s3.object_info(uri)
                output(u"%s (object):" % uri.uri())
                output(u"   File size: %s" % info['headers']['content-length'])
                output(u"   Last mod:  %s" % info['headers']['last-modified'])
                output(u"   MIME type: %s" % info['headers']['content-type'])
                output(u"   MD5 sum:   %s" % info['headers']['etag'].strip('"'))
            else:
                info = s3.bucket_info(uri)
                output(u"%s (bucket):" % uri.uri())
                output(u"   Location:  %s" % info['bucket-location'])
            acl = s3.get_acl(uri)
            acl_grant_list = acl.getGrantList()

            try:
                policy = s3.get_policy(uri)
                output(u"   policy: %s" % policy)
            except:
                output(u"   policy: none")
            
            for grant in acl_grant_list:
                output(u"   ACL:       %s: %s" % (grant['grantee'], grant['permission']))
            if acl.isAnonRead():
                output(u"   URL:       %s" % uri.public_url())

        except S3Error, e:
            if S3.codes.has_key(e.info["Code"]):
                error(S3.codes[e.info["Code"]] % uri.bucket())
                return
            else:
                raise

def cmd_sync_remote2remote(args):
    def _do_deletes(s3, dst_list):
        # Delete items in destination that are not in source
        if cfg.dry_run:
            for key in dst_list:
                output(u"delete: %s" % dst_list[key]['object_uri_str'])
        else:
            for key in dst_list:
                uri = S3Uri(dst_list[key]['object_uri_str'])
                s3.object_delete(uri)
                output(u"deleted: '%s'" % uri)

    s3 = S3(Config())

    # Normalise s3://uri (e.g. assert trailing slash)
    destination_base = unicode(S3Uri(args[-1]))

    src_list = fetch_remote_list(args[:-1], recursive = True, require_attribs = True)
    dst_list = fetch_remote_list(destination_base, recursive = True, require_attribs = True)

    src_count = len(src_list)
    dst_count = len(dst_list)

    info(u"Found %d source files, %d destination files" % (src_count, dst_count))

    src_list, exclude_list = filter_exclude_include(src_list)

    src_list, dst_list, update_list, copy_pairs = compare_filelists(src_list, dst_list, src_remote = True, dst_remote = True, delay_updates = cfg.delay_updates)

    src_count = len(src_list)
    update_count = len(update_list)
    dst_count = len(dst_list)

    print(u"Summary: %d source files to copy, %d files at destination to delete" % (src_count, dst_count))

    ### Populate 'target_uri' only if we've got something to sync from src to dst
    for key in src_list:
        src_list[key]['target_uri'] = destination_base + key
    for key in update_list:
        update_list[key]['target_uri'] = destination_base + key

    if cfg.dry_run:
        for key in exclude_list:
            output(u"exclude: %s" % unicodise(key))
        if cfg.delete_removed:
            for key in dst_list:
                output(u"delete: %s" % dst_list[key]['object_uri_str'])
        for key in src_list:
            output(u"Sync: %s -> %s" % (src_list[key]['object_uri_str'], src_list[key]['target_uri']))
        warning(u"Exiting now because of --dry-run")
        return

    # if there are copy pairs, we can't do delete_before, on the chance
    # we need one of the to-be-deleted files as a copy source.
    if len(copy_pairs) > 0:
        cfg.delete_after = True

    # Delete items in destination that are not in source
    if cfg.delete_removed and not cfg.delete_after:
        _do_deletes(s3, dst_list)

    def _upload(src_list, seq, src_count):
        file_list = src_list.keys()
        file_list.sort()
        for file in file_list:
            seq += 1
            item = src_list[file]
            src_uri = S3Uri(item['object_uri_str'])
            dst_uri = S3Uri(item['target_uri'])
            seq_label = "[%d of %d]" % (seq, src_count)
            extra_headers = copy(cfg.extra_headers)
            try:
                response = s3.object_copy(src_uri, dst_uri, extra_headers)
                output("File %(src)s copied to %(dst)s" % { "src" : src_uri, "dst" : dst_uri })
            except S3Error, e:
                error("File %(src)s could not be copied: %(e)s" % { "src" : src_uri, "e" : e })
        return seq

    # Perform the synchronization of files
    timestamp_start = time.time()
    seq = 0
    seq = _upload(src_list, seq, src_count + update_count)
    seq = _upload(update_list, seq, src_count + update_count)
    n_copied, bytes_saved = remote_copy(s3, copy_pairs, destination_base)

    total_elapsed = time.time() - timestamp_start
    outstr = "Done. Copied %d files in %0.1f seconds, %0.2f files/s" % (seq, total_elapsed, seq/total_elapsed)
    if seq > 0:
        output(outstr)
    else:
        info(outstr)

    # Delete items in destination that are not in source
    if cfg.delete_removed and cfg.delete_after:
        _do_deletes(s3, dst_list)

def cmd_sync_remote2local(args):
    def _do_deletes(local_list):
        for key in local_list:
            os.unlink(local_list[key]['full_name'])
            output(u"deleted: %s" % local_list[key]['full_name_unicode'])

    s3 = S3(Config())

    destination_base = args[-1]
    local_list, single_file_local = fetch_local_list(destination_base, recursive = True)
    remote_list = fetch_remote_list(args[:-1], recursive = True, require_attribs = True)

    local_count = len(local_list)
    remote_count = len(remote_list)

    info(u"Found %d remote files, %d local files" % (remote_count, local_count))

    remote_list, exclude_list = filter_exclude_include(remote_list)

    remote_list, local_list, update_list, copy_pairs = compare_filelists(remote_list, local_list, src_remote = True, dst_remote = False, delay_updates = cfg.delay_updates)

    local_count = len(local_list)
    remote_count = len(remote_list)
    update_count = len(update_list)
    copy_pairs_count = len(copy_pairs)

    info(u"Summary: %d remote files to download, %d local files to delete, %d local files to hardlink" % (remote_count + update_count, local_count, copy_pairs_count))

    def _set_local_filename(remote_list, destination_base):
        if len(remote_list) == 0:
            return
        if not os.path.isdir(destination_base):
            ## We were either given a file name (existing or not) or want STDOUT
            if len(remote_list) > 1:
                raise ParameterError("Destination must be a directory when downloading multiple sources.")
            remote_list[remote_list.keys()[0]]['local_filename'] = deunicodise(destination_base)
        else:
            if destination_base[-1] != os.path.sep:
                destination_base += os.path.sep
            for key in remote_list:
                local_filename = destination_base + key
                if os.path.sep != "/":
                    local_filename = os.path.sep.join(local_filename.split("/"))
                remote_list[key]['local_filename'] = deunicodise(local_filename)

    _set_local_filename(remote_list, destination_base)
    _set_local_filename(update_list, destination_base)

    if cfg.dry_run:
        for key in exclude_list:
            output(u"exclude: %s" % unicodise(key))
        if cfg.delete_removed:
            for key in local_list:
                output(u"delete: %s" % local_list[key]['full_name_unicode'])
        for key in remote_list:
            output(u"download: %s -> %s" % (unicodise(remote_list[key]['object_uri_str']), unicodise(remote_list[key]['local_filename'])))
        for key in update_list:
            output(u"download: %s -> %s" % (update_list[key]['object_uri_str'], update_list[key]['local_filename']))

        warning(u"Exiting now because of --dry-run")
        return

    # if there are copy pairs, we can't do delete_before, on the chance
    # we need one of the to-be-deleted files as a copy source.
    if len(copy_pairs) > 0:
        cfg.delete_after = True

    if cfg.delete_removed and not cfg.delete_after:
        _do_deletes(local_list)

    def _download(remote_list, seq, total, total_size, dir_cache):
        file_list = remote_list.keys()
        file_list.sort()
        for file in file_list:
            seq += 1
            item = remote_list[file]
            uri = S3Uri(item['object_uri_str'])
            dst_file = item['local_filename']
            seq_label = "[%d of %d]" % (seq, total)
            try:
                dst_dir = os.path.dirname(dst_file)
                if not dir_cache.has_key(dst_dir):
                    dir_cache[dst_dir] = Utils.mkdir_with_parents(dst_dir)
                if dir_cache[dst_dir] == False:
                    warning(u"%s: destination directory not writable: %s" % (file, dst_dir))
                    continue
                try:
                    debug(u"dst_file=%s" % unicodise(dst_file))
                    # create temporary files (of type .s3cmd.XXXX.tmp) in the same directory
                    # for downloading and then rename once downloaded
                    chkptfd, chkptfname = tempfile.mkstemp(".tmp",".s3cmd.",os.path.dirname(dst_file))
                    debug(u"created chkptfname=%s" % unicodise(chkptfname))
                    dst_stream = os.fdopen(chkptfd, "wb")
                    response = s3.object_get(uri, dst_stream, extra_label = seq_label)
                    dst_stream.close()
                    # download completed, rename the file to destination
                    os.rename(chkptfname, dst_file)

                    # set permissions on destination file
                    original_umask = os.umask(0);
                    os.umask(original_umask);
                    mode = 0777 - original_umask;
                    debug(u"mode=%s" % oct(mode))
                    
                    os.chmod(dst_file, mode);
                    
                    debug(u"renamed chkptfname=%s to dst_file=%s" % (unicodise(chkptfname), unicodise(dst_file)))
                    if response['headers'].has_key('x-amz-meta-s3cmd-attrs') and cfg.preserve_attrs:
                        attrs = parse_attrs_header(response['headers']['x-amz-meta-s3cmd-attrs'])
                        if attrs.has_key('mode'):
                            os.chmod(dst_file, int(attrs['mode']))
                        if attrs.has_key('mtime') or attrs.has_key('atime'):
                            mtime = attrs.has_key('mtime') and int(attrs['mtime']) or int(time.time())
                            atime = attrs.has_key('atime') and int(attrs['atime']) or int(time.time())
                            os.utime(dst_file, (atime, mtime))
                        ## FIXME: uid/gid / uname/gname handling comes here! TODO
                except OSError, e:
                    try: 
                        dst_stream.close() 
                        os.remove(chkptfname)
                    except: pass
                    if e.errno == errno.EEXIST:
                        warning(u"%s exists - not overwriting" % (dst_file))
                        continue
                    if e.errno in (errno.EPERM, errno.EACCES):
                        warning(u"%s not writable: %s" % (dst_file, e.strerror))
                        continue
                    if e.errno == errno.EISDIR:
                        warning(u"%s is a directory - skipping over" % dst_file)
                        continue
                    raise e
                except KeyboardInterrupt:
                    try: 
                        dst_stream.close()
                        os.remove(chkptfname)
                    except: pass
                    warning(u"Exiting after keyboard interrupt")
                    return
                except Exception, e:
                    try: 
                        dst_stream.close()
                        os.remove(chkptfname)
                    except: pass
                    error(u"%s: %s" % (file, e))
                    continue
                # We have to keep repeating this call because
                # Python 2.4 doesn't support try/except/finally
                # construction :-(
                try: 
                    dst_stream.close()
                    os.remove(chkptfname)
                except: pass
            except S3DownloadError, e:
                error(u"%s: download failed too many times. Skipping that file." % file)
                continue
            speed_fmt = formatSize(response["speed"], human_readable = True, floating_point = True)
            if not Config().progress_meter:
                output(u"File '%s' stored as '%s' (%d bytes in %0.1f seconds, %0.2f %sB/s) %s" %
                    (uri, unicodise(dst_file), response["size"], response["elapsed"], speed_fmt[0], speed_fmt[1],
                    seq_label))
            total_size += response["size"]
            if Config().delete_after_fetch:
                s3.object_delete(uri)
                output(u"File '%s' removed after syncing" % (uri))
        return seq, total_size

    total_size = 0
    total_elapsed = 0.0
    timestamp_start = time.time()
    dir_cache = {}
    seq = 0
    seq, total_size = _download(remote_list, seq, remote_count + update_count, total_size, dir_cache)
    seq, total_size = _download(update_list, seq, remote_count + update_count, total_size, dir_cache)

    failed_copy_list = local_copy(copy_pairs, destination_base)
    _set_local_filename(failed_copy_list, destination_base)
    seq, total_size = _download(failed_copy_list, seq, len(failed_copy_list) + remote_count + update_count, total_size, dir_cache)

    total_elapsed = time.time() - timestamp_start
    speed_fmt = formatSize(total_size/total_elapsed, human_readable = True, floating_point = True)

    # Only print out the result if any work has been done or
    # if the user asked for verbose output
    outstr = "Done. Downloaded %d bytes in %0.1f seconds, %0.2f %sB/s" % (total_size, total_elapsed, speed_fmt[0], speed_fmt[1])
    if total_size > 0:
        output(outstr)
    else:
        info(outstr)

    if cfg.delete_removed and cfg.delete_after:
        _do_deletes(local_list)

def local_copy(copy_pairs, destination_base):
    # Do NOT hardlink local files by default, that'd be silly
    # For instance all empty files would become hardlinked together!

    failed_copy_list = FileDict()
    for (src_obj, dst1, relative_file) in copy_pairs:
        src_file = os.path.join(destination_base, dst1)
        dst_file = os.path.join(destination_base, relative_file)
        dst_dir = os.path.dirname(dst_file)
        try:
            if not os.path.isdir(dst_dir):
                debug("MKDIR %s" % dst_dir)
                os.makedirs(dst_dir)
            debug(u"Copying %s to %s" % (src_file, dst_file))
            shutil.copy2(src_file, dst_file)
        except (IOError, OSError), e:
            warning(u'Unable to hardlink or copy files %s -> %s: %s' % (src_file, dst_file, e))
            failed_copy_list[relative_file] = src_obj
    return failed_copy_list

def remote_copy(s3, copy_pairs, destination_base):
    saved_bytes = 0
    for (src_obj, dst1, dst2) in copy_pairs:
        debug(u"Remote Copying from %s to %s" % (dst1, dst2))
        dst1_uri = S3Uri(destination_base + dst1)
        dst2_uri = S3Uri(destination_base + dst2)
        extra_headers = copy(cfg.extra_headers)
        try:
            s3.object_copy(dst1_uri, dst2_uri, extra_headers)
            info = s3.object_info(dst2_uri)
            saved_bytes = saved_bytes + int(info['headers']['content-length'])
            output(u"remote copy: %s -> %s" % (dst1, dst2))
        except:
            raise
    return (len(copy_pairs), saved_bytes)


def cmd_sync_local2remote(args):
    def _build_attr_header(local_list, src):
        import pwd, grp
        attrs = {}
        for attr in cfg.preserve_attrs_list:
            if attr == 'uname':
                try:
                    val = pwd.getpwuid(local_list[src]['uid']).pw_name
                except KeyError:
                    attr = "uid"
                    val = local_list[src].get('uid')
                    warning(u"%s: Owner username not known. Storing UID=%d instead." % (src, val))
            elif attr == 'gname':
                try:
                    val = grp.getgrgid(local_list[src].get('gid')).gr_name
                except KeyError:
                    attr = "gid"
                    val = local_list[src].get('gid')
                    warning(u"%s: Owner groupname not known. Storing GID=%d instead." % (src, val))
            elif attr == 'md5':
                try:
                    val = local_list.get_md5(src)
                except IOError:
                    val = None
            else:
                val = getattr(local_list[src]['sr'], 'st_' + attr)
            attrs[attr] = val

        if 'md5' in attrs and attrs['md5'] is None:
            del attrs['md5']

        result = ""
        for k in attrs: result += "%s:%s/" % (k, attrs[k])
        return { 'x-amz-meta-s3cmd-attrs' : result[:-1] }

    def _do_deletes(s3, remote_list):
        for key in remote_list:
            uri = S3Uri(remote_list[key]['object_uri_str'])
            s3.object_delete(uri)
            output(u"deleted: '%s'" % uri)

    def _single_process(local_list):
        for dest in destinations:
            ## Normalize URI to convert s3://bkt to s3://bkt/ (trailing slash)
            destination_base_uri = S3Uri(dest)
            if destination_base_uri.type != 's3':
                raise ParameterError("Destination must be S3Uri. Got: %s" % destination_base_uri)
            destination_base = str(destination_base_uri)
            _child(destination_base, local_list)
            return destination_base_uri

    def _parent():
        # Now that we've done all the disk I/O to look at the local file system and
        # calculate the md5 for each file, fork for each destination to upload to them separately
        # and in parallel
        child_pids = []

        for dest in destinations:
            ## Normalize URI to convert s3://bkt to s3://bkt/ (trailing slash)
            destination_base_uri = S3Uri(dest)
            if destination_base_uri.type != 's3':
                raise ParameterError("Destination must be S3Uri. Got: %s" % destination_base_uri)
            destination_base = str(destination_base_uri)
            child_pid = os.fork()
            if child_pid == 0:
                _child(destination_base, local_list)
                os._exit(0)
            else:
                child_pids.append(child_pid)

        while len(child_pids):
            (pid, status) = os.wait()
            child_pids.remove(pid)

        return

    def _child(destination_base, local_list):
        def _set_remote_uri(local_list, destination_base, single_file_local):
            if len(local_list) > 0:
                ## Populate 'remote_uri' only if we've got something to upload
                if not destination_base.endswith("/"):
                    if not single_file_local:
                        raise ParameterError("Destination S3 URI must end with '/' (ie must refer to a directory on the remote side).")
                    local_list[local_list.keys()[0]]['remote_uri'] = unicodise(destination_base)
                else:
                    for key in local_list:
                        local_list[key]['remote_uri'] = unicodise(destination_base + key)

        def _upload(local_list, seq, total, total_size):
            file_list = local_list.keys()
            file_list.sort()
            for file in file_list:
                seq += 1
                item = local_list[file]
                src = item['full_name']
                uri = S3Uri(item['remote_uri'])
                seq_label = "[%d of %d]" % (seq, total)
                extra_headers = copy(cfg.extra_headers)
                try:
                    if cfg.preserve_attrs:
                        attr_header = _build_attr_header(local_list, file)
                        debug(u"attr_header: %s" % attr_header)
                        extra_headers.update(attr_header)
                    response = s3.object_put(src, uri, extra_headers, extra_label = seq_label)
                except InvalidFileError, e:
                    warning(u"File can not be uploaded: %s" % e)
                    continue
                except S3UploadError, e:
                    error(u"%s: upload failed too many times. Skipping that file." % item['full_name_unicode'])
                    continue
                speed_fmt = formatSize(response["speed"], human_readable = True, floating_point = True)
                if not cfg.progress_meter:
                    output(u"File '%s' stored as '%s' (%d bytes in %0.1f seconds, %0.2f %sB/s) %s" %
                        (item['full_name_unicode'], uri, response["size"], response["elapsed"],
                        speed_fmt[0], speed_fmt[1], seq_label))
                total_size += response["size"]
                uploaded_objects_list.append(uri.object())
            return seq, total_size

        remote_list = fetch_remote_list(destination_base, recursive = True, require_attribs = True)

        local_count = len(local_list)
        remote_count = len(remote_list)

        info(u"Found %d local files, %d remote files" % (local_count, remote_count))

        local_list, exclude_list = filter_exclude_include(local_list)

        if single_file_local and len(local_list) == 1 and len(remote_list) == 1:
            ## Make remote_key same as local_key for comparison if we're dealing with only one file
            remote_list_entry = remote_list[remote_list.keys()[0]]
            # Flush remote_list, by the way
            remote_list = FileDict()
            remote_list[local_list.keys()[0]] =  remote_list_entry

        local_list, remote_list, update_list, copy_pairs = compare_filelists(local_list, remote_list, src_remote = False, dst_remote = True, delay_updates = cfg.delay_updates)

        local_count = len(local_list)
        update_count = len(update_list)
        copy_count = len(copy_pairs)
        remote_count = len(remote_list)

        info(u"Summary: %d local files to upload, %d files to remote copy, %d remote files to delete" % (local_count + update_count, copy_count, remote_count))

        _set_remote_uri(local_list, destination_base, single_file_local)
        _set_remote_uri(update_list, destination_base, single_file_local)

        if cfg.dry_run:
            for key in exclude_list:
                output(u"exclude: %s" % unicodise(key))
            for key in local_list:
                output(u"upload: %s -> %s" % (local_list[key]['full_name_unicode'], local_list[key]['remote_uri']))
            for key in update_list:
                output(u"upload: %s -> %s" % (update_list[key]['full_name_unicode'], update_list[key]['remote_uri']))
            for (src_obj, dst1, dst2) in copy_pairs:
                output(u"remote copy: %s -> %s" % (dst1, dst2))
            if cfg.delete_removed:
                for key in remote_list:
                    output(u"delete: %s" % remote_list[key]['object_uri_str'])

            warning(u"Exiting now because of --dry-run")
            return

        # if there are copy pairs, we can't do delete_before, on the chance
        # we need one of the to-be-deleted files as a copy source.
        if len(copy_pairs) > 0:
            cfg.delete_after = True

        if cfg.delete_removed and not cfg.delete_after:
            _do_deletes(s3, remote_list)

        total_size = 0
        total_elapsed = 0.0
        timestamp_start = time.time()
        n, total_size = _upload(local_list, 0, local_count, total_size)
        n, total_size = _upload(update_list, n, local_count, total_size)
        n_copies, saved_bytes = remote_copy(s3, copy_pairs, destination_base)
        if cfg.delete_removed and cfg.delete_after:
            _do_deletes(s3, remote_list)
        total_elapsed = time.time() - timestamp_start
        total_speed = total_elapsed and total_size/total_elapsed or 0.0
        speed_fmt = formatSize(total_speed, human_readable = True, floating_point = True)

        # Only print out the result if any work has been done or
        # if the user asked for verbose output
        outstr = "Done. Uploaded %d bytes in %0.1f seconds, %0.2f %sB/s.  Copied %d files saving %d bytes transfer." % (total_size, total_elapsed, speed_fmt[0], speed_fmt[1], n_copies, saved_bytes)
        if total_size + saved_bytes > 0:
            output(outstr)
        else:
            info(outstr)

        return

    def _invalidate_on_cf(destination_base_uri):
        cf = CloudFront(cfg)
        default_index_file = None
        if cfg.invalidate_default_index_on_cf or cfg.invalidate_default_index_root_on_cf:
            info_response = s3.website_info(destination_base_uri, cfg.bucket_location)
            if info_response:
              default_index_file = info_response['index_document']
              if len(default_index_file) < 1:
                  default_index_file = None

        result = cf.InvalidateObjects(destination_base_uri, uploaded_objects_list, default_index_file, cfg.invalidate_default_index_on_cf, cfg.invalidate_default_index_root_on_cf)
        if result['status'] == 201:
            output("Created invalidation request for %d paths" % len(uploaded_objects_list))
            output("Check progress with: s3cmd cfinvalinfo cf://%s/%s" % (result['dist_id'], result['request_id']))


    # main execution
    s3 = S3(cfg)
    uploaded_objects_list = []

    if cfg.encrypt:
        error(u"S3cmd 'sync' doesn't yet support GPG encryption, sorry.")
        error(u"Either use unconditional 's3cmd put --recursive'")
        error(u"or disable encryption with --no-encrypt parameter.")
        sys.exit(1)

    local_list, single_file_local = fetch_local_list(args[:-1], recursive = True)

    destinations = [args[-1]]
    if cfg.additional_destinations:
        destinations = destinations + cfg.additional_destinations

    if 'fork' not in os.__all__ or len(destinations) < 2:
        destination_base_uri = _single_process(local_list)
        if cfg.invalidate_on_cf:
            if len(uploaded_objects_list) == 0:
                info("Nothing to invalidate in CloudFront")
            else:
                _invalidate_on_cf(destination_base_uri)
    else:
        _parent()
        if cfg.invalidate_on_cf:
            error(u"You cannot use both --cf-invalidate and --add-destination.")

def cmd_sync(args):
    if (len(args) < 2):
        raise ParameterError("Too few parameters! Expected: %s" % commands['sync']['param'])

    if S3Uri(args[0]).type == "file" and S3Uri(args[-1]).type == "s3":
        return cmd_sync_local2remote(args)
    if S3Uri(args[0]).type == "s3" and S3Uri(args[-1]).type == "file":
        return cmd_sync_remote2local(args)
    if S3Uri(args[0]).type == "s3" and S3Uri(args[-1]).type == "s3":
        return cmd_sync_remote2remote(args)
    raise ParameterError("Invalid source/destination: '%s'" % "' '".join(args))

def cmd_setacl(args):
    s3 = S3(cfg)

    set_to_acl = cfg.acl_public and "Public" or "Private"

    if not cfg.recursive:
        old_args = args
        args = []
        for arg in old_args:
            uri = S3Uri(arg)
            if not uri.has_object():
                if cfg.acl_public != None:
                    info("Setting bucket-level ACL for %s to %s" % (uri.uri(), set_to_acl))
                else:
                    info("Setting bucket-level ACL for %s" % (uri.uri()))
                if not cfg.dry_run:
                    update_acl(s3, uri)
            else:
                args.append(arg)

    remote_list = fetch_remote_list(args)
    remote_list, exclude_list = filter_exclude_include(remote_list)

    remote_count = len(remote_list)

    info(u"Summary: %d remote files to update" % remote_count)

    if cfg.dry_run:
        for key in exclude_list:
            output(u"exclude: %s" % unicodise(key))
        for key in remote_list:
            output(u"setacl: %s" % remote_list[key]['object_uri_str'])

        warning(u"Exiting now because of --dry-run")
        return

    seq = 0
    for key in remote_list:
        seq += 1
        seq_label = "[%d of %d]" % (seq, remote_count)
        uri = S3Uri(remote_list[key]['object_uri_str'])
        update_acl(s3, uri, seq_label)

def cmd_setpolicy(args):
    s3 = S3(cfg)
    uri = S3Uri(args[1])
    policy_file = args[0]
    policy = open(policy_file, 'r').read()

    if cfg.dry_run: return

    response = s3.set_policy(uri, policy)

    #if retsponse['status'] == 200:
    debug(u"response - %s" % response['status'])
    if response['status'] == 204:
        output(u"%s: Policy updated" % uri)

def cmd_delpolicy(args):
    s3 = S3(cfg)
    uri = S3Uri(args[0])
    if cfg.dry_run: return

    response = s3.delete_policy(uri)

    #if retsponse['status'] == 200:
    debug(u"response - %s" % response['status'])
    output(u"%s: Policy deleted" % uri)


def cmd_accesslog(args):
    s3 = S3(cfg)
    bucket_uri = S3Uri(args.pop())
    if bucket_uri.object():
        raise ParameterError("Only bucket name is required for [accesslog] command")
    if cfg.log_target_prefix == False:
        accesslog, response = s3.set_accesslog(bucket_uri, enable = False)
    elif cfg.log_target_prefix:
        log_target_prefix_uri = S3Uri(cfg.log_target_prefix)
        if log_target_prefix_uri.type != "s3":
            raise ParameterError("--log-target-prefix must be a S3 URI")
        accesslog, response = s3.set_accesslog(bucket_uri, enable = True, log_target_prefix_uri = log_target_prefix_uri, acl_public = cfg.acl_public)
    else:   # cfg.log_target_prefix == None
        accesslog = s3.get_accesslog(bucket_uri)

    output(u"Access logging for: %s" % bucket_uri.uri())
    output(u"   Logging Enabled: %s" % accesslog.isLoggingEnabled())
    if accesslog.isLoggingEnabled():
        output(u"     Target prefix: %s" % accesslog.targetPrefix().uri())
        #output(u"   Public Access:   %s" % accesslog.isAclPublic())

def cmd_sign(args):
    string_to_sign = args.pop()
    debug("string-to-sign: %r" % string_to_sign)
    signature = Utils.sign_string(string_to_sign)
    output("Signature: %s" % signature)

def cmd_signurl(args):
    expiry = args.pop()
    url_to_sign = S3Uri(args.pop())
    if url_to_sign.type != 's3':
        raise ParameterError("Must be S3Uri. Got: %s" % url_to_sign)
    debug("url to sign: %r" % url_to_sign)
    signed_url = Utils.sign_url(url_to_sign, expiry)
    output(signed_url)

def cmd_fixbucket(args):
    def _unescape(text):
        ##
        # Removes HTML or XML character references and entities from a text string.
        #
        # @param text The HTML (or XML) source text.
        # @return The plain text, as a Unicode string, if necessary.
        #
        # From: http://effbot.org/zone/re-sub.htm#unescape-html
        def _unescape_fixup(m):
            text = m.group(0)
            if not htmlentitydefs.name2codepoint.has_key('apos'):
                htmlentitydefs.name2codepoint['apos'] = ord("'")
            if text[:2] == "&#":
                # character reference
                try:
                    if text[:3] == "&#x":
                        return unichr(int(text[3:-1], 16))
                    else:
                        return unichr(int(text[2:-1]))
                except ValueError:
                    pass
            else:
                # named entity
                try:
                    text = unichr(htmlentitydefs.name2codepoint[text[1:-1]])
                except KeyError:
                    pass
            return text # leave as is
            text = text.encode('ascii', 'xmlcharrefreplace')
        return re.sub("&#?\w+;", _unescape_fixup, text)

    cfg.urlencoding_mode = "fixbucket"
    s3 = S3(cfg)

    count = 0
    for arg in args:
        culprit = S3Uri(arg)
        if culprit.type != "s3":
            raise ParameterError("Expecting S3Uri instead of: %s" % arg)
        response = s3.bucket_list_noparse(culprit.bucket(), culprit.object(), recursive = True)
        r_xent = re.compile("&#x[\da-fA-F]+;")
        response['data'] = unicode(response['data'], 'UTF-8')
        keys = re.findall("<Key>(.*?)</Key>", response['data'], re.MULTILINE)
        debug("Keys: %r" % keys)
        for key in keys:
            if r_xent.search(key):
                info("Fixing: %s" % key)
                debug("Step 1: Transforming %s" % key)
                key_bin = _unescape(key)
                debug("Step 2:       ... to %s" % key_bin)
                key_new = replace_nonprintables(key_bin)
                debug("Step 3:  ... then to %s" % key_new)
                src = S3Uri("s3://%s/%s" % (culprit.bucket(), key_bin))
                dst = S3Uri("s3://%s/%s" % (culprit.bucket(), key_new))
                resp_move = s3.object_move(src, dst)
                if resp_move['status'] == 200:
                    output("File %r renamed to %s" % (key_bin, key_new))
                    count += 1
                else:
                    error("Something went wrong for: %r" % key)
                    error("Please report the problem to s3tools-bugs@lists.sourceforge.net")
    if count > 0:
        warning("Fixed %d files' names. Their ACL were reset to Private." % count)
        warning("Use 's3cmd setacl --acl-public s3://...' to make")
        warning("them publicly readable if required.")

def resolve_list(lst, args):
    retval = []
    for item in lst:
        retval.append(item % args)
    return retval

def gpg_command(command, passphrase = ""):
    debug("GPG command: " + " ".join(command))
    p = subprocess.Popen(command, stdin = subprocess.PIPE, stdout = subprocess.PIPE, stderr = subprocess.STDOUT)
    p_stdout, p_stderr = p.communicate(passphrase + "\n")
    debug("GPG output:")
    for line in p_stdout.split("\n"):
        debug("GPG: " + line)
    p_exitcode = p.wait()
    return p_exitcode

def gpg_encrypt(filename):
    tmp_filename = Utils.mktmpfile()
    args = {
        "gpg_command" : cfg.gpg_command,
        "passphrase_fd" : "0",
        "input_file" : filename,
        "output_file" : tmp_filename,
    }
    info(u"Encrypting file %(input_file)s to %(output_file)s..." % args)
    command = resolve_list(cfg.gpg_encrypt.split(" "), args)
    code = gpg_command(command, cfg.gpg_passphrase)
    return (code, tmp_filename, "gpg")

def gpg_decrypt(filename, gpgenc_header = "", in_place = True):
    tmp_filename = Utils.mktmpfile(filename)
    args = {
        "gpg_command" : cfg.gpg_command,
        "passphrase_fd" : "0",
        "input_file" : filename,
        "output_file" : tmp_filename,
    }
    info(u"Decrypting file %(input_file)s to %(output_file)s..." % args)
    command = resolve_list(cfg.gpg_decrypt.split(" "), args)
    code = gpg_command(command, cfg.gpg_passphrase)
    if code == 0 and in_place:
        debug(u"Renaming %s to %s" % (tmp_filename, filename))
        os.unlink(filename)
        os.rename(tmp_filename, filename)
        tmp_filename = filename
    return (code, tmp_filename)

def run_configure(config_file, args):
    cfg = Config()
    options = [
        ("access_key", "Access Key", "Access key and Secret key are your identifiers for Amazon S3"),
        ("secret_key", "Secret Key"),
        ("gpg_passphrase", "Encryption password", "Encryption password is used to protect your files from reading\nby unauthorized persons while in transfer to S3"),
        ("gpg_command", "Path to GPG program"),
        ("use_https", "Use HTTPS protocol", "When using secure HTTPS protocol all communication with Amazon S3\nservers is protected from 3rd party eavesdropping. This method is\nslower than plain HTTP and can't be used if you're behind a proxy"),
        ("proxy_host", "HTTP Proxy server name", "On some networks all internet access must go through a HTTP proxy.\nTry setting it here if you can't conect to S3 directly"),
        ("proxy_port", "HTTP Proxy server port"),
        ]
    ## Option-specfic defaults
    if getattr(cfg, "gpg_command") == "":
        setattr(cfg, "gpg_command", find_executable("gpg"))

    if getattr(cfg, "proxy_host") == "" and os.getenv("http_proxy"):
        re_match=re.match("(http://)?([^:]+):(\d+)", os.getenv("http_proxy"))
        if re_match:
            setattr(cfg, "proxy_host", re_match.groups()[1])
            setattr(cfg, "proxy_port", re_match.groups()[2])

    try:
        while 1:
            output(u"\nEnter new values or accept defaults in brackets with Enter.")
            output(u"Refer to user manual for detailed description of all options.")
            for option in options:
                prompt = option[1]
                ## Option-specific handling
                if option[0] == 'proxy_host' and getattr(cfg, 'use_https') == True:
                    setattr(cfg, option[0], "")
                    continue
                if option[0] == 'proxy_port' and getattr(cfg, 'proxy_host') == "":
                    setattr(cfg, option[0], 0)
                    continue

                try:
                    val = getattr(cfg, option[0])
                    if type(val) is bool:
                        val = val and "Yes" or "No"
                    if val not in (None, ""):
                        prompt += " [%s]" % val
                except AttributeError:
                    pass

                if len(option) >= 3:
                    output(u"\n%s" % option[2])

                val = raw_input(prompt + ": ")
                if val != "":
                    if type(getattr(cfg, option[0])) is bool:
                        # Turn 'Yes' into True, everything else into False
                        val = val.lower().startswith('y')
                    setattr(cfg, option[0], val)
            output(u"\nNew settings:")
            for option in options:
                output(u"  %s: %s" % (option[1], getattr(cfg, option[0])))
            val = raw_input("\nTest access with supplied credentials? [Y/n] ")
            if val.lower().startswith("y") or val == "":
                try:
                    # Default, we try to list 'all' buckets which requires
                    # ListAllMyBuckets permission
                    if len(args) == 0:
                        output(u"Please wait, attempting to list all buckets...")
                        S3(Config()).bucket_list("", "")
                    else:
                        # If user specified a bucket name directly, we check it and only it.
                        # Thus, access check can succeed even if user only has access to
                        # to a single bucket and not ListAllMyBuckets permission.
                        output(u"Please wait, attempting to list bucket: " + args[0])
                        uri = S3Uri(args[0])
                        if uri.type == "s3" and uri.has_bucket():
                            S3(Config()).bucket_list(uri.bucket(), "")
                        else:
                            raise Exception(u"Invalid bucket uri: " + args[0])

                    output(u"Success. Your access key and secret key worked fine :-)")

                    output(u"\nNow verifying that encryption works...")
                    if not getattr(cfg, "gpg_command") or not getattr(cfg, "gpg_passphrase"):
                        output(u"Not configured. Never mind.")
                    else:
                        if not getattr(cfg, "gpg_command"):
                            raise Exception("Path to GPG program not set")
                        if not os.path.isfile(getattr(cfg, "gpg_command")):
                            raise Exception("GPG program not found")
                        filename = Utils.mktmpfile()
                        f = open(filename, "w")
                        f.write(os.sys.copyright)
                        f.close()
                        ret_enc = gpg_encrypt(filename)
                        ret_dec = gpg_decrypt(ret_enc[1], ret_enc[2], False)
                        hash = [
                            Utils.hash_file_md5(filename),
                            Utils.hash_file_md5(ret_enc[1]),
                            Utils.hash_file_md5(ret_dec[1]),
                        ]
                        os.unlink(filename)
                        os.unlink(ret_enc[1])
                        os.unlink(ret_dec[1])
                        if hash[0] == hash[2] and hash[0] != hash[1]:
                            output ("Success. Encryption and decryption worked fine :-)")
                        else:
                            raise Exception("Encryption verification error.")

                except Exception, e:
                    error(u"Test failed: %s" % (e))
                    val = raw_input("\nRetry configuration? [Y/n] ")
                    if val.lower().startswith("y") or val == "":
                        continue


            val = raw_input("\nSave settings? [y/N] ")
            if val.lower().startswith("y"):
                break
            val = raw_input("Retry configuration? [Y/n] ")
            if val.lower().startswith("n"):
                raise EOFError()

        ## Overwrite existing config file, make it user-readable only
        old_mask = os.umask(0077)
        try:
            os.remove(config_file)
        except OSError, e:
            if e.errno != errno.ENOENT:
                raise
        f = open(config_file, "w")
        os.umask(old_mask)
        cfg.dump_config(f)
        f.close()
        output(u"Configuration saved to '%s'" % config_file)

    except (EOFError, KeyboardInterrupt):
        output(u"\nConfiguration aborted. Changes were NOT saved.")
        return

    except IOError, e:
        error(u"Writing config file failed: %s: %s" % (config_file, e.strerror))
        sys.exit(1)

def process_patterns_from_file(fname, patterns_list):
    try:
        fn = open(fname, "rt")
    except IOError, e:
        error(e)
        sys.exit(1)
    for pattern in fn:
        pattern = pattern.strip()
        if re.match("^#", pattern) or re.match("^\s*$", pattern):
            continue
        debug(u"%s: adding rule: %s" % (fname, pattern))
        patterns_list.append(pattern)

    return patterns_list

def process_patterns(patterns_list, patterns_from, is_glob, option_txt = ""):
    """
    process_patterns(patterns, patterns_from, is_glob, option_txt = "")
    Process --exclude / --include GLOB and REGEXP patterns.
    'option_txt' is 'exclude' / 'include' / 'rexclude' / 'rinclude'
    Returns: patterns_compiled, patterns_text
    """

    patterns_compiled = []
    patterns_textual = {}

    if patterns_list is None:
        patterns_list = []

    if patterns_from:
        ## Append patterns from glob_from
        for fname in patterns_from:
            debug(u"processing --%s-from %s" % (option_txt, fname))
            patterns_list = process_patterns_from_file(fname, patterns_list)

    for pattern in patterns_list:
        debug(u"processing %s rule: %s" % (option_txt, patterns_list))
        if is_glob:
            pattern = glob.fnmatch.translate(pattern)
        r = re.compile(pattern)
        patterns_compiled.append(r)
        patterns_textual[r] = pattern

    return patterns_compiled, patterns_textual

def get_commands_list():
    return [
    {"cmd":"mb", "label":"Make bucket", "param":"s3://BUCKET", "func":cmd_bucket_create, "argc":1},
    {"cmd":"rb", "label":"Remove bucket", "param":"s3://BUCKET", "func":cmd_bucket_delete, "argc":1},
    {"cmd":"ls", "label":"List objects or buckets", "param":"[s3://BUCKET[/PREFIX]]", "func":cmd_ls, "argc":0},
    {"cmd":"la", "label":"List all object in all buckets", "param":"", "func":cmd_buckets_list_all_all, "argc":0},
    {"cmd":"put", "label":"Put file into bucket", "param":"FILE [FILE...] s3://BUCKET[/PREFIX]", "func":cmd_object_put, "argc":2},
    {"cmd":"get", "label":"Get file from bucket", "param":"s3://BUCKET/OBJECT LOCAL_FILE", "func":cmd_object_get, "argc":1},
    {"cmd":"del", "label":"Delete file from bucket", "param":"s3://BUCKET/OBJECT", "func":cmd_object_del, "argc":1},
    #{"cmd":"mkdir", "label":"Make a virtual S3 directory", "param":"s3://BUCKET/path/to/dir", "func":cmd_mkdir, "argc":1},
    {"cmd":"sync", "label":"Synchronize a directory tree to S3", "param":"LOCAL_DIR s3://BUCKET[/PREFIX] or s3://BUCKET[/PREFIX] LOCAL_DIR", "func":cmd_sync, "argc":2},
    {"cmd":"du", "label":"Disk usage by buckets", "param":"[s3://BUCKET[/PREFIX]]", "func":cmd_du, "argc":0},
    {"cmd":"info", "label":"Get various information about Buckets or Files", "param":"s3://BUCKET[/OBJECT]", "func":cmd_info, "argc":1},
    {"cmd":"cp", "label":"Copy object", "param":"s3://BUCKET1/OBJECT1 s3://BUCKET2[/OBJECT2]", "func":cmd_cp, "argc":2},
    {"cmd":"mv", "label":"Move object", "param":"s3://BUCKET1/OBJECT1 s3://BUCKET2[/OBJECT2]", "func":cmd_mv, "argc":2},
    {"cmd":"setacl", "label":"Modify Access control list for Bucket or Files", "param":"s3://BUCKET[/OBJECT]", "func":cmd_setacl, "argc":1},

    {"cmd":"setpolicy", "label":"Modify Bucket Policy", "param":"FILE s3://BUCKET", "func":cmd_setpolicy, "argc":2},
    {"cmd":"delpolicy", "label":"Delete Bucket Policy", "param":"s3://BUCKET", "func":cmd_delpolicy, "argc":1},

    {"cmd":"accesslog", "label":"Enable/disable bucket access logging", "param":"s3://BUCKET", "func":cmd_accesslog, "argc":1},
    {"cmd":"sign", "label":"Sign arbitrary string using the secret key", "param":"STRING-TO-SIGN", "func":cmd_sign, "argc":1},
    {"cmd":"signurl", "label":"Sign an S3 URL to provide limited public access with expiry", "param":"s3://BUCKET/OBJECT expiry_epoch", "func":cmd_signurl, "argc":2},
    {"cmd":"fixbucket", "label":"Fix invalid file names in a bucket", "param":"s3://BUCKET[/PREFIX]", "func":cmd_fixbucket, "argc":1},

    ## Website commands
    {"cmd":"ws-create", "label":"Create Website from bucket", "param":"s3://BUCKET", "func":cmd_website_create, "argc":1},
    {"cmd":"ws-delete", "label":"Delete Website", "param":"s3://BUCKET", "func":cmd_website_delete, "argc":1},
    {"cmd":"ws-info", "label":"Info about Website", "param":"s3://BUCKET", "func":cmd_website_info, "argc":1},

    ## CloudFront commands
    {"cmd":"cflist", "label":"List CloudFront distribution points", "param":"", "func":CfCmd.info, "argc":0},
    {"cmd":"cfinfo", "label":"Display CloudFront distribution point parameters", "param":"[cf://DIST_ID]", "func":CfCmd.info, "argc":0},
    {"cmd":"cfcreate", "label":"Create CloudFront distribution point", "param":"s3://BUCKET", "func":CfCmd.create, "argc":1},
    {"cmd":"cfdelete", "label":"Delete CloudFront distribution point", "param":"cf://DIST_ID", "func":CfCmd.delete, "argc":1},
    {"cmd":"cfmodify", "label":"Change CloudFront distribution point parameters", "param":"cf://DIST_ID", "func":CfCmd.modify, "argc":1},
    #{"cmd":"cfinval", "label":"Invalidate CloudFront objects", "param":"s3://BUCKET/OBJECT [s3://BUCKET/OBJECT ...]", "func":CfCmd.invalidate, "argc":1},
    {"cmd":"cfinvalinfo", "label":"Display CloudFront invalidation request(s) status", "param":"cf://DIST_ID[/INVAL_ID]", "func":CfCmd.invalinfo, "argc":1},
    ]

def format_commands(progname, commands_list):
    help = "Commands:\n"
    for cmd in commands_list:
        help += "  %s\n      %s %s %s\n" % (cmd["label"], progname, cmd["cmd"], cmd["param"])
    return help


def update_acl(s3, uri, seq_label=""):
    something_changed = False
    acl = s3.get_acl(uri)
    debug(u"acl: %s - %r" % (uri, acl.grantees))
    if cfg.acl_public == True:
        if acl.isAnonRead():
            info(u"%s: already Public, skipping %s" % (uri, seq_label))
        else:
            acl.grantAnonRead()
            something_changed = True
    elif cfg.acl_public == False:  # we explicitely check for False, because it could be None
        if not acl.isAnonRead():
            info(u"%s: already Private, skipping %s" % (uri, seq_label))
        else:
            acl.revokeAnonRead()
            something_changed = True

    # update acl with arguments
    # grant first and revoke later, because revoke has priority
    if cfg.acl_grants:
        something_changed = True
        for grant in cfg.acl_grants:
            acl.grant(**grant)

    if cfg.acl_revokes:
        something_changed = True
        for revoke in cfg.acl_revokes:
            acl.revoke(**revoke)

    if not something_changed:
        return

    retsponse = s3.set_acl(uri, acl)
    if retsponse['status'] == 200:
        if cfg.acl_public in (True, False):
            set_to_acl = cfg.acl_public and "Public" or "Private"
            output(u"%s: ACL set to %s  %s" % (uri, set_to_acl, seq_label))
        else:
            output(u"%s: ACL updated" % uri)

class OptionMimeType(Option):
    def check_mimetype(option, opt, value):
        if re.compile("^[a-z0-9]+/[a-z0-9+\.-]+(;.*)?$", re.IGNORECASE).match(value):
            return value
        raise OptionValueError("option %s: invalid MIME-Type format: %r" % (opt, value))

class OptionS3ACL(Option):
    def check_s3acl(option, opt, value):
        permissions = ('read', 'write', 'read_acp', 'write_acp', 'full_control', 'all')
        try:
            permission, grantee = re.compile("^(\w+):(.+)$", re.IGNORECASE).match(value).groups()
            if not permission or not grantee:
                raise
            if permission in permissions:
                return { 'name' : grantee, 'permission' : permission.upper() }
            else:
                raise OptionValueError("option %s: invalid S3 ACL permission: %s (valid values: %s)" %
                    (opt, permission, ", ".join(permissions)))
        except:
            raise OptionValueError("option %s: invalid S3 ACL format: %r" % (opt, value))

class OptionAll(OptionMimeType, OptionS3ACL):
    TYPE_CHECKER = copy(Option.TYPE_CHECKER)
    TYPE_CHECKER["mimetype"] = OptionMimeType.check_mimetype
    TYPE_CHECKER["s3acl"] = OptionS3ACL.check_s3acl
    TYPES = Option.TYPES + ("mimetype", "s3acl")

class MyHelpFormatter(IndentedHelpFormatter):
    def format_epilog(self, epilog):
        if epilog:
            return "\n" + epilog + "\n"
        else:
            return ""

def main():
    global cfg

    commands_list = get_commands_list()
    commands = {}

    ## Populate "commands" from "commands_list"
    for cmd in commands_list:
        if cmd.has_key("cmd"):
            commands[cmd["cmd"]] = cmd

    default_verbosity = Config().verbosity
    optparser = OptionParser(option_class=OptionAll, formatter=MyHelpFormatter())
    #optparser.disable_interspersed_args()

    config_file = None
    if os.getenv("HOME"):
        config_file = os.path.join(os.getenv("HOME"), ".s3cfg")
    elif os.name == "nt" and os.getenv("USERPROFILE"):
        config_file = os.path.join(os.getenv("USERPROFILE").decode('mbcs'), "Application Data", "s3cmd.ini")

    preferred_encoding = locale.getpreferredencoding() or "UTF-8"

    optparser.set_defaults(encoding = preferred_encoding)
    optparser.set_defaults(config = config_file)
    optparser.set_defaults(verbosity = default_verbosity)

    optparser.add_option(      "--configure", dest="run_configure", action="store_true", help="Invoke interactive (re)configuration tool. Optionally use as '--configure s3://come-bucket' to test access to a specific bucket instead of attempting to list them all.")
    optparser.add_option("-c", "--config", dest="config", metavar="FILE", help="Config file name. Defaults to %default")
    optparser.add_option(      "--dump-config", dest="dump_config", action="store_true", help="Dump current configuration after parsing config files and command line options and exit.")
    optparser.add_option(      "--access_key", dest="access_key", help="AWS Access Key")
    optparser.add_option(      "--secret_key", dest="secret_key", help="AWS Secret Key")

    optparser.add_option("-n", "--dry-run", dest="dry_run", action="store_true", help="Only show what should be uploaded or downloaded but don't actually do it. May still perform S3 requests to get bucket listings and other information though (only for file transfer commands)")

    optparser.add_option("-e", "--encrypt", dest="encrypt", action="store_true", help="Encrypt files before uploading to S3.")
    optparser.add_option(      "--no-encrypt", dest="encrypt", action="store_false", help="Don't encrypt files.")
    optparser.add_option("-f", "--force", dest="force", action="store_true", help="Force overwrite and other dangerous operations.")
    optparser.add_option(      "--continue", dest="get_continue", action="store_true", help="Continue getting a partially downloaded file (only for [get] command).")
    optparser.add_option(      "--skip-existing", dest="skip_existing", action="store_true", help="Skip over files that exist at the destination (only for [get] and [sync] commands).")
    optparser.add_option("-r", "--recursive", dest="recursive", action="store_true", help="Recursive upload, download or removal.")
    optparser.add_option(      "--check-md5", dest="check_md5", action="store_true", help="Check MD5 sums when comparing files for [sync]. (default)")
    optparser.add_option(      "--no-check-md5", dest="check_md5", action="store_false", help="Do not check MD5 sums when comparing files for [sync]. Only size will be compared. May significantly speed up transfer but may also miss some changed files.")
    optparser.add_option("-P", "--acl-public", dest="acl_public", action="store_true", help="Store objects with ACL allowing read for anyone.")
    optparser.add_option(      "--acl-private", dest="acl_public", action="store_false", help="Store objects with default ACL allowing access for you only.")
    optparser.add_option(      "--acl-grant", dest="acl_grants", type="s3acl", action="append", metavar="PERMISSION:EMAIL or USER_CANONICAL_ID", help="Grant stated permission to a given amazon user. Permission is one of: read, write, read_acp, write_acp, full_control, all")
    optparser.add_option(      "--acl-revoke", dest="acl_revokes", type="s3acl", action="append", metavar="PERMISSION:USER_CANONICAL_ID", help="Revoke stated permission for a given amazon user. Permission is one of: read, write, read_acp, wr     ite_acp, full_control, all")

    optparser.add_option(      "--delete-removed", dest="delete_removed", action="store_true", help="Delete remote objects with no corresponding local file [sync]")
    optparser.add_option(      "--no-delete-removed", dest="delete_removed", action="store_false", help="Don't delete remote objects.")
    optparser.add_option(      "--delete-after", dest="delete_after", action="store_true", help="Perform deletes after new uploads [sync]")
    optparser.add_option(      "--delay-updates", dest="delay_updates", action="store_true", help="Put all updated files into place at end [sync]")
    optparser.add_option(      "--add-destination", dest="additional_destinations", action="append", help="Additional destination for parallel uploads, in addition to last arg.  May be repeated.")
    optparser.add_option(      "--delete-after-fetch", dest="delete_after_fetch", action="store_true", help="Delete remote objects after fetching to local file (only for [get] and [sync] commands).")
    optparser.add_option("-p", "--preserve", dest="preserve_attrs", action="store_true", help="Preserve filesystem attributes (mode, ownership, timestamps). Default for [sync] command.")
    optparser.add_option(      "--no-preserve", dest="preserve_attrs", action="store_false", help="Don't store FS attributes")
    optparser.add_option(      "--exclude", dest="exclude", action="append", metavar="GLOB", help="Filenames and paths matching GLOB will be excluded from sync")
    optparser.add_option(      "--exclude-from", dest="exclude_from", action="append", metavar="FILE", help="Read --exclude GLOBs from FILE")
    optparser.add_option(      "--rexclude", dest="rexclude", action="append", metavar="REGEXP", help="Filenames and paths matching REGEXP (regular expression) will be excluded from sync")
    optparser.add_option(      "--rexclude-from", dest="rexclude_from", action="append", metavar="FILE", help="Read --rexclude REGEXPs from FILE")
    optparser.add_option(      "--include", dest="include", action="append", metavar="GLOB", help="Filenames and paths matching GLOB will be included even if previously excluded by one of --(r)exclude(-from) patterns")
    optparser.add_option(      "--include-from", dest="include_from", action="append", metavar="FILE", help="Read --include GLOBs from FILE")
    optparser.add_option(      "--rinclude", dest="rinclude", action="append", metavar="REGEXP", help="Same as --include but uses REGEXP (regular expression) instead of GLOB")
    optparser.add_option(      "--rinclude-from", dest="rinclude_from", action="append", metavar="FILE", help="Read --rinclude REGEXPs from FILE")

    optparser.add_option(      "--bucket-location", dest="bucket_location", help="Datacentre to create bucket in. As of now the datacenters are: US (default), EU, ap-northeast-1, ap-southeast-1, sa-east-1, us-west-1 and us-west-2")
    optparser.add_option(      "--reduced-redundancy", "--rr", dest="reduced_redundancy", action="store_true", help="Store object with 'Reduced redundancy'. Lower per-GB price. [put, cp, mv]")

    optparser.add_option(      "--access-logging-target-prefix", dest="log_target_prefix", help="Target prefix for access logs (S3 URI) (for [cfmodify] and [accesslog] commands)")
    optparser.add_option(      "--no-access-logging", dest="log_target_prefix", action="store_false", help="Disable access logging (for [cfmodify] and [accesslog] commands)")

    optparser.add_option(      "--default-mime-type", dest="default_mime_type", action="store_true", help="Default MIME-type for stored objects. Application default is binary/octet-stream.")
    optparser.add_option("-M", "--guess-mime-type", dest="guess_mime_type", action="store_true", help="Guess MIME-type of files by their extension or mime magic. Fall back to default MIME-Type as specified by --default-mime-type option")
    optparser.add_option(      "--no-guess-mime-type", dest="guess_mime_type", action="store_false", help="Don't guess MIME-type and use the default type instead.")
    optparser.add_option("-m", "--mime-type", dest="mime_type", type="mimetype", metavar="MIME/TYPE", help="Force MIME-type. Override both --default-mime-type and --guess-mime-type.")

    optparser.add_option(      "--add-header", dest="add_header", action="append", metavar="NAME:VALUE", help="Add a given HTTP header to the upload request. Can be used multiple times. For instance set 'Expires' or 'Cache-Control' headers (or both) using this options if you like.")

    optparser.add_option(      "--encoding", dest="encoding", metavar="ENCODING", help="Override autodetected terminal and filesystem encoding (character set). Autodetected: %s" % preferred_encoding)
    optparser.add_option(      "--add-encoding-exts", dest="add_encoding_exts", metavar="EXTENSIONs", help="Add encoding to these comma delimited extensions i.e. (css,js,html) when uploading to S3 )")
    optparser.add_option(      "--verbatim", dest="urlencoding_mode", action="store_const", const="verbatim", help="Use the S3 name as given on the command line. No pre-processing, encoding, etc. Use with caution!")

    optparser.add_option(      "--disable-multipart", dest="enable_multipart", action="store_false", help="Disable multipart upload on files bigger than --multipart-chunk-size-mb")
    optparser.add_option(      "--multipart-chunk-size-mb", dest="multipart_chunk_size_mb", type="int", action="store", metavar="SIZE", help="Size of each chunk of a multipart upload. Files bigger than SIZE are automatically uploaded as multithreaded-multipart, smaller files are uploaded using the traditional method. SIZE is in Mega-Bytes, default chunk size is %defaultMB, minimum allowed chunk size is 5MB, maximum is 5GB.")

    optparser.add_option(      "--list-md5", dest="list_md5", action="store_true", help="Include MD5 sums in bucket listings (only for 'ls' command).")
    optparser.add_option("-H", "--human-readable-sizes", dest="human_readable_sizes", action="store_true", help="Print sizes in human readable form (eg 1kB instead of 1234).")

    optparser.add_option(      "--ws-index", dest="website_index", action="store", help="Name of error-document (only for [ws-create] command)")
    optparser.add_option(      "--ws-error", dest="website_error", action="store", help="Name of index-document (only for [ws-create] command)")

    optparser.add_option(      "--progress", dest="progress_meter", action="store_true", help="Display progress meter (default on TTY).")
    optparser.add_option(      "--no-progress", dest="progress_meter", action="store_false", help="Don't display progress meter (default on non-TTY).")
    optparser.add_option(      "--enable", dest="enable", action="store_true", help="Enable given CloudFront distribution (only for [cfmodify] command)")
    optparser.add_option(      "--disable", dest="enable", action="store_false", help="Enable given CloudFront distribution (only for [cfmodify] command)")
    optparser.add_option(      "--cf-invalidate", dest="invalidate_on_cf", action="store_true", help="Invalidate the uploaded filed in CloudFront. Also see [cfinval] command.")
    # joseprio: adding options to invalidate the default index and the default
    # index root
    optparser.add_option(      "--cf-invalidate-default-index", dest="invalidate_default_index_on_cf", action="store_true", help="When using Custom Origin and S3 static website, invalidate the default index file.")
    optparser.add_option(      "--cf-no-invalidate-default-index-root", dest="invalidate_default_index_root_on_cf", action="store_false", help="When using Custom Origin and S3 static website, don't invalidate the path to the default index file.")
    optparser.add_option(      "--cf-add-cname", dest="cf_cnames_add", action="append", metavar="CNAME", help="Add given CNAME to a CloudFront distribution (only for [cfcreate] and [cfmodify] commands)")
    optparser.add_option(      "--cf-remove-cname", dest="cf_cnames_remove", action="append", metavar="CNAME", help="Remove given CNAME from a CloudFront distribution (only for [cfmodify] command)")
    optparser.add_option(      "--cf-comment", dest="cf_comment", action="store", metavar="COMMENT", help="Set COMMENT for a given CloudFront distribution (only for [cfcreate] and [cfmodify] commands)")
    optparser.add_option(      "--cf-default-root-object", dest="cf_default_root_object", action="store", metavar="DEFAULT_ROOT_OBJECT", help="Set the default root object to return when no object is specified in the URL. Use a relative path, i.e. default/index.html instead of /default/index.html or s3://bucket/default/index.html (only for [cfcreate] and [cfmodify] commands)")
    optparser.add_option("-v", "--verbose", dest="verbosity", action="store_const", const=logging.INFO, help="Enable verbose output.")
    optparser.add_option("-d", "--debug", dest="verbosity", action="store_const", const=logging.DEBUG, help="Enable debug output.")
    optparser.add_option(      "--version", dest="show_version", action="store_true", help="Show s3cmd version (%s) and exit." % (PkgInfo.version))
    optparser.add_option("-F", "--follow-symlinks", dest="follow_symlinks", action="store_true", default=False, help="Follow symbolic links as if they are regular files")
    optparser.add_option(      "--cache-file", dest="cache_file", action="store", default="",  metavar="FILE", help="Cache FILE containing local source MD5 values")
    optparser.add_option("-q", "--quiet", dest="quiet", action="store_true", default=False, help="Silence output on stdout")

    optparser.set_usage(optparser.usage + " COMMAND [parameters]")
    optparser.set_description('S3cmd is a tool for managing objects in '+
        'Amazon S3 storage. It allows for making and removing '+
        '"buckets" and uploading, downloading and removing '+
        '"objects" from these buckets.')
    optparser.epilog = format_commands(optparser.get_prog_name(), commands_list)
    optparser.epilog += ("\nFor more informations see the progect homepage:\n%s\n" % PkgInfo.url)
    optparser.epilog += ("\nConsider a donation if you have found s3cmd useful:\n%s/donate\n" % PkgInfo.url)

    (options, args) = optparser.parse_args()

    ## Some mucking with logging levels to enable
    ## debugging/verbose output for config file parser on request
    logging.basicConfig(level=options.verbosity,
                        format='%(levelname)s: %(message)s',
                        stream = sys.stderr)

    if options.show_version:
        output(u"s3cmd version %s" % PkgInfo.version)
        sys.exit(0)

    if options.quiet:
        try:
            f = open("/dev/null", "w")
            sys.stdout.close()
            sys.stdout = f
        except IOError:
            warning(u"Unable to open /dev/null: --quiet disabled.")

    ## Now finally parse the config file
    if not options.config:
        error(u"Can't find a config file. Please use --config option.")
        sys.exit(1)

    try:
        cfg = Config(options.config)
    except IOError, e:
        if options.run_configure:
            cfg = Config()
        else:
            error(u"%s: %s"  % (options.config, e.strerror))
            error(u"Configuration file not available.")
            error(u"Consider using --configure parameter to create one.")
            sys.exit(1)

    ## And again some logging level adjustments
    ## according to configfile and command line parameters
    if options.verbosity != default_verbosity:
        cfg.verbosity = options.verbosity
    logging.root.setLevel(cfg.verbosity)

    ## Default to --progress on TTY devices, --no-progress elsewhere
    ## Can be overriden by actual --(no-)progress parameter
    cfg.update_option('progress_meter', sys.stdout.isatty())

    ## Unsupported features on Win32 platform
    if os.name == "nt":
        if cfg.preserve_attrs:
            error(u"Option --preserve is not yet supported on MS Windows platform. Assuming --no-preserve.")
            cfg.preserve_attrs = False
        if cfg.progress_meter:
            error(u"Option --progress is not yet supported on MS Windows platform. Assuming --no-progress.")
            cfg.progress_meter = False

    ## Pre-process --add-header's and put them to Config.extra_headers SortedDict()
    if options.add_header:
        for hdr in options.add_header:
            try:
                key, val = hdr.split(":", 1)
            except ValueError:
                raise ParameterError("Invalid header format: %s" % hdr)
            key_inval = re.sub("[a-zA-Z0-9-.]", "", key)
            if key_inval:
                key_inval = key_inval.replace(" ", "<space>")
                key_inval = key_inval.replace("\t", "<tab>")
                raise ParameterError("Invalid character(s) in header name '%s': \"%s\"" % (key, key_inval))
            debug(u"Updating Config.Config extra_headers[%s] -> %s" % (key.strip(), val.strip()))
            cfg.extra_headers[key.strip()] = val.strip()

    ## --acl-grant/--acl-revoke arguments are pre-parsed by OptionS3ACL()
    if options.acl_grants:
        for grant in options.acl_grants:
            cfg.acl_grants.append(grant)

    if options.acl_revokes:
        for grant in options.acl_revokes:
            cfg.acl_revokes.append(grant)

    ## Process --(no-)check-md5
    if options.check_md5 == False:
        try:
            cfg.sync_checks.remove("md5")
        except Exception:
            pass
    if options.check_md5 == True and cfg.sync_checks.count("md5") == 0:
        cfg.sync_checks.append("md5")

    ## Update Config with other parameters
    for option in cfg.option_list():
        try:
            if getattr(options, option) != None:
                debug(u"Updating Config.Config %s -> %s" % (option, getattr(options, option)))
                cfg.update_option(option, getattr(options, option))
        except AttributeError:
            ## Some Config() options are not settable from command line
            pass

    ## Special handling for tri-state options (True, False, None)
    cfg.update_option("enable", options.enable)
    cfg.update_option("acl_public", options.acl_public)

    ## Check multipart chunk constraints
    if cfg.multipart_chunk_size_mb < MultiPartUpload.MIN_CHUNK_SIZE_MB:
        raise ParameterError("Chunk size %d MB is too small, must be >= %d MB. Please adjust --multipart-chunk-size-mb" % (cfg.multipart_chunk_size_mb, MultiPartUpload.MIN_CHUNK_SIZE_MB))
    if cfg.multipart_chunk_size_mb > MultiPartUpload.MAX_CHUNK_SIZE_MB:
        raise ParameterError("Chunk size %d MB is too large, must be <= %d MB. Please adjust --multipart-chunk-size-mb" % (cfg.multipart_chunk_size_mb, MultiPartUpload.MAX_CHUNK_SIZE_MB))

    ## CloudFront's cf_enable and Config's enable share the same --enable switch
    options.cf_enable = options.enable

    ## CloudFront's cf_logging and Config's log_target_prefix share the same --log-target-prefix switch
    options.cf_logging = options.log_target_prefix

    ## Update CloudFront options if some were set
    for option in CfCmd.options.option_list():
        try:
            if getattr(options, option) != None:
                debug(u"Updating CloudFront.Cmd %s -> %s" % (option, getattr(options, option)))
                CfCmd.options.update_option(option, getattr(options, option))
        except AttributeError:
            ## Some CloudFront.Cmd.Options() options are not settable from command line
            pass

    if options.additional_destinations:
        cfg.additional_destinations = options.additional_destinations

    ## Set output and filesystem encoding for printing out filenames.
    sys.stdout = codecs.getwriter(cfg.encoding)(sys.stdout, "replace")
    sys.stderr = codecs.getwriter(cfg.encoding)(sys.stderr, "replace")

    ## Process --exclude and --exclude-from
    patterns_list, patterns_textual = process_patterns(options.exclude, options.exclude_from, is_glob = True, option_txt = "exclude")
    cfg.exclude.extend(patterns_list)
    cfg.debug_exclude.update(patterns_textual)

    ## Process --rexclude and --rexclude-from
    patterns_list, patterns_textual = process_patterns(options.rexclude, options.rexclude_from, is_glob = False, option_txt = "rexclude")
    cfg.exclude.extend(patterns_list)
    cfg.debug_exclude.update(patterns_textual)

    ## Process --include and --include-from
    patterns_list, patterns_textual = process_patterns(options.include, options.include_from, is_glob = True, option_txt = "include")
    cfg.include.extend(patterns_list)
    cfg.debug_include.update(patterns_textual)

    ## Process --rinclude and --rinclude-from
    patterns_list, patterns_textual = process_patterns(options.rinclude, options.rinclude_from, is_glob = False, option_txt = "rinclude")
    cfg.include.extend(patterns_list)
    cfg.debug_include.update(patterns_textual)

    ## Set socket read()/write() timeout
    socket.setdefaulttimeout(cfg.socket_timeout)

    if cfg.encrypt and cfg.gpg_passphrase == "":
        error(u"Encryption requested but no passphrase set in config file.")
        error(u"Please re-run 's3cmd --configure' and supply it.")
        sys.exit(1)

    if options.dump_config:
        cfg.dump_config(sys.stdout)
        sys.exit(0)

    if options.run_configure:
        # 'args' may contain the test-bucket URI
        run_configure(options.config, args)
        sys.exit(0)

    if len(args) < 1:
        error(u"Missing command. Please run with --help for more information.")
        #sys.exit(1)

    ## Unicodise all remaining arguments:
    args = [unicodise(arg) for arg in args]

    command = args.pop(0)
    try:
        debug(u"Command: %s" % commands[command]["cmd"])
        ## We must do this lookup in extra step to
        ## avoid catching all KeyError exceptions
        ## from inner functions.
        cmd_func = commands[command]["func"]
    except KeyError, e:
        error(u"Invalid command: %s" % e)
        sys.exit(1)

    if len(args) < commands[command]["argc"]:
        error(u"Not enough parameters for command '%s'" % command)
        sys.exit(1)

    try:
        cmd_func(args)
    except S3Error, e:
        error(u"S3 error: %s" % e)
        sys.exit(1)

def report_exception(e):
        sys.stderr.write("""
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    An unexpected error has occurred.
  Please report the following lines to:
   s3tools-bugs@lists.sourceforge.net
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

""")
        tb = traceback.format_exc(sys.exc_info())
        e_class = str(e.__class__)
        e_class = e_class[e_class.rfind(".")+1 : -2]
        sys.stderr.write(u"Problem: %s: %s\n" % (e_class, e))
        try:
            sys.stderr.write("S3cmd:   %s\n" % PkgInfo.version)
        except NameError:
            sys.stderr.write("S3cmd:   unknown version. Module import problem?\n")
        sys.stderr.write("\n")
        sys.stderr.write(unicode(tb, errors="replace"))

        if type(e) == ImportError:
            sys.stderr.write("\n")
            sys.stderr.write("Your sys.path contains these entries:\n")
            for path in sys.path:
                sys.stderr.write(u"\t%s\n" % path)
            sys.stderr.write("Now the question is where have the s3cmd modules been installed?\n")

        sys.stderr.write("""
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    An unexpected error has occurred.
    Please report the above lines to:
   s3tools-bugs@lists.sourceforge.net
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
""")

if __name__ == '__main__':
    try:
        ## Our modules
        ## Keep them in try/except block to
        ## detect any syntax errors in there
        from S3.Exceptions import *
        from S3 import PkgInfo
        from S3.S3 import S3
        from S3.Config import Config
        from S3.SortedDict import SortedDict
        from S3.FileDict import FileDict
        from S3.S3Uri import S3Uri
        from S3 import Utils
        from S3.Utils import *
        from S3.Progress import Progress
        from S3.CloudFront import Cmd as CfCmd
        from S3.CloudFront import CloudFront
        from S3.FileLists import *
        from S3.MultiPart import MultiPartUpload

        main()
        sys.exit(0)

    except ImportError, e:
        report_exception(e)
        sys.exit(1)

    except ParameterError, e:
        error(u"Parameter problem: %s" % e)
        #sys.exit(1)

    except SystemExit, e:
        sys.exit(e.code)

    except KeyboardInterrupt:
        sys.stderr.write("See ya!\n")
        sys.exit(1)

    except Exception, e:
        report_exception(e)
        #sys.exit(1)



cmd_ls("ls")


from flask import Flask
from flask import Response, render_template, request, redirect, url_for, send_from_directory

from flask import stream_with_context
app = Flask(__name__)
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/listall')
def getAllBuckets():
        print "I am in"
	args = []
	args.append("s3://sat-hadoop")
	print "I am here"
	return str(cmd_ls(args)) 
	#print req
        #return Response(stream_with_context(req.iter_content()),content_type = req.headers['content-type'])

@app.route('/getobject')
def getObject():
	print "getting object"
	objectname = request.args.get('objectname')
        print objectname
        args = []
        args.append('s3://sat-hadoop/'+str(objectname))
	args.append('.')
	req = cmd_object_get(args)
	print "Printing response " + str(req)
	#return req['data']
	http_response = req["data"]
	print http_response
	def generate():
		chunks = "saiasa"
		while (chunks):
			chunks = http_response.read(2048)
			yield chunks
	#return "downloading"
	#return Response(stream_with_context(generate()),mimetype="text/plain",headers={"Content-Disposition":"attachment;filename=test.txt"})
	return Response(stream_with_context(generate()),headers ={'Connection': 'keep-alive',"Content-Disposition":"attachment;filename="+objectname})
@app.route('/streamobject')
def streamObject():
        print "getting object"
	objectname = request.args.get('objectname') 
	print objectname
        args = []
        args.append('s3://sat-hadoop/'+str(objectname))
        args.append('.')
        req = cmd_object_get(args)
        print "Printing response " + str(req)
        #return req['data']
        http_response = req["data"]
        print http_response
        def generate():
		#yield http_response.read()
                chunks = "saiasa"
                while (chunks):
                        chunks = http_response.read(2047)
                        yield chunks
		#	time.sleep(1)
        #return "downloading"
        return Response(stream_with_context(generate()),headers ={'Transfer-Encoding':'chunked'})



@app.route('/upload', methods=['POST'])
def putObject():
        file = request.files['file']
	print dir(file)
	print file.filename
	print file.content_length
        args = []
	args.append(file.filename)
	args.append(file)
	args.append('s3://sat-hadoop/')
        print "The uploaded file is " + file.filename
        req = cmd_object_put(args)
        return "Done"



if __name__ == '__main__':
    app.run(threaded=True,host='0.0.0.0', port=80)














# vim:et:ts=4:sts=4:ai
