##   filetransfer.py 
##
##   Copyright (C) 2004 Alexey "Snake" Nezhdanov
##
##   This program is free software; you can redistribute it and/or modify
##   it under the terms of the GNU General Public License as published by
##   the Free Software Foundation; either version 2, or (at your option)
##   any later version.
##
##   This program is distributed in the hope that it will be useful,
##   but WITHOUT ANY WARRANTY; without even the implied warranty of
##   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
##   GNU General Public License for more details.

# $Id$

from protocol import *
from dispatcher import NodeProcessed,PlugIn
import base64

NS_IBB        = "http://jabber.org/protocol/ibb"
NS_AMP        = "http://jabber.org/protocol/amp"

class IBB(PlugIn):
    def __init__(self):
        PlugIn.__init__(self)
        self.DBG_LINE='ibb'
        self._exported_methods=[self.OpenStream]
        self._streams={}
        self._ampnode=Node(NS_AMP+' amp',payload=[Node('rule',{'condition':'deliver-at','value':'stored','action':'error'}),Node('rule',{'condition':'match-resource','value':'exact','action':'error'})])

    def plugin(self,owner):
        self._owner.RegisterHandlerOnce('iq',self.StreamOpenReplyHandler) # Move to StreamOpen and specify stanza id
        self._owner.RegisterHandler('iq',self.IqHandler,ns=NS_IBB)
        self._owner.RegisterHandler('message',self.ReceiveHandler,ns=NS_IBB)

    def IqHandler(self,conn,stanza):
        typ=stanza.getType()
        if typ=='set' and stanza.getTag('open',namespace=NS_IBB): self.StreamOpenHandler(conn,stanza)
        elif typ=='set' and stanza.getTag('close',namespace=NS_IBB): self.StreamCloseHandler(conn,stanza)
        elif typ=='result': self.StreamCommitHandler(conn,stanza)
        elif typ=='error': self.StreamOpenReplyHandler(conn,stanza)
        else: conn.send(Error(stanza,ERR_BAD_REQUEST))
