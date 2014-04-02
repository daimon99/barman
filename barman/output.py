# Copyright (C) 2013-2014 2ndQuadrant Italia (Devise.IT S.r.L.)
#
# This file is part of Barman.
#
# Barman is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Barman is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Barman.  If not, see <http://www.gnu.org/licenses/>.

"""
This module control how the output of Barman will be rendered
"""

import inspect
import logging
import sys
from barman.infofile import BackupInfo
from barman.utils import pretty_size


__all__ = [
    'error_occurred', 'debug', 'info', 'warning', 'error', 'exception',
    'result', 'close_and_exit', 'close', 'set_output_writer',
    'AVAILABLE_WRITERS', 'DEFAULT_WRITER', 'ConsoleOutputWriter',
    'NagiosOutputWriter',
]

#: True if error or exception methods have been called
error_occurred = False

#: Exit code if error occurred
error_exit_code = 1


def _format_message(message, args):
    """
    Format a message using the args list. The result will be equivalent to

        message % args

    If args list contains a dictionary as its only element the result will be

        message % args[0]

    :param str message: the template string to be formatted
    :param tuple args: a list of arguments
    :return: the formatted message
    :rtype: str
    """
    if len(args) == 1 and isinstance(args[0], dict):
        return message % args[0]
    elif len(args) > 0:
        return message % args
    else:
        return message


def _put(level, message, *args, **kwargs):
    """
    Send the message with all the remaining positional arguments to
    the configured output manager with the right output level. The message will
    be sent also to the logger unless  explicitly disabled with log=False

    No checks are performed on level parameter as this method is meant
    to be called only by this module.

    If level == 'exception' the stack trace will be also logged

    :param str level:
    :param str message: the template string to be formatted
    :param tuple args: all remaining arguments are passed to the log formatter
    :key bool log: whether to log the message
    :key bool is_error: treat this message as an error
    """
    # handle keyword-only parameters
    log = kwargs.pop('log', True)
    is_error = kwargs.pop('is_error', False)
    if len(kwargs):
        raise TypeError('%s() got an unexpected keyword argument %r'
                        % (inspect.stack()[1][3], kwargs.popitem()[0]))
    if is_error:
        global error_occurred
        error_occurred = True
        _writer.error_occurred()
    # dispatch the call to the output handler
    getattr(_writer, level)(message, *args)
    # log the message as originating from caller's caller module
    if log:
        exc_info = False
        if level == 'exception':
            level = 'error'
            exc_info = True
        frm = inspect.stack()[2]
        mod = inspect.getmodule(frm[0])
        logger = logging.getLogger(mod.__name__)
        log_level = logging.getLevelName(level.upper())
        logger.log(log_level, message, *args, **{'exc_info': exc_info})


def _dispatch(obj, prefix, name, *args, **kwargs):
    """
    Dispatch the call to the %(prefix)s_%(name) method of the obj object

    :param obj: the target object
    :param str prefix: prefix of the method to be called
    :param str name: name of the method to be called
    :param tuple args: all remaining positional arguments will be sent to target
    :param dict kwargs: all remaining keyword arguments will be sent to target
    :return: the result of the invoked method
    :raise ValueError: if the target method is not present
    """
    method_name = "%s_%s" % (prefix, name)
    handler = getattr(obj, method_name, None)
    if callable(handler):
        return handler(*args, **kwargs)
    else:
        raise ValueError("The object %r does not have the %r method" % (
            obj, method_name))


def debug(message, *args, **kwargs):
    """
    Output a message with severity 'DEBUG'

    :key bool log: whether to log the message
    """
    _put('debug', message, *args, **kwargs)


def info(message, *args, **kwargs):
    """
    Output a message with severity 'INFO'

    :key bool log: whether to log the message
    """
    _put('info', message, *args, **kwargs)


def warning(message, *args, **kwargs):
    """
    Output a message with severity 'INFO'

    :key bool log: whether to log the message
    """
    _put('warning', message, *args, **kwargs)


def error(message, *args, **kwargs):
    """
    Output a message with severity 'ERROR'.
    Also records that an error has occurred unless the ignore parameter is True.

    :key bool ignore: avoid setting an error exit status (default False)
    :key bool log: whether to log the message
    """
    # ignore is a keyword-only parameter
    ignore = kwargs.pop('ignore', False)
    if not ignore:
        kwargs.setdefault('is_error', True)
    _put('error', message, *args, **kwargs)


