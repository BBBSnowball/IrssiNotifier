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


import sys, random, time, logging

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
logger.setLevel(logging.DEBUG)

if in_weechat:
    # log to weechat root buffer and don't propagate to default handler
    logger.propagate = False

    class WeeChatLogger(logging.Handler):
        def emit(self, record):
            text = self.format(record)
            weechat.prnt("", text)
    logger.addHandler(WeeChatLogger())


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


### WeeChat-specific subclasses

class ObjectRegistry(object):
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


### container subclasses

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


### helper filters

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


### some filters

class RegisteredNotificationFilter(NotificationFilter):
    """Abstract class. This filter has a short name that the user can use when building filters"""

    _registry = {}

    @classmethod
    def register(cls, name, filter):
        if name in cls._registry:
            raise ValueError("The name '%s' is already used for another NotificationFilter.")
        cls._registry[name] = filter
        # return filter class, so this can be used as a class decorator
        return filter

    @classmethod
    def has(cls, name):
        return name in cls._registry

    @classmethod
    def get(cls, name):
        return cls._registry[name]

    @classmethod
    def make_local_scope(cls):
        # a scope is just a dict, so we simply copy our registry
        return cls._registry.copy()

    @classmethod
    def eval_filter(cls, expr):
        return eval(expr, globals(), cls.make_local_scope())

def register(name):
    return lambda cls: RegisteredNotificationFilter.register(name, cls)

@register("blub")
class BlubNotificationFilter(RegisteredNotificationFilter):
    pass


del register


### other stuff

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

        def testRegisteredNotificationFilter(self):
            self.assertTrue(RegisteredNotificationFilter.has("blub"))
            self.assertTrue(not RegisteredNotificationFilter.has("unobtainium"))

            self.assertIs(RegisteredNotificationFilter.get("blub"), BlubNotificationFilter)

            self.assertIsInstance(RegisteredNotificationFilter.eval_filter("blub()"), BlubNotificationFilter)

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