#        raise NodeProcessed

    def StreamOpenHandler(self,conn,stanza):
        """
<iq type='set' 
    from='romeo@montague.net/orchard'
    to='juliet@capulet.com/balcony'
    id='inband_1'>
  <open sid='mySID' 
        block-size='4096'
        xmlns='http://jabber.org/protocol/ibb'/>
</iq>
"""
        err=None
        sid,blocksize=stanza.getTagAttr('open','sid'),stanza.getTagAttr('open','block-size')
        try: blocksize=int(blocksize)
        except: err=ERR_BAD_REQUEST
        if not sid or not blocksize: err=ERR_BAD_REQUEST
        elif sid in self._streams.keys(): err=ERR_UNEXPECTED_REQUEST
        if err: rep=Error(stanza,err)
        else:
            self.DEBUG("Opening stream: id %s, block-size %s"%(sid,blocksize),'info')
            rep=Protocol('iq',stanza.getFrom(),'result',stanza.getTo(),{'id':stanza.getID()})
            self._streams[sid]={'direction':'<'+str(stanza.getFrom()),'block-size':blocksize,'data':'','seq':0,'syn_id':stanza.getID()}
        conn.send(rep)

    def OpenStream(self,sid,to,data,blocksize=4096):
        if sid in self._streams.keys(): return
        if not JID(to).getResource(): return
        self._streams[sid]={'direction':'|>'+to,'block-size':blocksize,'data':data,'seq':0}
        self._owner.RegisterCycleHandler(self.SendHandler)
        syn=Protocol('iq',to,'set',payload=[Node(NS_IBB+' open',{'sid':sid,'block-size':blocksize})])
        self._owner.send(syn)
        self._streams[sid]['syn_id']=syn.getID()
        return self._streams[sid]

    def SendHandler(self,conn):
        cont=0
        for sid in self._streams.keys():
            stream=self._streams[sid]
            if stream['direction'][:2]=='|>': cont=1
            elif stream['direction'][0]=='>':
                chunk=stream['data'][:stream['block-size']]
                stream['data']=stream['data'][stream['block-size']:]
                if chunk:
                    datanode=Node(NS_IBB+' data',{'sid':sid,'seq':stream['seq']},base64.encodestring(chunk))
                    stream['seq']+=1
                    if stream['seq']==65536: stream['seq']=0
                    conn.send(Protocol('message',stream['direction'][1:],payload=[datanode,self._ampnode]))
                if stream['data']: cont=1
                else:
                    """ ����� ��������� ����� ����������� ����� �� ��� �������
                        ����� �������� ���������� ������������ � ��� ��� ������ ������� ��������
                        ����� ������� ��������� �����"""
                    conn.send(Protocol('iq',stream['direction'][1:],'set',payload=[Node(NS_IBB+' close',{'sid':sid})]))
                    conn.Event(DBG_IBB,'SUCCESSFULL SEND',stream)
                    del self._streams[sid]

                    """
<message from='romeo@montague.net/orchard' to='juliet@capulet.com/balcony' id='msg1'>
  <data xmlns='http://jabber.org/protocol/ibb' sid='mySID' seq='0'>
    qANQR1DBwU4DX7jmYZnncmUQB/9KuKBddzQH+tZ1ZywKK0yHKnq57kWq+RFtQdCJ
    WpdWpR0uQsuJe7+vh3NWn59/gTc5MDlX8dS9p0ovStmNcyLhxVgmqS8ZKhsblVeu
    IpQ0JgavABqibJolc3BKrVtVV1igKiX/N7Pi8RtY1K18toaMDhdEfhBRzO/XB0+P
    AQhYlRjNacGcslkhXqNjK5Va4tuOAPy2n1Q8UUrHbUd0g+xJ9Bm0G0LZXyvCWyKH
    kuNEHFQiLuCY6Iv0myq6iX6tjuHehZlFSh80b5BVV9tNLwNR5Eqz1klxMhoghJOA
  </data>
  <amp xmlns='http://jabber.org/protocol/amp'>
    <rule condition='deliver-at' value='stored' action='error'/>
    <rule condition='match-resource' value='exact' action='error'/>
  </amp>
</message>
"""
        if not cont: self._owner.UnregisterCycleHandler(self.SendHandler)

    def ReceiveHandler(self,conn,stanza):
        sid,seq,data=stanza.getTagAttr('data','sid'),stanza.getTagAttr('data','seq'),stanza.getTagData('data')
        try: seq=int(seq); data=base64.decodestring(data)
        except: seq=''; data=''
        err=None
        if not sid in self._streams.keys(): err=ERR_ITEM_NOT_FOUND
        else:
            stream=self._streams[sid]
            if not data: err=ERR_BAD_REQUEST
            elif seq<>stream['seq']: err=ERR_UNEXPECTED_REQUEST
            else:
                stream['seq']+=1
                stream['data']+=data
        if err: conn.send(Error(Iq(to=stanza.getFrom(),frm=stanza.getTo(),payload=[Node(NS_IBB+' close')]),err,reply=0))

    def StreamCloseHandler(self,conn,stanza):
        sid=stanza.getTagAttr('close','sid')
        if sid in self._streams.keys():
            conn.send(stanza.buildReply('result'))
            conn.Event(DBG_IBB,'SUCCESSFULL RECEIVE',self._streams[sid])
            del self._streams[sid]
        else: conn.send(Error(stanza,ERR_ITEM_NOT_FOUND))

    def StreamBrokenHandler(self,conn,stanza):
        syn_id=stanza.getID()
        for sid in self._streams.keys():
            stream=self._streams[sid]
            if stream['syn_id']==syn_id:
                if stream['direction'][0]=='<': conn.Event(DBG_IBB,'ERROR ON RECEIVE',stream)
                else: conn.Event(DBG_IBB,'ERROR ON SEND',stream)
                del self._streams[sid]

    def StreamOpenReplyHandler(self,conn,stanza):
        syn_id=stanza.getID()
        for sid in self._streams.keys():
            stream=self._streams[sid]
            if stream['syn_id']==syn_id:
                if stanza.getType()=='error':
                    if stream['direction'][0]=='<': conn.Event(DBG_IBB,'ERROR ON RECEIVE',stream)
                    else: conn.Event(DBG_IBB,'ERROR ON SEND',stream)
                    del self._streams[sid]
                elif stanza.getType()=='result':
                    if stream['direction'][0]=='|':
                        stream['direction']=stream['direction'][1:]
                        conn.Event(DBG_IBB,'STREAM COMMITTED',stream)
                    else: conn.send(Error(stanza,ERR_UNEXPECTED_REQUEST))
