#!/usr/bin/python
# -*- coding: utf-8 -*-
# ex:sw=4 ts=4:ai:
#
# Copyright (c) 2013 by Benjamin Koch <bbbsnowball@gmail.com>
#
#   based on many other scripts (mostly ideas, in some cases also code):
#
#    pyrnotify.py
#    by Krister Svanlund <krister.svanlund@gmail.com>
#    http://weechat.org/scripts/source/pyrnotify.py.html/
#    GNU GPL
#
#    irssinotifier.py
#    by Caspar Clemens Mierau <ccm@screenage.de>
#    https://github.com/leitmedium/weechat-irssinotifier
#    GNU GPL v3
#    
#    windicate.py
#    by  Leon Bogaert <leon AT tim-online DOT nl>
#    and Stacey Sheldon <stac AT solidgoldbomb DOT org>
#    http://www.weechat.org/scripts/source/windicate.py.html/
#    GNU GPL v2
#
#   indirectly based on:
#     Remote Notification Script v1.1 by Gotisch <gotisch@gmail.com>
#     notifo by ochameau <poirot.alex AT gmail DOT com>
#       https://github.com/ochameau/weechat-notifo
#     notify by  lavaramano <lavaramano AT gmail DOT com>
#            and BaSh - <bash.lnx AT gmail DOT com>
#            and Sharn - <sharntehnub AT gmail DOT com>
#     notifo_notify by SAEKI Yoshiyasu <laclef_yoshiyasu@yahoo.co.jp>
#       http://bitbucket.org/laclefyoshi/weechat/
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

#TODO example
#TODO ChangeLog

SCRIPT_NAME    = "snowball-notify"
SCRIPT_AUTHOR  = "Benjamin Koch <bbbsnowball@gmail.com>"
SCRIPT_VERSION = "0.1"
SCRIPT_LICENSE = "GPL"
SCRIPT_DESC    = "Send notifications"

DEBUG = True


import sys, random, time, logging, inspect, re, traceback, subprocess, os

try:
    import weechat
    in_weechat = True
except ImportError:
    in_weechat = False

try:
    import unittest
    have_unittest = True
except:
    have_unittest = False


### Logging

# -> print to WeeChat main buffer

logger = logging.getLogger(__name__)
if DEBUG:
    logger.setLevel(logging.DEBUG)

if in_weechat:
    # log to weechat root buffer and don't propagate to default handler
    logger.propagate = False

    class WeeChatLogger(logging.Handler):
        def emit(self, record):
            text = self.format(record)
            weechat.prnt("", text)
    logger.addHandler(WeeChatLogger())
else:
    logging.basicConfig()


### Base classes for notifications, sources, sinks, ...

class Notification(object):
    """An event that might be reported as a notification, i.e. a highlight or private message"""

    def __init__(self, buffer, date, tags, displayed, highlight, prefix, message):
        #TODO parse data
        self.buffer_ptr = buffer
        self.date       = time.localtime(int(date))
        self.tags       = set(tags.split(","))
        self.displayed  = bool(int(displayed))
        self.highlight  = bool(int(highlight))
        self.prefix     = prefix
        self.message    = message

    @property
    def is_private(self):
        """is it a private message (i.e. not on a channel, but directly to a user) ?"""
        return "notify_private" in self.tags

    @property
    def short_buffer_name(self):
        return self.buffer_ptr and weechat.buffer_get_string(self.buffer_ptr, "short_name")

    @property
    def target(self):
        """to whom has the message been sent?

        This is either a channel name or "me" for a private message."""
        if self.is_private:
            return "me"
        else:
            return self.short_buffer_name

    def __repr__(self):
        return "Notification(" + repr(self.__dict__) + ")"

class NotificationSource(object):
    """Generates notifications and forwards them to a sink"""

    __slots__ = "_sink"
    def __init__(self, sink):
        self._sink = sink

    def enable(self):
        """Enable the source, i.e. from now on it should send notifications for events

        If you change the properties of the sink while the source is enabled, you must
        call update()."""
        raise NotImplementedError()

    def disable(self):
        """Disable the source, i.e. it won't send any further notifications

        You may get a few notifications that are delayed for some reason, but the source
        should try to avoid that."""
        #NOTE WeeChatNotificationSource doesn't send any further notifications, so this
        #     warning may be superfluous. However, sinks must be prepared to handle messages
        #     at any time because they may be delayed at later parts of the chain.
        raise NotImplementedError()

    def update(self):
        """Query sink properties and apply them

        You shouldn't call update() while the source is disabled."""
        self.disable()
        self.enable()

    def _get_sink(self):
        return self._sink
    sink = property(_get_sink)

class TagSet(set):
    """Set of tags that a sink or filter is interested in

    A sink/filter claims that it only wants notifications that have at least one of the
    tags in this set. It should ignore any other notifications. It might still get those
    notifications, if another sink/filter requests other tags.

    The value "*" is treated specially. It means that a sink/filter will accept tags
    that are not in the set. However, it will only ever get those tags, if another sink/
    filter requests it, so make sure that you add important tags, as well.
    """

    def __init__(self, *tags):
        super(TagSet, self).__init__()
        for tag in tags:
            if isinstance(tag, str):
                # add one tag
                self.add(tag)
            else:
                # add many tags (sequence)
                self.update(tag)

    # overwrite some methods to make them honour the special element "*" and return TagSet
    #NOTE You shouldn't use any function that is not overwritten!

    def intersection(self, other):
        x = TagSet(self)
        x.intersection_update(other)
        return x

    def intersection_update(self, other):
        if "*" in self and "*" in other:
            # union
            self.update(other)
        elif "*" in self:
            # use intersection for self, but keep all of other
            super(TagSet, self).intersection_update(other)
            self.update(other)
        elif "*" in other:
            # use intersection for other, but keep all of other
            x = super(TagSet, self).intersection(other)
            self.update(x)
        else:
            super(TagSet, self).intersection_update(other)

    def union(self, other):
        x = TagSet(self)
        x.update(other)
        return x

    # not overwriting update() because it doesn't need any special logic

    def __sub__(self, other):
        x = TagSet(self)
        x -= other
        return x

    # not overwriting update() because it doesn't need any special logic

    def __repr__(self):
        return "TagSet(" + str(list(self)) + ")"

    __str__ = __repr__

class DeliveryStatus(object):
    #NOTE I might make that a proper enum, so you shouldn't rely on the values being ints. However, you
    #     will always be able to cast them to a number with int() and compare them to numbers and each
    #     other (<, >, >=, <=, ==, !=).
    # user has confirmed that he has seen the notification
    confirmed = 100
    # notification was presented on a device that the user was using at that time
    seen = 80
    # notification was presented on a device that the user has used recently
    # (e.g. screensaver not active)
    likely_seen = 50
    # notification was presented on an inactive device and the user will notice it, when
    # she comes back
    not_yet_seen = 10
    # couldn't determine status
    unknown = 0
    # notification was presented on an inactive device and it may disappear before the user
    # has a chance to see it
    not_seen = -10
    # notification couldn't be presented
    not_presented = -30
    # an error occurred, but we have reason to believe that we might be successfull next time
    temporary_error = -50
    # an error has occurred and we don't have any more information
    error = -80
    # an error has occurred and we think that it will not go away
    permanent_error = -100

