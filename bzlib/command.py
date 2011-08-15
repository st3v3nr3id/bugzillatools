# This file is part of bugzillatools
# Copyright (C) 2011 Benon Technologies Pty Ltd, Fraser Tweedale
#
# bugzillatools is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import unicode_literals

import argparse
import itertools
import textwrap

from . import bug
from . import bugzilla
from . import config
from . import editor


class _ReadFileAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string):
        setattr(namespace, self.dest, values.read())


def with_add_remove(src, dst, metavar=None, type=None):
    def decorator(cls):
        cls.args = cls.args + [
            lambda x: x.add_argument('--add', metavar=metavar, type=type,
                nargs='+',
                help="Add {} to {}.".format(src, dst)),
            lambda x: x.add_argument('--remove', metavar=metavar, type=type,
                nargs='+',
                help="Remove {} from {}.".format(src, dst)),
        ]
        return cls
    return decorator


def with_set(src, dst, metavar=None, type=None):
    def decorator(cls):
        cls.args = cls.args + [
            lambda x: x.add_argument('--set', metavar=metavar, type=type,
                nargs='+',
                help="Set {} to {}. Ignore --add, --remove.".format(dst, src)),
        ]
        return cls
    return decorator


def with_bugs(cls):
    cls.args = cls.args + [
        lambda x: x.add_argument('bugs', metavar='BUG', type=int, nargs='+',
            help='Bug number'),
    ]
    return cls


