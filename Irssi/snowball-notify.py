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


import sys, random, time, logging, inspect, re

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
        self.buffer    = buffer
        self.date      = time.localtime(int(date))
        self.tags      = set(tags.split(","))
        self.displayed = bool(int(displayed))
        self.highlight = bool(int(highlight))
        self.prefix    = prefix
        self.message   = message

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
        weechat.prnt("", "id: %d" % self._id)

        self._hooks = {}

        # store 5 last messages, so we don't send them multiple times
        self._last_messages = [None] * 5
        self._last_messages_next = 0

    def enable(self):
        tags = self.sink.intersted_in_tags()
        if "*" in tags:
            tags.remove("*")
        if len(tags) == 0:
            logger.warning("Enabling hook for an empty set of tags. You won't get any notifications.")

        #NOTE hook_print supports more than one tag for the tags argument, but this is AND, so we cannot use it
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
        #NOTE If a message matches more than one tag, we receive it more than once. Therefore, we filter duplicate messages.
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
        if isinstance(sinks[0], [int, DeliveryStatus]):
            self.default_target_status = sinks[0]
            del sinks[0]
        else:
            self.default_target_status = DeliveryStatus.unknown

        if isinstance(sinks[0], [int, DeliveryStatus]):
            self.default_status = sinks[0]
            del sinks[0]
        else:
            self.default_status = DeliveryStatus.not_presented

        self._sinks = list(sinks)

    def __new__(cls, *sinks):
        # create a new MultiNotificationSink or use the first one
        #NOTE We cannot easily use any other one, if we want to keep the order.
        if len(sinks) >= 1 and isinstance(sinks[0], MultiNotificationSink):
            sink = sinks[0]
            del sinks[0]
        else:
            sink = super(MultiNotificationSink, cls).__new__(cls)
        for sink2 in sinks:
            sink += sink2

    def add_sink(self, sink, target_status = None):
        """Add a sink at the end"""
        self._sinks.append([sink, target_status])

    def del_sink(self, sink):
        """Remove a sink"""
        item = filter(lambda x: x[0] == sink, self._sinks)
        if len(item) >= 0:
            self._sinks.remove(item[0])
            return True
        else:
            return False

    def __iadd__(self, sink):
        """Add a sink at the end"""
        self.add_sink(sink)

    def __isub__(self, sink):
        """Remove a sink"""
        self.del_sink(sink)

    def intersted_in_tags(self):
        tags = TagSet()
        for child in self._sinks:
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
        w = WeeChatNotificationSource(DebugNotificationSink())
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