class NotificationSink(object):
    def notify(self, notification):
        """Process a notification, returns DeliveryStatus"""
        raise NotImplementedError()

    def intersted_in_tags(self):
        """Return a TagSet of tags that this sink is interested in"""
        return TagSet(["*"])

    def __add__(self, sink2):
        return MultiNotificationSink(self, sink2)

class NotificationPriority(object):
    __slots__ = "_priority"

    def __init__(self, priority):
        if isinstance(priority, bool):
            if priority:
                self._priority = 1
            else:
                self._priority = -1
        else:
            self._priority = priority

    def __int__(self):
        return self._priority

    def __and__(self, other):
        return NotificationPriority(min(int(self), int(other)))
    def __or__(self, other):
        return NotificationPriority(max(int(self), int(other)))
    def __neg__(self, other):
        return NotificationPriority(-int(self))
    def __invert__(self, other):
        return NotificationPriority(-int(self))

    def __mul__(self, other):
        # not casting other to int -> we cannot multiply two priorities
        return NotificationPriority(int(self) * other)
    def __rmul__(self, other):
        # not casting other to int -> we cannot multiply two priorities
        return NotificationPriority(int(self) * other)

    def __add__(self, other):
        return NotificationPriority(int(self) + int(other))
    def __sub__(self, other):
        return NotificationPriority(int(self) + int(other))

class NotificationFilter(object):
    def prioritize(self, notification):
        """get priority of a notification (returns a NotificationPriority)"""
        raise NotImplementedError()

    def intersted_in_tags(self):
        """Return a TagSet of tags that this filter is interested in"""
        return TagSet(["*"])

    def getattr(self, attr, *args):
        if attr == "__mul__":
            return ScaleNotificationFilter(args[1], args[0])
        elif attr == "__rmul__":
            return ScaleNotificationFilter(args[0], args[1])
        elif attr.startswith("__") and attr.endswith("__"):
            return lambda *op_args: OperatorNotificationFilter(attr, *op_args)
        else:
            return super(NotificationFilter, self).getattr(attr, *args)


### Helper classes

class ObjectRegistry(object):
    """Assign ids to objects and allow them to be retrieved by id.

    We can pass some data to hooks, but it cannot be a Python object. Therefore, we pass the
    id and later retrieve the object from the registry."""

    _instances = {}

    @classmethod
    def register(cls, object):
        id = -1
        while id < 0 or id in cls._instances:
            id = random.randint(1, 1000000)
        cls._instances[id] = object
        return id

    @classmethod
    def unregister(cls, id):
        del cls._instances[int(id)]

    @classmethod
    def get(cls, id):
        return cls._instances[int(id)]

class ShortNameRegistry(type):
    """
    Metaclass. Assigns short names to classes, used for evaluating user code.

    Use add_category(baseclass) to add a category. Subclasses of baseclass can be registered in that
    category. baseclass should use `__metaclass__ = ShortNameRegistry`, so subclasses are automatically
    registered, if they have "__shortname__" in their class dict.

    In the subclass, you can set a short name like this: __shortname__ = "name"
    If auto-detection fails, set the category, as well:  __category__  = CategoryClass

    Shortnames will be made available via the locals argument to eval. If you don't set a shortname, the
    class won't be available as a local name, but the long name is available because it will be in the
    global dictionary. If you don't want that, you can simply declare the class in another namespace.
    """

    _registry   = { }
    _used_names = { }

    @staticmethod
    def _key(baseclass):
        if not isinstance(baseclass, type):
            raise TypeError("Category must be a type name (the common base class for the category), but it is %s (%s)"
                % (baseclass, type(baseclass)))
        # We use the class name because I don't know whether a class can (efficiently) be used as a hash key.
        return baseclass.__name__

    @classmethod
    def add_category(cls, baseclass):
        baseclass_key = cls._key(baseclass)
        if baseclass_key in cls._registry:
            raise ValueError("'%s' is already registered as a category in ShortNameRegistry" % baseclass)
        
        cls._registry[baseclass_key] = { }

    @classmethod
    def _find_category_of_class(cls, class_to_register):
        baseclasses = filter(lambda bcls: cls._key(bcls) in cls._registry, inspect.getmro(class_to_register))
        if len(baseclasses) > 0:
            return baseclasses[0]
        else:
            logger.info("Couldn't determine category that I should register %s for." % class_to_register)
            logger.info("  mro:        " + str(inspect.getmro(class_to_register)))
            logger.info("  mro (keys): " + str(map(lambda bcls: cls._key(bcls), inspect.getmro(class_to_register))))
            logger.info("  categories: " + str(cls._registry.keys()))
            raise TypeError("Couldn't determine category that I should register %s for." % class_to_register)

    @classmethod
    def register(cls, name, class_to_register, baseclass = None):
        # look at parents of class_to_register to find the category class
        if not baseclass:
            baseclass = cls._find_category_of_class(class_to_register)
        baseclass_key = cls._key(baseclass)

        # make sure we cannot use a name twice
        #NOTE As categories can be combined at will, none may share a name.
        if name in cls._used_names:
            raise ValueError("The name '%s' is already used for a %s." % (name, cls._used_names[name]))

        # register the class
        #NOTE This will throw an exception (KeyError), if the category doesn't exist. This is intended.
        cls._registry[baseclass_key][name] = class_to_register
        cls._used_names[name] = type

        # return registered class, so this can be used as a class decorator
        return class_to_register

    @classmethod
    def has(cls, baseclass, name = None):
        key = cls._key(baseclass)
        return key in cls._registry and (name is None or name in cls._registry[key])

    @classmethod
    def get(cls, baseclass, name):
        key = cls._key(baseclass)
        #NOTE This will throw an exception (KeyError), if either baseclass or name doesn't exist. This is intended.
        return cls._registry[key][name]

    @classmethod
    def make_local_scope(cls, *categories):
        # special case: no arguments at all means all categories
        if len(categories) == 0:
            categories = cls._registry.keys()

        # a scope is just a dict, so we simply copy our registry dicts into it
        scope = dict()
        for category in categories:
            if isinstance(category, str):
                #NOTE The user shouldn't pass a string. This is for ourselves, when categories is empty (see above).
                #     We won't stop the user from passing a string, but don't expect that to work forever.
                key = category
            else:
                key = cls._key(category)
            #NOTE This will throw an exception (KeyError), if the category doesn't exist. This is intended.
            scope.update(cls._registry[key])
        return scope

    @classmethod
    def eval(cls, expr, *categories):
        # build scope with shortnames in categories
        scope = cls.make_local_scope(*categories)

        # try to guess whether it is an expression or some statements
        # -> if it ends with a return statement, we assume it consists of statements
        m = re.search("return\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*;?\s*$", expr)
        if m:
            # remove return statement because it isn't valid outside of a function
            expr = expr[0:m.start()]

            # it is a statement -> use exec
            exec(expr, globals(), scope)

            # exec doesn't return anything, but the return statement tells us what value we should grab
            result_var = m.group(1)
            if result_var in scope:
                return scope[result_var]
            else:
                raise ValueError(("I evaluated your code and expected to find the variable '%s' according to "
                    + "your return statement. Unfortunately, it doesn't exist. This is your code: \"\"\"%s\"\"\" "
                    + "and '%s'")
                    % (result_var, expr, m.group(0)))
        else:
            # it is an expression -> use eval
            return eval(expr, globals(), scope)

    # This class can be used as a metaclass that automatically registers classes and their subclasses.
    #NOTE If any subclass uses another metaclass, this won't work for that class (and its subclasses).
    def __new__(mcs, name, bases, dict):
        # create the class
        cls = type.__new__(mcs, name, bases, dict)

        # register it, if it has a __shortname__ property
        if "__shortname__" in dict:
            if "__category__" in dict:
                baseclass = dict["__category__"]
            else:
                baseclass = cls._find_category_of_class(cls)

            mcs.register(dict["__shortname__"], cls, baseclass)

        # return the class
        return cls