def exception(message, *args, **kwargs):
    """
    Output a message with severity 'EXCEPTION'

    If raise_exception parameter doesn't evaluate to false raise and exception:
      - if raise_exception is callable raise the result of raise_exception()
      - if raise_exception is an exception raise it
      - else raise the last exception again

    :key bool ignore: avoid setting an error exit status
    :key raise_exception:
        raise an exception after the message has been processed
    :key bool log: whether to log the message
    """
    # ignore and raise_exception are keyword-only parameters
    ignore = kwargs.pop('ignore', False)
    #noinspection PyNoneFunctionAssignment
    raise_exception = kwargs.pop('raise_exception', None)
    if not ignore:
        kwargs.setdefault('is_error', True)
    _put('exception', message, *args, **kwargs)
    if raise_exception:
        if callable(raise_exception):
            #noinspection PyCallingNonCallable
            raise raise_exception(message)
        elif isinstance(raise_exception, BaseException):
            raise raise_exception
        else:
            raise


def init(command, *args, **kwargs):
    """
    Initialize the output writer for a given command.

    :param str command: name of the command are being executed
    :param tuple args: all remaining positional arguments will be sent
        to the output processor
    :param dict kwargs: all keyword arguments will be sent
        to the output processor
    """
    try:
        _dispatch(_writer, 'init', command, *args, **kwargs)
    except ValueError:
        exception('The %s writer does not support the "%s" command',
                  _writer.__class__.__name__, command)
        close_and_exit()


def result(command, *args, **kwargs):
    """
    Output the result of an operation.

    :param str command: name of the command are being executed
    :param tuple args: all remaining positional arguments will be sent
        to the output processor
    :param dict kwargs: all keyword arguments will be sent
        to the output processor
    """
    try:
        _dispatch(_writer, 'result', command, *args, **kwargs)
    except ValueError:
        exception('The %s writer does not support the "%s" command',
                  _writer.__class__.__name__, command)
        close_and_exit()


def close_and_exit():
    """
    Close the output writer and terminate the program.

    If an error has been emitted the program will report a non zero return
    value.
    """
    close()
    if error_occurred:
        sys.exit(error_exit_code)
    else:
        sys.exit(0)


def close():
    """
    Close the output writer.

    """
    _writer.close()


def set_output_writer(new_writer, *args, **kwargs):
    """
    Replace the current output writer with a new one.

    The new_writer parameter can be a symbolic name or an OutputWriter object

    :param new_writer: the OutputWriter name or the actual OutputWriter
    :type: string or an OutputWriter
    :param tuple args: all remaining positional arguments will be passed
        to the OutputWriter constructor
    :param dict kwargs: all remaining keyword arguments will be passed
        to the OutputWriter constructor
    """
    global _writer
    _writer.close()
    if new_writer in AVAILABLE_WRITERS:
        _writer = AVAILABLE_WRITERS[new_writer](*args, **kwargs)
    else:
        _writer = new_writer


