# Distributed under the terms of GPL version 2 or any later
# Copyright (C) Alexey Nezhdanov 2004
# Dialback module for xmppd.py

# $Id: dialback.py,v 1.1 2004-10-23 07:45:10 snakeru Exp $

from xmpp import *
from xmppd import *
import socket,thread,sha

class Dialback(PlugIn):
    """ 4. <db:result from= to= /> ->

        8.                db:verify ->
        9.                            <-  db:verify
        10.            <- db:result
        """
    NS=NS_DIALBACK
    def plugin(self,server):
        server.Dispatcher.RegisterHandler('result',self.dialbackHandler,xmlns=NS_DIALBACK)
        server.Dispatcher.RegisterHandler('verify',self.dialbackHandler,xmlns=NS_DIALBACK)
        server.Dispatcher.RegisterHandler('features',self.FeaturesHandler,xmlns=NS_STREAMS)
        self.waitlist={}

    def dialbackHandler(self,session,stanza):
        frm=stanza['from']
        to=stanza['to']
        name=stanza.getName()
        if to not in self._owner.servernames:
            self.DEBUG('Received dialback key for unknown server.','error')
            session.terminate_stream(STREAM_INVALID_ADDRESSING)
        elif not frm or frm<>frm.getDomain():
            self.DEBUG('Received dialback key from invalid server.','error')
            session.terminate_stream(STREAM_INVALID_ADDRESSING)
        elif name=='result' and session.TYP=='server':
            # (4) Received an dialback key. We should verify it.
            key=stanza.getData()
            self.DEBUG('Received dialback key %s (%s->%s).'%(`key`,frm,to),'info')
            # Now we should form a request and send it to authoritative server
            req=Node('db:verify',{'from':to,'to':frm,'id':session.ID},[key])
            s=self._owner.getsession(frm)
            if not s:
                s=self._owner.S2S(session.ourname,frm.getDomain())
            s.send(req)
            if self.waitlist.has_key(frm):
                self.waitlist[frm][1].terminate_stream(STREAM_CONFLICT)
            self.waitlist[frm]=(key,session)
        elif name=='verify' and session.TYP=='server':
            # (8) Received the dialback key for verification
            id=stanza['id']
            key=stanza.getData()
            self.DEBUG('Received dialback key %s for verification against id %s.'%(key,id),'info')
            if key.strip()==sha.new(id+self._owner.ID).hexdigest(): typ='valid'
            else: typ='invalid'
            rep=Node('db:verify',{'from':to,'to':frm,'id':id,'type':typ})
            session.send(rep)
        elif name=='verify' and session.TYP=='client':
            # (9) Received the verification reply
            self.DEBUG('Received verified dialback key for id %s (%s->%s). Result is: %s.'%(stanza['id'],frm,to,stanza['type']),'info')
            if self.waitlist.has_key(frm):
                key,s=self.waitlist[frm]
                if s.ID==stanza['id']:
                    rep=Node('db:result',{'from':to,'to':frm,'type':stanza['type']})
                    s.send(rep)
                    if stanza['type']<>'valid': s.terminate_stream(STREAM_NOT_AUTHORIZED)
                    else:
                        s.peer=frm
                        s.set_session_state(SESSION_AUTHED)
        elif name=='result' and session.TYP=='client':
            # (10) Received the result. Either we will be terminated now or authorized.
            if stanza['type']=='valid':
                session.set_session_state(SESSION_AUTHED)
                session.push_queue()
        raise NodeProcessed

    def __call__(self,session):
        # Server connected, send request
        key=sha.new(session.ID+self._owner.ID).hexdigest()
        req=Node('db:result',{'from':session.ourname,'to':session.peer},[key])
        session.send(req)

    def FeaturesHandler(self,session,stanza):
        if session._session_state>=SESSION_AUTHED: return     # already authed. do nothing
        if session.feature_in_process: return                 # another feature underway. Standby
        self(session)