def register_shortname(name, category = None):
    return lambda cls: ShortNameRegistry.register(name, cls, category)

class WithShortname(object):
    __metaclass__ = ShortNameRegistry

class PatternMatcher(object):
    """Test whether a string matches a pattern which can either use shell syntax or a regex

    You have several options:
    (NOTE: uppercase variants might match as well, see below)
    - normal string, e.g. "abc" (special case of shell patterns)
      -> matches "abc"
    - normal string with special chars, e.g. "exact:a*b*c"
      -> matches "a*b*c"
    - shell patterns, e.g. "abc*"
      -> matches any string that starts with "abc"
    - regex, e.g. "^ab*c$"
      -> matches "ac", "abc", "abbc", ...

    The context (i.e. whoever creates the PatternMatcher) can tell it to do case-insensitive
    matching. If the context doesn't say anything, the default is case-insensitive matching.
    You can use one of the prefixes "case-sensitive:"/"cs:" or "ignore-case:"/"ic:" to force
    a particular mode. If you use it together with another prefix, the case prefix must be
    the first one, e.g. "ic:re:^ab*c$"

    Shell patterns support these special chars:
      '*'       zero or more arbitrary characters
      '?'       exactly one arbitrary character
      '[a-z_]'  character range and/or enumeration (in this example: lowercase letters and underscore)
      '{ab,cd}' either 'ab' or 'cd', supports nesting
      '\\'      escape following character (i.e. use its literal meaning);
                '\n' and some others are treated as in strings
    Shell patterns are translated to regular expressions. This means that some characters might accidentally
    have the same special meaning as in a regex. If you trip over such a bug, please report it. Please bear
    with me - it might take some time to fix all the special cases.

    Regular expressions are passed to re.compile(). The `re` module has very good documentation, so I
    won't even try to beat it ;-)
    see http://docs.python.org/2/library/re.html
    A few more notes, though: The PatternMatcher will use the search function, so it will match patterns in
    the middle of a string. I think this is the natural behaviour because everyone does it (except Python *g*).
    If you need to set a regex flag, you must do so in the regex using the "(?iLmsux)" syntax. Search for that
    in the documentation.
    """

    __slots__ = "_pattern", "_ignore_case"

    def __init__(self, pattern, ignore_case = True):
        self._pattern, self._ignore_case = self._parse_pattern(pattern, ignore_case)

    def matches(self, text):
        if isinstance(self._pattern, str):
            if self._ignore_case:
                return self._pattern == text.lower()
            else:
                return self._pattern == text
        else:
            return bool(self._pattern.search(text))

    @classmethod
    def _parse_pattern(cls, pattern, ignore_case):
        # prefix is always case-insensitive, so we convert the pattern to lowercase to test prefixes
        patternL = pattern.lower()

        # process case-sensitivity prefix
        for prefix, ic_value in [["cs:", False], ["case-sensitive:", False], ["ic:", True], ["ignore-case", True]]:
            if patternL.startswith(prefix):
                ignore_case = ic_value
                pattern  = pattern [len(prefix):]
                patternL = patternL[len(prefix):]
                break

        # check type prefix and process pattern
        if patternL.startswith("exact:"):
            matcher = pattern[len("exact:"):]
        elif patternL.startswith("re:"):
            pattern = pattern[len("re:"):]
            if ignore_case:
                flags = re.IGNORECASE
            else:
                flags = 0
            matcher = re.compile(pattern, flags)
        else:
            pattern = cls.translate_shell_pattern(pattern)
            if ignore_case:
                flags = re.IGNORECASE
            else:
                flags = 0
            matcher = re.compile(pattern, flags)

        return (matcher, ignore_case)

    @staticmethod
    def translate_shell_pattern(pattern):
        # We match special parts of the pattern with a regex and replace them. The replacement is
        # chosen by a function. The function has to keep track of some state (e.g. are we currently
        # in a character class?), so we use a lambda to pass some state to it.

        initial_status = {
            "in_braces": 0,
            "in_brackets": False
        }
        def replace(m, status):
            all = unchanged = m.group(0)
            ch0 = all[0]

            in_braces, in_brackets = status["in_braces"], status["in_brackets"]

            # escapes remain
            if ch0 == '\\':
                if '0' <= all[1] and all[1] <= '9':
                    # number escapes are special: either group reference or character code
                    if all[1] == '0' and len(all) >= 3 or len(all) >= 4 or in_brackets:
                        # character code -> keep
                        return unchanged
                    else:
                        # would be a group reference -> escape it
                        return "\\" + all
                elif 'a' <= all[1] and all[1] <= 'z' or 'A' <= all[1] and all[1] <= 'Z':
                    if all[1] in "afnrtvx" or all[1] == 'b' and in_brackets:
                        # will be replaced by a special character, e.g. '\n' by newline
                        return unchanged
                    else:
                        # might be a special one (i.e. '\A' for start of string) and we don't have
                        # to escape it anyway, so we remove the backslash
                        return all[1:]
                else:
                    # regex will treat it properly, i.e. literal
                    return unchanged

            # ? and * are expanded to appropriate regexes
            elif all == '?':
                if not in_brackets:
                    return "."
                else:
                    return unchanged
            elif all == '*':
                if not in_brackets:
                    return ".*"
                else:
                    return unchanged

            # [...] remains unchanged, but we must remember that we are in there, so we
            # don't change any special characters
            elif all == '[':
                #NOTE another opening bracket is not an error, I think -> second one is part of the character class
                status["in_brackets"] = True
                return unchanged
            elif all == ']':
                if not in_brackets:
                    raise ValueError("too many closing ']'")
                status["in_brackets"] = False
                return unchanged

            # {abc,def} becomes (abc|def), but...
            # - we mustn't change commas outside of {}
            #   (special case: {[,]} -> don't change)
            # - we use non-capturing parens: (?:...)
            elif all == '{':
                status["in_braces"] += 1
                return "(?:"
            elif all == ',':
                if in_braces > 0 and not in_brackets:
                    return "|"
                else:
                    return unchanged
            elif all == '}':
                if in_braces <= 0:
                    raise ValueError("too many closing '}' in pattern")
                status["in_braces"] -= 1
                return ")"

            # escape special chars
            elif all in [".", "^", "$", "+", "|", "(", ")"]:
                if not in_brackets:
                    return "\\" + all
                else:
                    return unchanged

            else:
                # this shouldn't happen
                raise RuntimeError("Sorry, I don't know how to handle this: %r" % all)

        try:
            special = "\\\\.|\\\\[0-9]+|[?*{,}.^$+|()]|\\[|\\]"
            pattern = re.sub(special, lambda m: replace(m, initial_status), pattern)

            if initial_status["in_brackets"]:
                raise ValueError("missing ']' in pattern: %r" % pattern)
            elif initial_status["in_braces"] > 0:
                raise ValueError("missing '}' in pattern: %r" % pattern)
        except ValueError as e:
            raise ValueError(e.message + (" in pattern: %r" % pattern))

        # only match complete string
        pattern = "\\A" + pattern + "\\Z"

        # done :-)
        return pattern

    def __str__(self):
        s = "PatternMatcher("
        if isinstance(self._pattern, str):
            s += "'" + self._pattern + "'"
            if self._ignore_case:
                s += ", ignore-case"
        else:
            s += "/" + self._pattern.pattern + "/"
            if self._ignore_case:
                s += "i"
        s += ")"
        return s