class ConsoleOutputWriter(object):
    def __init__(self, debug=False, quiet=False):
        """
        Default output writer that output everything on console.

        :param bool debug: print debug messages on standard error
        :param bool quiet: don't print info messages
        """
        self._debug = debug
        self._quiet = quiet

        #: Used in check command to hold the check results
        self.result_check_list = []

        #: Used in status command to hold the status results
        self.result_status_list = []

        #: The minimal flag. If set the command must output a single list of
        #: values.
        self.minimal = False

    def _out(self, message, args):
        """
        Print a message on standard output
        """
        print >> sys.stdout, _format_message(message, args)

    def _err(self, message, args):
        """
        Print a message on standard error
        """
        print >> sys.stderr, _format_message(message, args)

    def debug(self, message, *args):
        """
        Emit debug.
        """
        if self._debug:
            self._err('DEBUG: %s' % message, args)

    def info(self, message, *args):
        """
        Normal messages are sent to standard output
        """
        if not self._quiet:
            self._out(message, args)

    def warning(self, message, *args):
        """
        Warning messages are sent to standard error
        """
        self._err('WARNING: %s' % message, args)

    def error(self, message, *args):
        """
        Error messages are sent to standard error
        """
        self._err('ERROR: %s' % message, args)

    def exception(self, message, *args):
        """
        Warning messages are sent to standard error
        """
        self._err('EXCEPTION: %s' % message, args)

    def error_occurred(self):
        """
        Called immediately before any message method when the originating
        call has is_error=True
        """

    def close(self):
        """
        Close the output channel.

        Nothing to do for console.
        """

    def result_backup(self, backup_info):
        """
        Render the result of a backup.

        Nothing to do for console.
        """
        # TODO: evaluate to display something useful here

    def _record_check(self, server_name, check, status, hint):
        """
        Record the check line in result_check_map attribute

        This method is for subclass use

        :param str server_name: the server is being checked
        :param str check: the check name
        :param bool status: True if succeeded
        :param str,None hint: hint to print if not None
        """
        self.result_check_list.append(dict(
            server_name=server_name, check=check, status=status, hint=hint))
        if not status:
            global error_occurred
            error_occurred = True

    def init_check(self, server_name):
        """
        Init the check command

        :param str server_name: the server we are start listing
        """
        self.info("Server %s:" % server_name)

    def result_check(self, server_name, check, status, hint=None):
        """
        Record a server result of a server check

        and output it as INFO

        :param str server_name: the server is being checked
        :param str check: the check name
        :param bool status: True if succeeded
        :param str,None hint: hint to print if not None
        """
        self._record_check(server_name, check, status, hint)
        if hint:
            self.info("\t%s: %s (%s)" %
                      (check, 'OK' if status else 'FAILED', hint))
        else:
            self.info("\t%s: %s" %
                      (check, 'OK' if status else 'FAILED'))

    def init_list_backup(self, server_name, minimal=False):
        """
        Init the list-backup command

        :param str server_name: the server we are start listing
        :param bool minimal: if true output only a list of backup id
        """
        self.minimal = minimal

    def result_list_backup(self, backup_info,
                           backup_size, wal_size,
                           retention_status):
        """
        Output a single backup in the list-backup command

        :param basestring server_name: server we are displaying
        :param BackupInfo backup_info: backup we are displaying
        :param backup_size: size of base backup (with the required WAL files)
        :param wal_size: size of WAL files belonging to this backup
            (without the required WAL files)
        :param retention_status: retention policy status
        """
        # If minimal is set only output the backup id
        if self.minimal:
            self.info(backup_info.backup_id)
            return

        out_list = ["%s %s - "
            % (backup_info.server_name, backup_info.backup_id)]
        if backup_info.status == BackupInfo.DONE:
            end_time = backup_info.end_time.ctime()
            out_list.append('%s - Size: %s - WAL Size: %s' %
                            (end_time,
                             pretty_size(backup_size),
                             pretty_size(wal_size)))
            if backup_info.tablespaces:
                tablespaces = [("%s:%s" % (tablespace.name, tablespace.location))
                               for tablespace in backup_info.tablespaces]
                out_list.append(' (tablespaces: %s)' %
                                ', '.join(tablespaces))
            if retention_status:
                out_list.append(' - %s' % retention_status)
        else:
            out_list.append(backup_info.status)
        self.info(''.join(out_list))

    def result_show_backup(self, backup_ext_info):
        """
        Output all available information about a backup in show-backup command

        The argument has to be the result of a Server.get_backup_ext_info() call

        :param dict backup_ext_info: a dictionary containing the info to display
        """
        data = dict(backup_ext_info)
        self.info("Backup %s:", data['backup_id'])
        self.info("  Server Name       : %s", data['server_name'])
        self.info("  Status            : %s", data['status'])
        if data['status'] == BackupInfo.DONE:
            self.info("  PostgreSQL Version: %s", data['version'])
            self.info("  PGDATA directory  : %s", data['pgdata'])
            if data['tablespaces']:
                self.info("  Tablespaces:")
                for item in data['tablespaces']:
                    self.info("    %s: %s (oid: %s)",
                              item.name, item.location, item.oid)
            self.info("")
            self.info("  Base backup information:")
            self.info("    Disk usage      : %s",
                      pretty_size(data['size'] + data[
                          'wal_size']))
            self.info("    Timeline        : %s", data['timeline'])
            self.info("    Begin WAL       : %s",
                      data['begin_wal'])
            self.info("    End WAL         : %s", data['end_wal'])
            self.info("    WAL number      : %s", data['wal_num'])
            self.info("    Begin time      : %s",
                      data['begin_time'])
            self.info("    End time        : %s", data['end_time'])
            self.info("    Begin Offset    : %s",
                      data['begin_offset'])
            self.info("    End Offset      : %s",
                      data['end_offset'])
            self.info("    Begin XLOG      : %s",
                      data['begin_xlog'])
            self.info("    End XLOG        : %s", data['end_xlog'])
            self.info("")
            self.info("  WAL information:")
            self.info("    No of files     : %s",
                      data['wal_until_next_num'])
            self.info("    Disk usage      : %s",
                      pretty_size(data['wal_until_next_size']))
            self.info("    Last available  : %s", data['wal_last'])
            self.info("")
            self.info("  Catalog information:")
            self.info("    Retention Policy: %s",
                      data['retention_policy_status']
                      or 'not enforced')
            self.info("    Previous Backup : %s",
                      data.setdefault('previous_backup_id', 'not available')
                      or '- (this is the oldest base backup)')
            self.info("    Next Backup     : %s",
                      data.setdefault('next_backup_id', 'not available')
                      or '- (this is the latest base backup)')
        else:
            if data['error']:
                self.info("  Error:            : %s",
                          data['error'])

    def init_status(self, server_name):
        """
        Init the status command

        :param str server_name: the server we are start listing
        """
        self.info("Server %s:", server_name)

    def result_status(self, server_name, status, description, message):
        """
        Record a result line of a server status command

        and output it as INFO

        :param str server_name: the server is being checked
        :param str status: the returned status code
        :param str description: the returned status description
        :param str,object message: status message. It will be converted to str
        """
        message = str(message)
        self.result_status_list.append(dict(
            server_name=server_name, status=status,
            description=description, message=message))
        self.info("\t%s: %s", description, message)

    def init_list_server(self, server_name, minimal=False):
        """
        Init the list-server command

        :param str server_name: the server we are start listing
        """
        self.minimal = minimal

    def result_list_server(self, server_name, description=None):
        """
        Output a result line of a list-server command

        :param str server_name: the server is being checked
        :param str,None description: server description if applicable
        """
        if self.minimal or not description:
            self.info("%s", server_name)
        else:
            self.info("%s - %s", server_name, description)

    def init_show_server(self, server_name):
        """
        Init the show-server command output method

        :param str server_name: the server we are displaying
        """
        self.info("Server %s:" % server_name)

    def result_show_server(self, server_name, server_info):
        """
        Output the results of the show-server command

        :param str server_name: the server we are displaying
        :param dict server_info: a dictionary containing the info to display
        """
        for status, message in server_info.items():
            self.info("\t%s: %s", status, message)


