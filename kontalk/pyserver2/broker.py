# -*- coding: utf-8 -*-
'''The Message Broker Service.'''
'''
  Kontalk pyserver2
  Copyright (C) 2011 Kontalk Devteam <devteam@kontalk.org>

 This program is free software: you can redistribute it and/or modify
 it under the terms of the GNU General Public License as published by
 the Free Software Foundation, either version 3 of the License, or
 (at your option) any later version.

 This program is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 GNU General Public License for more details.

 You should have received a copy of the GNU General Public License
 along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

import os, socket, time
from Queue import Queue
import pickle, shelve

from twisted.application import internet, service
from twisted.internet.defer import Deferred

# local imports
from broker_twisted import *
import version
import kontalk.config as config
from kontalklib import database, utils, token, txprotobuf
from kontalklib.utils import PersistentDict
from txrdq import ResizableDispatchQueue, PersistentDispatchQueue


class C2SChannel:
    '''Client channel implementation.'''

    userid = None

    def __init__(self, protocol, broker):
        self.protocol = protocol
        self.broker = broker

    def connected(self):
        # TODO
        print "connected!"

    def disconnected(self):
        print "disconnected."
        if self.userid:
            self.broker.unregister_user_consumer(self.userid)

    def authenticate(self, tx_id, auth_token):
        '''Client tried to authenticate.'''
        print "[%s] authenticating token: %s" % (tx_id, auth_token)
        userid = token.verify_user_token(auth_token, self.broker.db.servers(), config.config['server']['fingerprint'])
        if userid:
            print "[%s] user %s logged in." % (tx_id, userid)
            self.userid = userid
            self.broker.register_user_consumer(userid, self._incoming)
            return True

        return False

    def post_message(self, tx_id, recipient = None, mime = None, flags = None, content = None):
        '''User posted a message.'''
        # TODO
        print "[%s] posting message for: %s (mime=%s, flags=%s)" % \
            (tx_id, str(recipient), mime, str(flags))
        # TODO
        for rcpt in recipient:
            self.broker.publish_user(self.userid, str(rcpt), [str(mime), flags, content], True)

    def _incoming(self, data, unused = None):
        '''Internal queue worker.'''
        # TODO
        print "incoming message:", data
        a = NewMessage()
        a.message_id = data['messageid']
        a.sender = data['sender']
        a.mime = 'undefined'
        a.encrypted = False
        a.content = 'AOOAOAOAOAO'
        self.protocol.sendBox(a)


class S2SChannel:
    '''Server channel implementation.'''
    # TODO
    # TODO
    # TODO

    fingerprint = None

    def __init__(self, protocol, broker):
        self.protocol = protocol
        self.broker = broker

    def connected(self):
        # TODO
        print "connected!"

    def disconnected(self):
        print "disconnected."
        if self.fingerprint:
            self.broker.unregister_server_queue(self.fingerprint)

    """
    TODO
    def handshake(self, tx_id, auth_token):
        print "authenticating token: %s" % auth_token
        userid = token.verify_user_token(auth_token, self.broker.db.servers(), config.config['server']['fingerprint'])
        if userid:
            print "user %s logged in." % userid
            self.userid = userid
            self.broker.register_user_queue(userid, self._incoming)
            return True

        return False
    """

    def _incoming(self, data):
        # TODO
        print "incoming message:", data


class MessageStorage:
    '''Map of mailbox storages.'''
    _mboxes = {}

    def __init__(self, path):
        self._path = path

    def get_storage(self, uid, flag = 'c', force = False, cache = True):
        if uid not in self._mboxes or force:
            try:
                os.makedirs(self._path)
            except:
                pass
            db = PersistentDict(os.path.join(self._path, uid + '.mbox'), flag)
            if not cache:
                return db
            self._mboxes[uid] = db
        return self._mboxes[uid]

    def load(self, uid):
        try:
            return self.get_storage(uid, 'r', True, False)
        except:
            return None

    def store(self, uid, msg, force = False):
        '''Used to persist a message.'''
        db = self.get_storage(uid)
        print "storing message %s to disk" % msg['messageid']
        if msg['messageid'] not in db or force:
            db[msg['messageid']] = msg
            db.sync()

    def deliver(self, userid, msg, force = False):
        '''Used to persist a message that was intended to a generic userid.'''

        # store the new message
        db = self.get_storage(userid)
        if msg['messageid'] not in db or force:
            db[msg['messageid']] = msg
            db.sync()

        # delete the old message in the generic user mbox
        db = self.get_storage(userid[:utils.USERID_LENGTH])
        try:
            del db[msg['originalid']]
            db.sync()
        except:
            import traceback
            traceback.print_exc()


class MessageBroker:
    '''Message broker connection manager.'''

    '''Map of the queue consumers.
    Queues in this map will contain the collection of workers for specific userids.'''
    _consumers = {}
    '''The messages storage.'''
    _storage = MessageStorage(config.config['broker']['storage_path'])

    def __init__(self, application):
        self.application = application

    def setup(self):
        # estabilish a connection to the database
        self.db = database.connect_config(config.config)
        self.servers = self.db.servers()

        # create listening service for clients
        factory = InternalServerFactory(C2SServerProtocol, C2SChannel, self)
        service = internet.TCPServer(port=config.config['server']['c2s.bind'][1],
            factory=factory, interface=config.config['server']['c2s.bind'][0])
        service.setServiceParent(self.application)

        # create listening service for servers
        factory = InternalServerFactory(S2SServerProtocol, S2SChannel, self)
        service = internet.TCPServer(port=config.config['server']['s2s.bind'][1],
            factory=factory, interface=config.config['server']['s2s.bind'][0])
        service.setServiceParent(self.application)

    def _usermsg_worker(self, msg):
        userid = msg['userid']
        need_ack = msg['need_ack']
        #print "queue data for user %s (need_ack=%s)" % (userid, need_ack)

        # generic user, post to every consumer
        if len(userid) == utils.USERID_LENGTH:
            try:
                for resource, q in self._consumers[userid].iteritems():
                    outmsg = dict(msg)
                    # branch the message :)
                    outmsg['messageid'] = self.message_id()
                    outmsg['originalid'] = msg['messageid']
                    outmsg['userid'] += resource

                    # store to disk (if need_ack)
                    if need_ack:
                        try:
                            #print "storing message %s to disk" % outmsg['messageid']
                            self._storage.deliver(outmsg['userid'], outmsg)
                        except:
                            # TODO handle errors
                            import traceback
                            traceback.print_exc()

                    # send to client listener
                    q.put(outmsg)

            except:
                print "warning: no listener to deliver message!"
                # store to temporary spool
                self._storage.store(userid, msg)

        elif len(userid) == utils.USERID_LENGTH_RESOURCE:
            uhash, resource = self.split_userid(userid)

            # store to disk (if need_ack)
            if need_ack:
                try:
                    #print "storing message %s to disk" % msg['messageid']
                    self._storage.store(userid, msg)
                except:
                    # TODO handle errors
                    import traceback
                    traceback.print_exc()

            try:
                # send to client consumer
                self._consumers[uhash][resource].put(msg)
            except:
                print "warning: no listener to deliver message to resource %s!" % resource

        else:
            print "warning: unknown userid format %s" % userid

    def register_user_consumer(self, userid, worker):
        uhash, resource = self.split_userid(userid)

        try:
            # stop previous queue if any
            self._consumers[uhash][resource].stop()
        except:
            pass

        if uhash not in self._consumers:
            self._consumers[uhash] = {}

        self._consumers[uhash][resource] = ResizableDispatchQueue(worker)
        self._consumers[uhash][resource].start(5)

        """
        WARNING these two need to be called in this order!!!
        Otherwise bad things happen...
        """
        # load previously stored messages (for specific) and requeue them
        self._reload_usermsg_queue(userid)
        # load previously stored messages (for generic) and requeue them
        self._reload_usermsg_queue(uhash)

    def unregister_user_consumer(self, userid):
        uhash, resource = self.split_userid(userid)

        try:
            # stop previous queue if any
            self._consumers[uhash][resource].stop()
            del self._consumers[uhash][resource]
            if len(self._consumers[uhash]) == 0:
                del self._consumers[uhash]
        except:
            import traceback
            traceback.print_exc()

    def split_userid(self, userid):
        return userid[:utils.USERID_LENGTH], userid[utils.USERID_LENGTH:]

    def message_id(self):
        return utils.rand_str(30)

    def _reload_usermsg_queue(self, uid):
        stored = dict(self._storage.load(uid))
        if stored:
            # requeue messages
            for msgid, msg in stored.iteritems():
                self._usermsg_worker(msg)

    def publish_user(self, sender, userid, msg, need_ack = False):
        '''Publish a message to a user, either generic or specific.'''

        if len(userid) == utils.USERID_LENGTH:
            uhash, resource = userid, None
        elif len(userid) == utils.USERID_LENGTH_RESOURCE:
            uhash, resource = self.split_userid(userid)
        else:
            print "invalid userid format: %s" % userid
            # TODO should we throw an exception here?
            return None

        # prepare message dict
        msg_id = self.message_id()
        outmsg = {
            'messageid' : msg_id,
            'sender' : sender,
            'userid' : userid,
            'timestamp' : time.time(),
            'need_ack' : need_ack,
            'payload' : msg
        }

        # process message immediately
        self._usermsg_worker(outmsg)

        return msg_id