#### Classes for test of ShortNameRegistry

def register_classes_for_shortname_test():
    class Base1(WithShortname):
        pass
    class Base2(object):
        pass

    ShortNameRegistry.add_category(Base1)
    ShortNameRegistry.add_category(Base2)

    # simple decorator, category is auto-detected
    @register_shortname("a2")
    class A2(Base2):
        pass
    # auto-detection fails, so we specify the category as an argument
    @register_shortname("b1", Base1)
    class B1(object):
        pass
    # overwrite auto-detected category
    @register_shortname("c1", Base1)
    class C1(Base2):
        pass
    # register via metaclass, category auto-detected
    class D1(Base1):
        __shortname__ = "d1"
    # auto-detection fails, so we specify the category as an argument
    class E2(object):
        # super doesn't set the metaclass, so we do that here
        __metaclass__ = ShortNameRegistry
        __shortname__ = "e2"
        __category__  = Base2
    # overwrite auto-detected category
    class F2(Base1):
        __shortname__ = "f2"
        __category__  = Base2
    # use metaclass, but don't give a shortname -> not registered
    class G0(Base1):
        pass

    return { "categories": [Base1, Base2], Base1: {"b1": B1, "c1": C1, "d1": D1},
                Base2: {"a2": A2, "e2": E2, "f2": F2}, None: {"g0": G0},
                "tests": [ ["a2()", [Base2], A2], ["(c1(), d1())[1]", [], D1], ["c1", [Base2], NameError],
                           ["(a2(), c1())[1]", [], C1], ["(a2(), c1())[1]", [Base1, Base2], C1],
                           ["(a2(), c1())[1]", [Base1], NameError],
                           # a few statements
                           ["a = a2();    c = c1(); return a",       [], A2],
                           ["a = a2();    c = c1(); return c ; ",    [], C1],
                           ["a = a2(); _c_1 = c1(); return _c_1 ; ", [], C1],
                           ["a = a2();    c = c1(); return b",       [], ValueError]] }


### WeeChat-specific subclasses

def _on_notification(id, *args):
    self = ObjectRegistry.get(id)
    return self.on_notification(args)

class WeeChatNotificationSource(NotificationSource):
    __slots__ = "_last_messages", "_last_messages_next", "_hooks", "_id"

    def __init__(self, sink):
        global weechat_notification_source_instances
        super(WeeChatNotificationSource, self).__init__(sink)
        self._id = ObjectRegistry.register(self)

        self._hooks = {}

        # store 5 last messages, so we don't send them multiple times
        self._last_messages = [None] * 5
        self._last_messages_next = 0

    def enable(self):
        tags = self.sink.intersted_in_tags()
        if "*" in tags:
            tags.remove("*")
        if len(tags) == 0:
            logger.warning("Enabling hook for an empty set of tags. You won't get any "
                + "notifications.")

        #NOTE hook_print supports more than one tag for the tags argument, but this is AND, so
        #     we cannot use it
        for tag in tags:
            self.enable_tag(tag)

    def disable(self):
        for tag in self._hooks.keys():
            self.disable_tag(tag)

    def update(self):
        active_tags = set(self._hooks.keys())
        wanted_tags = self.sink.intersted_in_tags()
        for tag in wanted_tags - active_tags:
            self.enable_tag(tag)
        for tag in active_tags - wanted_tags:
            self.disable_tag()

    def enable_tag(self, tag):
        if tag not in self._hooks:
            self._hooks[tag] = weechat.hook_print("", tag, "", 1, "_on_notification", str(self._id))

    def disable_tag(self, tag):
        if tag in self._hooks:
            weechat.unhook(self._hooks[tag])
            del self._hooks[tag]

    def on_notification(self, notification):
        #NOTE If a message matches more than one tag, we receive it more than once. Therefore, we
        #     filter duplicate messages.
        if any(map(lambda x: x == notification, self._last_messages)):
            # we already got that one
            logger.info("got duplicate notification")
            return weechat.WEECHAT_RC_OK

        # add it to the queue
        i = self._last_messages_next
        self._last_messages[i] = notification
        self._last_messages_next = (i+1) % len(self._last_messages)

        # send notification
        self.sink.notify(Notification(*notification))
        return weechat.WEECHAT_RC_OK


### Container subclasses