def with_optional_message(cls):
    def msgargs(parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument('-F', '--file', metavar='MSGFILE', dest='message',
            type=argparse.FileType('r'), action=_ReadFileAction,
            help='Take comment from this file')
        group.add_argument('-m', '--message', nargs='?', const=True,
            help='Comment on the change. With no argument, invokes an editor.')
    cls.args = cls.args + [msgargs]
    return cls


def with_limit(things='items', default=None):
    def decorator(cls):
        cls.args = cls.args + [
            lambda x: x.add_argument('--limit', '-l', type=int,
                default=default, metavar='N',
                help='Limit output to N {}.'.format(things))
        ]
        return cls
    return decorator


class Command(object):
    """A command object.

    Provides arguments.  Does what it does using __call__.
    """

    """
    An array of (args, kwargs) tuples that will be used as arguments to
    ArgumentParser.add_argument().
    """
    args = []

    @classmethod
    def help(cls):
        return textwrap.dedent(filter(None, cls.__doc__.splitlines())[0])

    @classmethod
    def epilog(cls):
        return textwrap.dedent('\n\n'.join(cls.__doc__.split('\n\n')[1:]))

    def __init__(self, args, parser, commands, aliases, ui):
        """
        args: an argparse.Namespace
        parser: the argparse.ArgumentParser
        commands: a dict of all Command classes keyed by __name__.lower()
        aliases: a dict of aliases keyed by alias
        """
        self._args = args
        self._parser = parser
        self._commands = commands
        self._aliases = aliases
        self._ui = ui


class Help(Command):
    """Show help."""
    args = [
        lambda x: x.add_argument('subcommand', metavar='SUBCOMMAND', nargs='?',
            help='show help for subcommand')
    ]

    def __call__(self):
        if not self._args.subcommand:
            self._parser.parse_args(['--help'])
        else:
            if self._args.subcommand in self._aliases:
                print "'{}': alias for {}".format(
                    self._args.subcommand,
                    self._aliases[self._args.subcommand]
                )
            elif self._args.subcommand not in self._commands:
                print "unknown subcommand: '{}'".format(self._args.subcommand)
            else:
                self._parser.parse_args([self._args.subcommand, '--help'])


class BugzillaCommand(Command):
    def __init__(self, *args, **kwargs):
        super(BugzillaCommand, self).__init__(*args, **kwargs)
        # Get a Bugzilla object.
        #  Bit of a hack, but there's no nice way to get dict from Namespace
        self.bz = bugzilla.Bugzilla.from_config(**self._args.__dict__)


@with_bugs
@with_optional_message
class Assign(BugzillaCommand):
    """Assign bugs to the given user."""
    args = [
        lambda x: x.add_argument('--to', metavar='ASSIGNEE',
            help='New assignee'),
    ]

    def __call__(self):
        args = self._args
        message = editor.input('Enter your comment.') if args.message is True \
            else args.message
        return map(
            lambda x: self.bz.bug(x).set_assigned_to(args.to, comment=message),
            args.bugs
        )


@with_set('given bugs', 'blocked bugs', metavar='BUG', type=int)
@with_add_remove('given bugs', 'blocked bugs', metavar='BUG', type=int)
@with_bugs
@with_optional_message
class Block(BugzillaCommand):
    """Show or update block list of given bugs."""
    def __call__(self):
        args = self._args
        bugs = map(self.bz.bug, args.bugs)
        if args.add or args.remove or args.set:
            message = editor.input('Enter your comment.') \
                if args.message is True else args.message
            # update blocked bugs
            map(
                lambda x: self.bz.bug(x).update_block(
                    add=args.add,
                    remove=args.remove,
                    set=args.set,
                    comment=message
                ),
                args.bugs
            )
        else:
            # show blocked bugs
            for bug in bugs:
                bug.read()
                print 'Bug {}:'.format(bug.bugno)
                if bug.data['blocks']:
                    print '  Blocked bugs: {}'.format(
                        ', '.join(map(str, bug.data['blocks'])))
                else:
                    print '  No blocked bugs'


@with_add_remove('given users', 'CC List', metavar='USER')
@with_bugs
@with_optional_message
class CC(BugzillaCommand):
    """Show or update CC List."""
    def __call__(self):
        args = self._args
        bugs = map(self.bz.bug, args.bugs)
        if args.add or args.remove:
            # get actual users
            getuser = lambda x: self.bz.match_one_user(x)['name']
            add = map(getuser, args.add) if args.add else None
            remove = map(getuser, args.remove) if args.remove else None

            # get message
            message = editor.input('Enter your comment.') \
                if args.message is True else args.message

            # update CC list
            map(
                lambda x: self.bz.bug(x).update_cc(
                    add=add,
                    remove=remove,
                    comment=message
                ),
                args.bugs
            )
        else:
            # show CC List
            for bug in bugs:
                bug.read()
                print 'Bug {}:'.format(bug.bugno)
                if bug.data['cc']:
                    print '  CC List: {}'.format(
                        ', '.join(map(str, bug.data['cc'])))
                else:
                    print '  0 users'


@with_bugs
@with_optional_message
@with_limit(things='comments')
class Comment(BugzillaCommand):
    """List comments or file a comment on the given bugs."""
    args = [
        lambda x: x.add_argument('--reverse', action='store_true',
            default=True,
            help='Show from newest to oldest.'),
        lambda x: x.add_argument('--forward', action='store_false',
            dest='reverse',
            help='Show from oldest to newest.'),
    ]

    formatstring = '{}\nauthor: {creator}\ntime: {time}\n\n{text}\n\n'

    def __call__(self):
        args = self._args
        message = editor.input('Enter your comment.') \
            if args.message is True else args.message
        if message:
            map(lambda x: self.bz.bug(x).add_comment(message), args.bugs)
        else:
            def cmtfmt(bug):
                comments = sorted(
                    enumerate(self.bz.bug(bug).get_comments()),
                    key=lambda x: int(x[1]['id']),
                    reverse=True  # initially reverse to apply limit
                )

                # apply limit, if one given
                comments = comments[:abs(args.limit)] \
                    if args.limit else comments

                # re-reverse if reversed comments were /not/ wanted
                comments = reversed(comments) if not args.reverse else comments

                return '=====\nBUG {}\n\n-----\n{}'.format(
                    bug,
                    '-----\n'.join(map(
                        lambda (n, x): self.formatstring.format(
                            'comment: {}'.format(n) if n else 'description',
                            **x
                        ),
                        comments
                    ))
                )
            print '\n'.join(map(cmtfmt, args.bugs))


@with_set('given bugs', 'depdendencies', metavar='BUG', type=int)
@with_add_remove('given bugs', 'depdendencies', metavar='BUG', type=int)
@with_bugs
@with_optional_message
class Depend(BugzillaCommand):
    """Show or update dependencies of given bugs."""
    def __call__(self):
        args = self._args
        bugs = map(self.bz.bug, args.bugs)
        if args.add or args.remove or args.set:
            message = editor.input('Enter your comment.') \
                if args.message is True else args.message
            # update dependencies
            map(
                lambda x: x.update_depend(
                    add=args.add,
                    remove=args.remove,
                    set=args.set,
                    comment=message
                ),
                bugs
            )
        else:
            # show dependencies
            for bug in bugs:
                bug.read()
                print 'Bug {}:'.format(bug.bugno)
                if bug.data['depends_on']:
                    print '  Dependencies: {}'.format(
                        ', '.join(map(str, bug.data['depends_on'])))
                else:
                    print '  No dependencies'


class Fields(BugzillaCommand):
    """List valid values for bug fields."""
    def __call__(self):
        args = self._args
        fields = filter(lambda x: 'values' in x, self.bz.get_fields())
        for field in fields:
            keyfn = lambda x: x['visibility_values']
            groups = itertools.groupby(
                sorted(field['values'], None, keyfn),
                keyfn
            )
            print field['name'], ':'
            for key, group in groups:
                values = sorted(group, None, lambda x: int(x['sortkey']))
                if key:
                    print '  {}: {}'.format(
                        key,
                        ','.join(map(lambda x: x['name'], values))
                    )
                else:
                    print '  ', ','.join(map(lambda x: x['name'], values))


@with_bugs
class Info(BugzillaCommand):
    """Show detailed information about the given bugs."""
    def __call__(self):
        args = self._args
        fields = config.get_show_fields()
        for bug in map(self.bz.bug, args.bugs):
            bug.read()
            print 'Bug {}:'.format(bug.bugno)
            fields = config.get_show_fields() & bug.data.viewkeys()
            width = max(map(len, fields)) - min(map(len, fields)) + 2
            for field in fields:
                print '  {:{}} {}'.format(field + ':', width, bug.data[field])
            print


@with_bugs
class List(BugzillaCommand):
    """Show a one-line summary of the given bugs."""
    def __call__(self):
        args = self._args
        fields = config.get_show_fields()
        lens = map(lambda x: len(str(x)), args.bugs)
        width = max(lens) - min(lens) + 2
        for bug in map(self.bz.bug, args.bugs):
            bug.read()
            print 'Bug {:{}} {}'.format(
                str(bug.bugno) + ':', width, bug.data['summary']
            )


class New(BugzillaCommand):
    """File a new bug."""
    def __call__(self):
        # create new Bug
        b = bug.Bug(self.bz)

        # get mandatory fields
        fields = self.bz.get_fields()
        mandatory_fields = filter(lambda x: x['is_mandatory'], fields)

        # first choose the product
        b.data['product'] = self._ui.choose(
            'Choose a product',
            map(lambda x: x['name'], self.bz.get_products())
        )

        # fill out other mandatory fields
        for field in mandatory_fields:
            if field['name'] in b.data:
                continue  # field is already defined
            if 'values' in field:
                values = self.bz.get_field_values(
                    field['name'],
                    visible_for=b.data
                )
                # TODO handle select-multiple fields
                b.data[field['name']] = self._ui.choose(
                    'Choose the {}'.format(field['display_name']),
                    map(lambda x: x['name'], values)
                )
            else:
                # TODO take field types into account
                b.data[field['name']] = self._ui.text(
                    'Enter the {}'.format(field['display_name'])
                )

        # fill out a comment ("Description") if not already defined
        if 'comment' not in b.data:
            b.data['comment'] = editor.input(
                'Enter a description of the problem.'
            )

        # list of create fields ripped from Bugzilla documentation
        # (this info is not introspectable as of Bugzilla 4.0)
        create_fields = [
            'product', 'component', 'summary', 'version', 'comment',
            'op_sys', 'platform', 'priority', 'severity', 'alias',
            'assigned_to', 'cc', 'comment_is_private', 'groups',
            'qa_contact', 'status', 'target_milestone',
        ]

        # let user choose which of these other fields to define
        optional_fields = [ \
            x['display_name'] for x in fields \
            if x['name'] in create_fields \
                and x['name'] not in b.data.viewkeys()
        ]

        # prompt user for the fields they wish to define
        user_fields = self._ui.chooseN(
            'Set values for other fields?',
            optional_fields,
            default=[]
        )

        # iterate over those fields, prompting user for values
        for field in [x for x in fields if x['display_name'] in user_fields]:
            if field['name'] in b.data:
                continue  # field is already defined
            if 'values' in field:
                values = self.bz.get_field_values(
                    field['name'],
                    visible_for=b.data
                )
                # TODO handle select-multiple fields
                b.data[field['name']] = self._ui.choose(
                    'Choose the {}'.format(field['display_name']),
                    map(lambda x: x['name'], values)
                )
            else:
                # TODO take field types into account
                b.data[field['name']] = self._ui.text(
                    'Enter the {}'.format(field['display_name'])
                )

        # create the bug
        id = b.create()
        self._ui.show('Created Bug {}'.format(id))


class Products(BugzillaCommand):
    """List the products of a Bugzilla instance."""
    def __call__(self):
        products = self.bz.get_products()
        width = max(map(lambda x: len(x['name']), products)) + 1
        for product in products:
            print '{:{}} {}'.format(
                product['name'] + ':', width, product['description']
            )


@with_bugs
@with_optional_message
class Status(BugzillaCommand):
    """Set the status of the given bugs.

    Description
    -----------

    The ``status`` command is used to update the status and resolution of
    bugs.  The status is always required unless ``-dupe-of`` is used (see
    below).  It can be given as the argument to ``--status``, otherwise the
    user will be prompted to choose the status from a list.

    If the status is changing from one considered "open" to one not
    considered "open", a resolution is required.  It can be given using
    ``--resolution``, otherwise the user will be prompted to choose the
    resolution from a list.

    Marking bugs as duplicates
    --------------------------

    To set a bug as a duplicate, simply use ``--dupe-of <BUG>``.  ``--status``
    and ``--resolution`` will be ignored.  Bugzilla will automatically set the
    status and resolution fields to appropriate values for duplicate bugs.
    """

    args = [
        lambda x: x.add_argument('--status',
            help='Specify a resolution (case-insensitive).'),
        lambda x: x.add_argument('--resolution',
            help='Specify a resolution (case-insensitive).'),
        lambda x: x.add_argument('--dupe-of', type=int, metavar='BUG',
            help='The bug of which the given bugs are duplicates.'),
    ]

    def __call__(self):
        args = self._args
        message = editor.input('Enter your comment.') if args.message is True \
            else args.message

        if args.dupe_of:
            # This is all we need; --status and --resolution are ignored
            return map(
                lambda x: self.bz.bug(x).set_dupe_of(args.dupe_of, message),
                args.bugs
            )

        # get the values of the 'bug_status' field
        values = self.bz.get_field_values('bug_status')

        if args.status:
            status = args.status.upper()
        else:
            # choose status
            status = self._ui.choose(
                'Choose a status',
                map(lambda x: x['name'], values)
            )

        # check if the new status is "open"
        try:
            value = filter(lambda x: x['name'] == status, values)[0]
            is_open = value['is_open']
        except IndexError:
            # no value matching the chosen status
            raise UserWarning("Invalid status:", status)

        # instantiate bugs
        bugs = map(self.bz.bug, args.bugs)

        resolution = None
        if not is_open:
            # The new status accepts a resolution.
            if args.resolution:
                # A resolution was supplied.
                resolution = args.resolution.upper()
            elif any(map(lambda x: x.is_open(), bugs)):
                # A resolution was not supplied, but one is required since
                # at least one of the bugs is currently open.  Choose one.
                values = self.bz.get_field_values('resolution')
                resolution = self._ui.choose(
                    'Choose a resolution',
                    map(lambda x: x['name'], values)
                )

        return map(
            lambda x: self.bz.bug(x).set_status(
                status=status,
                resolution=resolution,
                comment=message
            ),
            args.bugs
        )


#class Search(BugzillaCommand):
#    """Search for bugs with supplied attributes."""
#    pass


# the list got too long; metaprogram it ^_^
commands = filter(
    lambda x: type(x) == type                     # is a class \
        and issubclass(x, Command)                # is a Command \
        and x not in [Command, BugzillaCommand],  # not abstract
    locals().viewvalues()
)