class NagiosOutputWriter(ConsoleOutputWriter):
    """
    Nagios output writer.

    This writer doesn't output anything to console.
    On close it writes a nagios-plugin compatible status
    """

    def _out(self, message, args):
        """
        Do not print anything on standard output
        """

    def _err(self, message, args):
        """
        Do not print anything on standard error
        """

    def close(self):
        """
        Display the result of a check run as expected by Nagios.

        Also set the exit code as 2 (CRITICAL) in case of errors
        """
        issues = []
        servers = []
        for item in self.result_check_list:
            if item['server_name'] not in servers:
                servers.append(item['server_name'])
            if not item['status'] and item['server_name'] not in issues:
                issues.append(item['server_name'])
        if len(issues) > 0:
            print "BARMAN CRITICAL - %d server out of %d has issues" % \
                  (len(issues), len(servers))
            global error_exit_code
            error_exit_code = 2
        else:
            print "BARMAN OK - Ready to serve the Espresso backup"


#: This dictionary acts as a registry of available OutputWriters
AVAILABLE_WRITERS = {
    'console': ConsoleOutputWriter,
    # nagios is not registered as it isn't a general purpose output writer
    # 'nagios': NagiosOutputWriter,
}

#: The default OutputWriter
DEFAULT_WRITER = 'console'

#: the current active writer. Initialized according DEFAULT_WRITER on load
_writer = AVAILABLE_WRITERS[DEFAULT_WRITER]()