class MultiNotificationSink(NotificationSink):
    """Combine several sinks and send notifications to each of them"""

    __slots__ = "_sinks", "default_target_status", "default_status"
    def __init__(self, *sinks):
        if isinstance(sinks[0], (int, DeliveryStatus)):
            self.default_target_status = sinks[0]
            del sinks[0]
        else:
            self.default_target_status = DeliveryStatus.unknown

        if isinstance(sinks[0], (int, DeliveryStatus)):
            self.default_status = sinks[0]
            del sinks[0]
        else:
            self.default_status = DeliveryStatus.not_presented

        self._sinks = [ ]
        self.add_sinks(sinks)

    def __new__(cls, *sinks):
        # create a new MultiNotificationSink or use the first one
        #NOTE We cannot easily use any other one, if we want to keep the order.
        if len(sinks) >= 1 and isinstance(sinks[0], MultiNotificationSink):
            sink = sinks[0]
            del sinks[0]

            # add sinks
            sink.add_sinks(sinks)
        else:
            sink = super(MultiNotificationSink, cls).__new__(cls, sinks)

        return sink

    def add_sink(self, sink, target_status = None):
        """Add a sink at the end"""
        if target_status is None:
            target_status = self.default_target_status
        self._sinks.append([sink, target_status])

    def del_sink(self, sink):
        """Remove a sink"""
        item = filter(lambda x: x[0] == sink, self._sinks)
        if len(item) >= 0:
            self._sinks.remove(item[0])
            return True
        else:
            return False

    def add_sinks(self, sinks):
        for sink2 in sinks:
            self.add_sink(sink2)

    def __iadd__(self, sink):
        """Add a sink at the end"""
        self.add_sink(sink)

    def __isub__(self, sink):
        """Remove a sink"""
        self.del_sink(sink)

    @property
    def children(self):
        return map(lambda x: x[0], self._sinks)

    def intersted_in_tags(self):
        tags = TagSet()
        for child in self.children:
            tags.update(child.intersted_in_tags())
        return tags

    def notify(self, notification):
        result = self.default_status

        for sink, target_status in self._sinks:
            if target_status is None:
                target_status = self.default_target_status

            status = sink.notify(notification)

            if status >= target_status:
                # success :-)
                return status
            
            if status < result:
                # lower result value
                result = status

        # no more sinks to try
        # -> return default status or lowest status, whichever is lower
        return result

class OperatorNotificationFilter(NotificationFilter):
    """Execute filters and combine their result with an operator, e.g. filter1 + filter2"""

    __slots__ = "operator", "args"

    def __init__(self, operator, *op_args):
        self.operator = operator
        self.args = op_args

    def prioritize(self, notification):
        args = map(lambda x: x.prioritize(notification), self.args)
        return getattr(args[0], self.operator)(*args[1:])

    def intersted_in_tags(self):
        if self.operator in ["__add__", "__sub__", "__or__"]:
            # union tags
            tags = TagSet()
            for child in self._sinks:
                tags.update(child.intersted_in_tags())
            return tags
        elif self.operator in ["__and__"]:
            # intersect tags
            tags = TagSet()
            for child in self._sinks:
                tags.intersection_update(child.intersted_in_tags())
            return tags
        elif self.operator in ["__not__", "__invert__"]:
            # we can't say anything about the tags
            return TagSet("*")
        else:
            logger.error("Unknown operator '%s'", self.operator)
            return TagSet("*")


### Helper filters

class DecoratorNotificationFilter(NotificationFilter):
    """Abstract class. Modify the behaviour of an inner filter."""
    __slots__ = "_filter"

    filter = property(lambda self: self._filter)

    def __init__(self, filter):
        self._filter = filter

    def intersted_in_tags(self):
        return self._filter.intersted_in_tags()

    def prioritize(self, notification):
        return self._filter.prioritize(notification)

class ScaleNotificationFilter(DecoratorNotificationFilter):
    """Scale filter result"""

    __slots__ = "_factor"

    def __init__(self, factor, filter):
        super(ScaleNotificationFilter, self).__init__(filter)
        self._factor = factor

    def prioritize(self, notification):
        return super(ScaleNotificationFilter, self).prioritize(notification) * self._factor


### Some filters

class ShortNameNotificationFilter(WithShortname, NotificationFilter):
    """Abstract class for notification filters with a short name"""
    pass

ShortNameRegistry.add_category(NotificationFilter)


class AllTagsFilter(ShortNameNotificationFilter):
    """Matches messages that have all tags"""

    __shortname__ = "all_tags"
    __slots__ = "_tags"

    def __init__(self, *tags):
        self._tags = tuple(tags)

    @property
    def tags(self):
        return self._tags

    def intersted_in_tags(self):
        return TagSet(self._tags)

    def prioritize(self, notification):
        return NotificationPriority( all(map(lambda tag: tag in notification.tags, self._tags)) )

class AnyTagFilter(ShortNameNotificationFilter):
    """Matches messages that have any of the tags"""

    __shortname__ = "any_tag"
    __slots__ = "_tags"

    def __init__(self, *tags):
        self._tags = tuple(tags)

    @property
    def tags(self):
        return self._tags

    def intersted_in_tags(self):
        return TagSet(self._tags) + ["*"]

    def prioritize(self, notification):
        return NotificationPriority( any(map(lambda tag: tag in notification.tags, self._tags)) )

class HighlightFilter(ShortNameNotificationFilter):
    """Matches messages that are highlighted for you"""

    __shortname__ = "highlight"

    def prioritize(self, notification):
        return NotificationPriority(notification.highlight)

class PrivateMessageFilter(ShortNameNotificationFilter):
    """Matches private messages"""

    __shortname__ = "private"

    def prioritize(self, notification):
        return NotificationPriority( "notify_private" in notification.tags )

class NickFilter(ShortNameNotificationFilter):
    """Matches messages from a certain user (supports pattern)"""
    #TODO support matching by additional information about the user, e.g. host they connect from

    __shortname__ = "nick"
    __slots__     = "_nick_pattern"

    def __init__(self, nick):
        self._nick_pattern = PatternMatcher(nick)

    def prioritize(self, notification):
        #TODO is prefix always the nick?

        # find tag that tells us about the nick
        #NOTE I think this will always be zero or one, but we support more - just in case ;-)
        nick = filter(lambda tag: tag.startswith("nick_"), notification.tags)
        # remove prefix
        nick = map(lambda tag: tag[5:])

        # does it match the pattern?
        matches = any(lambda n: self._nick_pattern.matches(n), nick)
        return NotificationPriority(matches)

class MessageFilter(ShortNameNotificationFilter):
    """Matches messages that match a pattern"""

    __shortname__ = "text"
    __slots__     = "_msg_pattern"

    def __init__(self, pattern):
        self._msg_pattern = PatternMatcher(pattern)

    def prioritize(self, notification):
        return NotificationPriority( self._msg_pattern.matches(notification.message) )

        # find tag that tells us about the nick
        #NOTE I think this will always be zero or one, but we support more - just in case ;-)
        nick = filter(lambda tag: tag.startswith("nick_"), notification.tags)
        # remove prefix
        nick = map(lambda tag: tag[5:])

        # does it match the pattern?
        matches = any(lambda n: self._nick_pattern.matches(n), nick)
        return NotificationPriority(matches)

class ServerFilter(ShortNameNotificationFilter):
    """Matches messages on a certain server (supports pattern)"""

    __shortname__ = "server"
    __slots__     = "_server_pattern"

    #TODO


### Notification sinks

class ShortNameNotificationSink(WithShortname, NotificationSink):
    """Abstract class for notification sinks with a short name"""
    pass

ShortNameRegistry.add_category(NotificationSink)


# LibnotifySink and NotifySendSink are based on
# pyrnotify.py by Krister Svanlund <krister.svanlund@gmail.com>
# http://www.weechat.org/scripts/source/pyrnotify.py.html/

class LibnotifySink(ShortNameNotificationSink):
    __shortname__ = "libnotify"
    __slots__     = ()

    def __new__(cls, *args, **kwargs):
        """LibnotifySink is abstract, so this method returns an instance of
        either PyNotifySink (preferred) or NotifySendSink"""
        if cls != LibnotifySink:
            # constructor has been called for a subclass
            # -> we won't mess with it
            return super(LibnotifySink, cls).__new__(cls, *args, **kwargs)

        if PyNotifySink.available():
            logger.info("Using PyNotifySink to provide LibnotifySink")
            return PyNotifySink(*args, **kwargs)
        elif NotifySendSink.available():
            logger.info("Using NotifySendSink to provide LibnotifySink")
            return NotifySendSink(*args, **kwargs)
        else:
            raise RuntimeError("Please install either the pynotify library or the "
                + "notify-send binary. On Debian, you can do that with one of these commands:\n"
                + "  sudo apt-get install python-gobject\n"
                + "  sudo apt-get install python-notify2    # or python3-notify2\n"
                + "  sudo apt-get install libnotify-bin")

    def _get_icon(self, notification):
        if notification.is_private and weechat.config_get_plugin('pm-icon'):
            return "emblem-favorite"        #TODO: w.config_get_plugin('pm-icon')
        else:
            return "utilities-terminal"     #TODO: w.config_get_plugin('icon')
        # This one is also a nice option: "/usr/share/pixmaps/weechat.xpm"
        # It is used by notify.py

    def _get_urgency(self, notification):
        return "normal"

    def _get_title(self, notification):
        sender  = notification.prefix
        title   = "%s to %s" % (sender, notification.target)
        return title

    def _get_timeout(self, notification):
        # timeout is in milliseconds. It must be an int or None.
        # None: default
        # -1:   default
        #  0:   forever
        # >0:   timeout in milliseconds
        return None

    def do_notify(self, urgency, category, icon, title, body, timeout):
        raise NotImplementedError()

    def notify(self, notification):
        # filtering shouldn't be in here
        if not notification.is_private and not notification.highlight:
            return

        urgency  = self._get_urgency(notification)
        category = "IRC"
        icon     = self._get_icon(notification)
        title    = self._get_title(notification)
        body     = notification.message
        timeout  = self._get_timeout(notification)

        self.do_notify(urgency, category, icon, title, body, timeout)

class NotifySendSink(LibnotifySink):
    __shortname__ = "notify_send"
    __slots__     = ()

    @staticmethod
    def available():
        try:
            with open(os.devnull, 'w') as fnull:
                return 0 == subprocess.call(["which", "notify-send"],
                    # output goes to /dev/null (hide it)
                    stdout = fnull, stderr = fnull)
        except OSError:
            # we cannot even call 'which'?
            return False

    def __init__(self):
        if not NotifySendSink.available():
            raise RuntimeError("Please install either the "
                + "notify-send binary. On Debian, you can do that like this:\n"
                + "  sudo apt-get install libnotify-bin")

    @staticmethod
    def _escape(s):
        return re.sub(r'([\\"\'])', r'\\\1', s)
    def do_notify(self, urgency, category, icon, title, body, timeout):
        args = ["notify-send"] + (["-t", int(timeout)] if timeout else [])       \
                + ["-u", urgency, "-c", self._escape(category), "-i", icon, \
                   self._escape(title), self._escape(body)]
        try:
            subprocess.call(args)
        except ValueError:
            logger.exception("Error while calling notify-send: %r", args)
        except OSError:
            logger.exception("Error while calling notify-send: %r", args)

# Bindings from gi.repository should be newer than pynotify module, so we try them first
# see http://stackoverflow.com/q/14360006
try:
    from gi.repository import Notify
    have_pynotify = True

    # rename it, so we can use the same name no matter which module we import)
    pynotify = Notify
    pynotify_type = "gi"
    del Notify
except ImportError:
    # hm, didn't work -> try the other one
    try:
        import pynotify
        have_pynotify = True
        pynotify_type = "pynotify"
    except:
        have_pynotify = False


# documentation is here: https://developer-next.gnome.org/libnotify/0.7/
# Python bindings are quite straight-forward. I couldn't find any reference doc,
# but there are some examples: https://wiki.archlinux.org/index.php/Libnotify#Python
class PyNotifySink(LibnotifySink):
    __shortname__ = "pynotify"
    __slots__     = ()

    @staticmethod
    def available():
        return have_pynotify

    def __init__(self):
        if not NotifySendSink.available():
            raise RuntimeError("Please install either the "
                + "notify-send binary. On Debian, you can run one of these commands:\n"
                + "  sudo apt-get install python-gobject\n"
                + "  sudo apt-get install python-notify2    # or python3-notify2")

        # we use the same name as notify.py
        if not pynotify.is_initted():
            pynotify.init("wee-notifier")

        #NOTE We may want to use pynotify.get_server_caps() and pynotify.get_server_info()
        #     to learn something about the notification server. On my system, they return this:
        # caps: ['actions', 'body', 'body-markup', 'icon-static', 'x-canonical-private-icon-only']
        # info: {'version': '0.2.2', 'vendor': 'Xfce', 'name': 'Xfce Notify Daemon',
        #        'spec-version': '0.9'}
        #       via pynotify
        # info: (True, 'Xfce Notify Daemon', 'Xfce', '0.2.2', '0.9')
        #       via gi.repository.Notify
        # I'm running Ubuntu 12.04 with a Unity desktop (not xfce).

    def translate_urgency(self, urgency_name):
        urgency_name = urgency_name.upper()

        if False:
            # We cannot pynotify.Urgency because it causes this error:
            #   Warning: cannot register existing type `Urgency'
            #   SystemError: error return without exception set
            # It breaks when WeeChat reloads the script (this means it works, if
            # you don't reload the script). I think gi forgets the Python part of
            # the state, but it keeps the C part. Therefore, Python thinks it should
            # register the enum, but the C code complains because it did register the
            # same type earlier.
            # It works fine with pynotify; probably because we don't access the Urgency
            # type in any direct way.

            # pynotify has pynotify.URGENCY_LOW, but gi.repository.Notify has Urgency.LOW
            #NOTE both have pynotify.Urgency
            print urgency_name
            print pynotify.Urgency
            value = getattr(getattr(pynotify, "Urgency", None), urgency_name, None)
            if value is not None:
                print value
                return value

            # try the old way
            value = getattr(pynotify, "URGENCY_" + urgency_name, None)
            if value is not None:
                print value
                return value
        else:
            # simple solution: hardcode the values
            urgencies_by_name = { "LOW": 0, "NORMAL": 1, "CRITICAL": 2 }
            if urgency_name in urgencies_by_name:
                return urgencies_by_name[urgency_name]
            else:
                return 

        # nope, we can't find it
        raise ValueError("Unknown urgency: %s" % urgency_name)

    def do_notify(self, urgency, category, icon, title, body, timeout):
        if pynotify_type == "gi":
            nn = pynotify.Notification(summary = title)
            nn.update(title, body, icon)
        else:
            nn = pynotify.Notification(title, body, icon)
        nn.set_category(category)
        nn.set_urgency(self.translate_urgency(urgency))
        if timeout:
            nn.set_timeout(int(timeout))
        nn.show()
        #NOTE We can do some things that we couldn't do with notify-send:
        # - use add_action to add a button to the notification
        #   def blub(notification, action_name, user_data):
        #     ...
        #   n.add_action("name", "label", blub, user_data)
        # - close the notification, if the user reads it in WeeChat (and probably
        #   keep it open for a longer time or even NOTIFY_EXPIRES_NEVER)
        # - wait for the "closed" signal and find out why the notification was closed
        #   def closed(notification):
        #     ...
        #   n.connect("closed", close)
        #   NOTE get_closed_reason is not available in pynotify (at least in my version)
        #        However, we can use get_property("closed-reason") to get it anyway.
        #   The meaning of that value isn't explained in libnotify. I found it in the
        #   source code of notify-daemon:
        #   https://launchpad.net/ubuntu/+source/notification-daemon/0.7.3-1
        #   notification-daemon_0.7.3.orig.tar.xz: src/nd-notification.h
        #   typedef enum
        #   {
        #           ND_NOTIFICATION_CLOSED_EXPIRED = 1,
        #           ND_NOTIFICATION_CLOSED_USER = 2,
        #           ND_NOTIFICATION_CLOSED_API = 3,
        #           ND_NOTIFICATION_CLOSED_RESERVED = 4
        #   } NdNotificationClosedReason;
        #   In addition, the default value (not closed, yet) is -1.


### Other stuff

class RemoteNotifySink(NotificationSink):
    def __init__(self, inner):
        pass

def run_debug(self, argv):
    #TODO
    pass

class DebugNotificationSink(NotificationSink):
    def notify(self, notification):
        weechat.prnt("", repr(notification))

    def intersted_in_tags(self):
        return TagSet("notify_message", "notify_private", "notify_highlight", "nick_snowball")

def run_weechat():
    if weechat.register(SCRIPT_NAME, SCRIPT_AUTHOR, SCRIPT_VERSION, SCRIPT_LICENSE, SCRIPT_DESC, "", ""):
        #TODO add settings
        #TODO init
        w = WeeChatNotificationSource(DebugNotificationSink() + LibnotifySink())
        w.enable()

if have_unittest:
    class TestNotifications(unittest.TestCase):
        def testTagSet(self):
            a = TagSet("a", "b", "c")
            b = TagSet(["d", "e", "f"])
            c = TagSet(b)
            c.add("g")

            self.assertTrue("a" in a)
            self.assertTrue("b" in a)
            self.assertTrue("c" in a)
            self.assertTrue("d" in b)
            self.assertTrue("e" in b)
            self.assertTrue("f" in b)
            self.assertTrue("d" in c)
            self.assertTrue("e" in c)
            self.assertTrue("f" in c)

            self.assertTrue("d" not in a)
            self.assertTrue("a" not in b)
            self.assertTrue("a" not in c)
            self.assertTrue("*" not in a)
            self.assertTrue("*" not in b)
            self.assertTrue("*" not in c)

            self.assertTrue("g"     in c)
            self.assertTrue("g" not in b, "c is a copy of b and not the same object")


            self.assertIsInstance(a.intersection(b), TagSet)
            self.assertIsInstance(a.union(b),        TagSet)
            self.assertIsInstance(a-b,               TagSet)

            d = TagSet(["b", "d", "e", "g"])

            self.assertEqual(a.intersection(b), TagSet([]))
            self.assertEqual(a.intersection(d), TagSet(["b"]))
            self.assertEqual(b.intersection(d), TagSet(["d", "e"]))
            self.assertEqual(c.intersection(d), TagSet(["d", "e", "g"]))
            self.assertEqual(d, TagSet(["b", "d", "e", "g"]), "set hasn't changed")

            self.assertEqual(a.union(b), TagSet(["a", "b", "c", "d", "e", "f"]))
            self.assertEqual(a.union(d), TagSet(["a", "b", "c", "d", "e",      "g"]))
            self.assertEqual(b.union(d), TagSet([     "b",      "d", "e", "f", "g"]))
            self.assertEqual(c.union(d), TagSet([     "b",      "d", "e", "f", "g"]))
            self.assertEqual(d, TagSet(["b", "d", "e", "g"]), "set hasn't changed")

            e = TagSet(["b", "d", "e", "g", "*"])
            f = TagSet(["b", "d", "h",      "*"])

            self.assertEqual(a.intersection(e), a)
            self.assertEqual(b.intersection(e), b)
            self.assertEqual(c.intersection(e), c)
            self.assertEqual(e.intersection(a), a)
            self.assertEqual(e.intersection(b), b)
            self.assertEqual(e.intersection(c), c)
            self.assertEqual(e.intersection(f), TagSet(["b", "d", "e", "g", "h", "*"]))
            self.assertEqual(f.intersection(e), TagSet(["b", "d", "e", "g", "h", "*"]))
            self.assertEqual(e, TagSet(["b", "d", "e", "g", "*"]), "set hasn't changed")
            self.assertEqual(f, TagSet(["b", "d", "h",      "*"]), "set hasn't changed")

            self.assertEqual(a.union(e), TagSet(["a", "b", "c", "d", "e",      "g",      "*"]))
            self.assertEqual(b.union(e), TagSet([     "b",      "d", "e", "f", "g",      "*"]))
            self.assertEqual(c.union(e), TagSet([     "b",      "d", "e", "f", "g",      "*"]))
            self.assertEqual(e.union(a), TagSet(["a", "b", "c", "d", "e",      "g",      "*"]))
            self.assertEqual(e.union(b), TagSet([     "b",      "d", "e", "f", "g",      "*"]))
            self.assertEqual(e.union(c), TagSet([     "b",      "d", "e", "f", "g",      "*"]))
            self.assertEqual(e.union(f), TagSet([     "b",      "d", "e",      "g", "h", "*"]))
            self.assertEqual(f.union(e), TagSet([     "b",      "d", "e",      "g", "h", "*"]))
            self.assertEqual(e, TagSet(["b", "d", "e", "g", "*"]), "set hasn't changed")
            self.assertEqual(f, TagSet(["b", "d", "h",      "*"]), "set hasn't changed")

            # not testing __sub__ because it behaves like set.__sub__
            # Yeah, I wouldn't have to test union() for the same reason...

        def testShortNameRegistry(self):
            # we need some test classes
            t = register_classes_for_shortname_test()

            for category in t["categories"]:
                self.assertTrue(ShortNameRegistry.has(category))
            self.assertFalse(ShortNameRegistry.has(TestNotifications))
            self.assertRaises(KeyError, lambda: ShortNameRegistry.get(TestNotifications, "dummy"))

            for category, members in t.iteritems():
                # is it a category or None? (not "categories")
                if isinstance(category, type) or category is None:
                    for name, cls in members.iteritems():
                        # we can retrieve all registered classes
                        if category is not None:
                            self.assertTrue(ShortNameRegistry.has(category, name),
                                "'%s' exists in category %s" % (name, category))
                            self.assertIs  (ShortNameRegistry.get(category, name), cls)

                        # we cannot retrieve them from another category
                        for category2 in t.keys():
                            if isinstance(category2, type) and category != category2:
                                self.assertFalse(ShortNameRegistry.has(category2, name))
                                self.assertRaises(KeyError, lambda: ShortNameRegistry.get(category2, name))

            for code_to_eval, categories, should_be_instance_of in t["tests"]:
                if not issubclass(should_be_instance_of, Exception):
                    self.assertIsInstance(ShortNameRegistry.eval(code_to_eval, *categories), should_be_instance_of)
                else:
                    self.assertRaises(should_be_instance_of, lambda: ShortNameRegistry.eval(code_to_eval, *categories))

        def testPatternMatcher_translate_shell_pattern(self):
            def check(pattern, result):
                self.assertEqual(PatternMatcher.translate_shell_pattern(pattern), result)
            check(r"a?c*",                     r"\Aa.c.*\Z"                         )
            check(r"a\?c*",                    r"\Aa\?c.*\Z"                        )
            check(r"__{a\?c*,b[.,]d}__",       r"\A__(?:a\?c.*|b[.,]d)__\Z"         )
            check(r"-{a{b,c},d{ef,gh,i}j}-,-", r"\A-(?:a(?:b|c)|d(?:ef|gh|i)j)-,-\Z")
            check(r"(?M(?:x))",                r"\A\(.M\(.:x\)\)\Z"                 )

            def check_exception(exc, pattern):
                self.assertRaises(exc, lambda: PatternMatcher.translate_shell_pattern(pattern))
            check_exception(ValueError, "]")
            check_exception(ValueError, "[]]")
            check_exception(ValueError, "}")
            check_exception(ValueError, "{")
            check_exception(ValueError, "{{}{}")
            check_exception(ValueError, "{}}")
            check_exception(ValueError, "}{}{")

        def testPatternMatcher(self):
            def check1(pattern, texts, result, ignore_case = True):
                if isinstance(texts, str):
                    texts = [texts]
                if result:
                    match_wish = "should match"
                else:
                    match_wish = "should not match"
                for text in texts:
                    matcher = PatternMatcher(pattern, ignore_case)
                    real_result = matcher.matches(text)
                    self.assertEqual(real_result, result,
                        "Pattern '%s' %s '%s', matcher is %s" % (pattern, match_wish, text, matcher))

            def check(pattern, do_match, dont_match, ignore_case = True):
                check1(pattern, do_match,   True,  ignore_case)
                check1(pattern, dont_match, False, ignore_case)

            check("exact:abc", ["abc", "Abc", "aBC"], ["aabc", "abcc", "abcd"])
            check("exact:abc", ["abc", "Abc", "aBC"], ["aabc", "abcc", "abcd"], ignore_case = True)
            check("exact:abc", ["abc"], ["aabc", "abcc", "abcd", "Abc", "aBC"], ignore_case = False)

            check("exact:a*b*c", ["a*b*c", "A*b*c", "a*B*C"], ["a*a*b*c", "abcc", "ab*"])
            check("exact:a*b*c", ["a*b*c", "A*b*c", "a*B*C"], ["a*a*b*c", "abcc", "ab*"], ignore_case = True)
            check("exact:a*b*c", ["a*b*c"], ["a*a*b*c", "abcc", "abcd", "A*b*c", "a*B*C"], ignore_case = False)

            check("abc", ["abc", "Abc", "aBC"], ["aabc", "abcc", "abcd", "\nabc", "abc\n"])
            check("abc", ["abc", "Abc", "aBC"], ["aabc", "abcc", "abcd", "\nabc", "abc\n"], ignore_case = True)
            check("abc", ["abc"], ["aabc", "abcc", "abcd", "Abc", "aBC", "\nabc", "abc\n"], ignore_case = False)

            check("abc*", ["abc", "Abc", "aBC", "abcc", "abcd"], ["aabc", "*abc", "*abc*"])
            check("abc*", ["abc", "Abc", "aBC", "abcc", "abcd"], ["aabc", "*abc", "*abc*"], ignore_case = True)
            check("abc*", ["abc", "abcc", "abcd"], ["aabc", "Abc", "aBC", "*abc", "*abc*"], ignore_case = False)

            check("re:abc", ["abc", "Abc", "aBC", "abcc", "abcd", "*abc"], ["aa bc", "*ab*c"])
            check("re:abc", ["abc", "Abc", "aBC", "abcc", "abcd", "*abc"], ["aa bc", "*ab*c"], ignore_case = True)
            check("re:abc", ["abc", "aabc", "abcc", "abcd"], ["Abc", "aBC", "aa bc", "*ab*c"], ignore_case = False)

            check("re:^ab*c$", ["ac", "abc", "abBc", "ac\n"], ["aac", "bac", "acb", "\nac", "ac\nx"])
            check("re:^ab*c$", ["ac", "abc", "abBc", "ac\n"], ["aac", "bac", "acb", "\nac", "ac\nx"], ignore_case = True)
            check("re:^ab*c$", ["ac", "abc", "ac\n"], ["abBc", "aac", "bac", "acb", "\nac", "ac\nx"], ignore_case = False)

            check("re:\\Aab*c\\Z", ["ac", "abc", "abBc", "AbBbC"], ["aac", "bac", "acb", "\nac", "ac\n"])
            check("re:\\Aab*c\\Z", ["ac", "abc", "abBc", "AbBbC"], ["aac", "bac", "acb", "\nac", "ac\n"], ignore_case = True)
            check("re:\\Aab*c\\Z", ["ac", "abc"], ["abBc", "AbBbC", "aac", "bac", "acb", "\nac", "ac\n"], ignore_case = False)

            check("(?M(?:x))",     ["(?M(?:x))",  "(+M(-:x))" ], ["x", "xy", " (?M(?:x))", "(?M(?:x)) "])
            check("(?m)(?:^x)",    ["(?m)(?:^x)", "(-m)(+:^x)"], ["x", "xy", " (?M(?:x))", "(?M(?:x)) "])
            check("re:(?m)(?:^x)", ["xy", "abc\nx"], ["(?m)(?:^x)"])
            check("re:(?:^x)",     ["xy"],           ["abc\nx"]    )


### decide which main program to run

if __name__ == "__main__":
    if in_weechat:
        run_weechat()
    elif len(sys.argv) > 1:
        if sys.argv[1] == "--test":
            if have_unittest:
                del sys.argv[1]
                unittest.main()
            else:
                print "Package unittest not available. Please install it."
                exit(1)
        elif sys.argv[1] == "--debug":
            run_debug(sys.argv[2:])
        else:
            print "unrecognized first argument"
            exit(-1)
    else:
        #TODO print help
        print "Usage: run in WeeChat or pass `--test` argument"
