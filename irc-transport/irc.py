#!/usr/bin/python
# $Id$
#
# xmpp->IRC transport
# Jan 2004 Copyright (c) Mike Albon
#
# This program is free software licensed with the GNU Public License Version 2.
# For a full copy of the license please go here http://www.gnu.org/licenses/licenses.html#GPL

import xmpp, urllib2, sys, time, irclib, re, ConfigParser, os, select
#from threading import *
from xmpp.protocol import *

#import IPython.ultraTB
#sys.excepthook = IPython.ultraTB.FormattedTB(mode='Verbose', color_schme="Linux", call_pdb=0)


#Global definitions
True = 1
False = 0
server = None
hostname = None
port = None
secret = None
localaddress = ""
connection = None
charset = 'utf-8'
#server = '127.0.0.1'
#hostname = 'irc.localhost'
#port = 9000
#secret = 'secret'
socketlist = {}

MALFORMED_JID=ErrorNode(ERR_JID_MALFORMED,text='Invalid JID, must be in form #room%server@transport')

def irc_add_conn(con):
    socketlist[con]='irc'
    
def irc_del_conn(con):
    #print "Have:" ,socketlist
    #print "Deleting:", con
    del socketlist[con]
    #print "Now have:", socketlist

#def irclib.irc_lower(nick):
#    nick=nick.lower()
#    nick=nick.replace'[','{').replace(']','}')
    #nick=nick.replace('\\','|')
    #return nick

def colourparse(str):
    # Each tuple consists of String, foreground, background, bold.
    foreground=None
    background=None
    bold=None
    s = ''
    html=[]
    hs = ''
    ctrseq=None
    ctrfor=None #Has forground been processed?
    for e in str:
        if e == '\x00':
            pass #'Black'
        elif e == '\x01':   
            pass #'Blue' CtCP Code
        elif e == '\x02':#'Green' Also Bold
            html.append((hs,foreground,background,bold))
            if bold == True:
                bold = None
            else:
                bold = True
            hs = ''
        elif e == '\x03':#'Cyan' Also Colour
            html.append((hs,foreground,background,bold))
            foreground = None
            #background = None
            if not ctrseq:
                ctrseq = True
            hs = ''
        elif e == '\x04':
            print 'Red'
        elif e == '\x05':
            print 'Purple'
        elif e == '\x06':
            print 'Brown'
        elif e == '\x07':
            print "Light Grey"
        elif e == '\x08':
            print 'Grey'
        elif e == '\x09':
            print 'Light Blue'
        elif e == '\x0a':
            print 'Light Green'
        elif e == '\x0b':
            print 'Light Cyan'
        elif e == '\x0c':
            print 'Light Red'
        elif e == '\x0d':
            print 'Pink'
        elif e == '\x0e':
            print 'Yellow'
        elif e == '\x0f':
            print 'White'
        elif e in ['\x10', '\x11', '\x12', '\x13', '\x14', '\x15', '\x16', '\x17', '\x18', '\x19', '\x1a', '\x1b', '\x1c', '\x1d', '\x1e', '\x1f']:
            print 'Other Escape'
        elif ctrseq == True:
            if e.isdigit():
                if not ctrfor:
                    try:
                        if not foreground.len() <2:
                            foreground = foreground +e
                        else:
                            ctrseq=None
                            foreground = int(foreground)
                            s = '%s%s'%(s,e)
                            hs = '%s%s'%(hs,e)
                    except AttributeError:   
                        foreground = e
                else:
                    try:
                        if background.len() <=2:
                            foreground = foreground +e
                        else:
                            ctrseq=None
                            ctrfor=None 
                            background = int(background)
                            s = '%s%s'%(s,e)
                            hs= '%s%s'%(hs,e)
                    except AttributeError:   
                        background = e
            elif e == ',':
                ctrfor=True
                background = None
            else:
                ctrfor = None
                ctrseq = None
                s = '%s%s'%(s,e)
                hs = '%s%s'%(hs,e)
        else:
            s = '%s%s'%(s,e)
            hs = '%s%s'%(hs,e)
    try:
        s = unicode(s,'utf8','strict') # Language detection stuff should go here.
    except:
        s = unicode(s, charset)
    return s
  
  
def connectxmpp():
    global connection
    connection = None
    connection = xmpp.client.Component(hostname,port)
    while not connection.connect((server,port)):
        time.sleep(10)
    if connection.auth(hostname,secret):
        socketlist[connection.Connection._sock]='xmpp'
        return True
    else:
        return False
        

class IrcThread(Thread):
    def __init__(self,irc):
        Thread.__init__(self)
        self.irc = irc
        self.start()
        
    def run(self):
        while 1:
            try:
                self.irc.process_forever()
            except:
                pass
    
class ComponentThread(Thread):
    def __init__(self,connection):
        Thread.__init__(self)
        self.connection = connection
        self.start()
        
    def run(self):
        while 1:
            try:
                self.connection.Process(5)
            except:
                pass
    
class Transport:
    # This class is the main collection of where all the handlers for both the IRC and Jabber
    
    #Global structures
    users = {}
    #This structure consists of each user of the transport having their own location of store.
    #The store per jid is then devided into two sections.
    #The first is the room and server for each room in use, used for directing messages, iq and subsiquent presence traffic
    #The second is used when adding channels in use. This will identify the servers and nick's in use.
    #Contrary to the above the new structure is dictionary of fromjid and a dictionary of servers connected.
    #All other information is stored in the connection.
    
    # Parameter order. Connection then options.
    
    def __init__(self,jabber,irc):
        self.jabber = jabber
        self.irc = irc
        self.register_handlers()
    
    def register_handlers(self):
        self.irc.add_global_handler('motd',self.irc_message)
        self.irc.add_global_handler('pubmsg',self.irc_message)
        self.irc.add_global_handler('pubnotice',self.irc_message)        
        self.irc.add_global_handler('privmsg',self.irc_message)
        self.irc.add_global_handler('privnotice',self.irc_message)
        self.irc.add_global_handler('whoreply',self.irc_whoreply)
        self.irc.add_global_handler('ctcp',self.irc_ctcp)
        self.irc.add_global_handler('nick',self.irc_nick)
        self.irc.add_global_handler('join',self.irc_join)
        self.irc.add_global_handler('part',self.irc_part)
        self.irc.add_global_handler('quit',self.irc_quit)
        self.irc.add_global_handler('kick',self.irc_kick)
        self.irc.add_global_handler('mode',self.irc_chanmode)
        self.irc.add_global_handler('error',self.irc_error)
        self.irc.add_global_handler('topic',self.irc_topic)
        self.irc.add_global_handler('nicknameinuse',self.irc_nicknameinuse)
        self.irc.add_global_handler('nosuchchannel',self.irc_nosuchchannel)
        self.irc.add_global_handler('notregistered',self.irc_notregistered)
        self.irc.add_global_handler('welcome',self.irc_welcome)
        self.jabber.RegisterHandler('message',self.xmpp_message)
        self.jabber.RegisterHandler('presence',self.xmpp_presence)
        self.jabber.RegisterHandler('iq',self.xmpp_iq_discoinfo,typ = 'get', ns='http://jabber.org/protocol/disco#info')
        self.jabber.RegisterHandler('iq',self.xmpp_iq_discoitems,typ = 'get', ns='http://jabber.org/protocol/disco#items')
        self.jabber.RegisterHandler('iq',self.xmpp_iq_version,typ = 'get', ns='jabber:iq:version')
        self.jabber.RegisterHandler('iq',self.xmpp_iq_agents,typ = 'get', ns='jabber:iq:agent')
        self.jabber.RegisterHandler('iq',self.xmpp_iq_browse,typ = 'get', ns='jabber:iq:browse')
        self.jabber.RegisterHandler('iq',self.xmpp_iq_mucadmin_set,typ = 'set', ns='http://jabber.org/protocol/muc#admin')
        self.jabber.RegisterHandler('iq',self.xmpp_iq_mucadmin_get,typ = 'get', ns='http://jabber.org/protocol/muc#admin')
        self.jabber.RegisterDisconnectHandler(self.xmpp_disconnect)
    #XMPP Handlers
    def xmpp_presence(self, con, event):
        # Add ACL support
        fromjid = event.getFrom().getStripped()
        type = event.getType()
        if type == None: type = 'available'
        to = event.getTo()
        room = to.getNode().lower()
        nick = to.getResource()
        try:
            channel, server = room.split('%')
        except ValueError:
            channel=''
        if not irclib.is_channel(channel):
            self.jabber.send(Error(event,MALFORMED_JID))
            return
        if type == 'available':
            #print nick
            if nick != '':
                if not self.users.has_key(fromjid): # if a new user session
                    c=self.irc_newconn(channel,server,nick,fromjid)
                    if c != None:
                        self.users[fromjid] = {server:c}
                else:
                    if self.users[fromjid].has_key(server):
                        if self.users[fromjid][server].memberlist.has_key(channel):
                            pass # This is the nickname change case -- need to do something with this.
                        elif self.users[fromjid].has_key(server): # if user already has a session open on same server
                            self.irc_newroom(self.users[fromjid][server],channel)
                    else: # the other cases
                        c=self.irc_newconn(channel,server,nick,fromjid)
                        if c != None:
                            self.users[fromjid][server]=c
        elif type == 'unavailable':
            if self.users.has_key(fromjid):
                if self.users[fromjid].has_key(server):
                    if self.users[fromjid][server].memberlist.has_key(channel):
                        connection = self.users[fromjid][server]
                        self.irc_leaveroom(connection,channel)
                        del self.users[fromjid][server].memberlist[channel]
                        #del self.users[fromjid][0][(channel,server)]
                        #need to add server connection tidying
                        self.test_inuse(connection)
        else:
            self.jabber.send(Error(event,ERR_FEATURE_NOT_IMPLEMENTED))
            
    def test_inuse(self,connection):
        inuse = False
        for each in self.users[connection.fromjid].keys():
            if self.users[connection.fromjid][each].memberlist != {}:
                inuse = True
        if inuse == False:
            self.irc_doquit(connection)
                    
    def xmpp_message(self, con, event):
        type = event.getType()
        fromjid = event.getFrom().getStripped()
        to = event.getTo()
        room = to.getNode().lower()
        try:
            channel, server = room.split('%')
        except ValueError:
            self.jabber.send(Error(event,MALFORMED_JID))
            return
        if not self.users.has_key(fromjid):
            self.jabber.send(Error(event,ERR_REGISTRATION_REQUIRED))         # another candidate: ERR_SUBSCRIPTION_REQUIRED
            return
        if not self.users[fromjid].has_key(server):
            self.jabber.send(Error(event,ERR_ITEM_NOT_FOUND))        # Another candidate: ERR_REMOTE_SERVER_NOT_FOUND (but it means that server doesn't exist at all)
            return
        #print channel, server, fromjid, self.users[fromjid][0][(channel,server)]
        if type == 'groupchat':
            if irclib.is_channel(channel):
                if event.getSubject():
                    if (self.users[fromjid][server].chanmodes['topic']==True and self.users[fromjid][server].memberlist[self.users[fromjid][server].nickname]['role'] == 'moderator') or self.users[fromjid][server].chanmodes['topic']==False:
                        self.irc_settopic(self.users[fromjid][server],channel,event.getSubject())
                    else:
                        self.jabber.send(Error(event,ERR_FORBIDDEN))
                elif event.getBody() != '':
                    if event.getBody()[0:3] == '/me':
                        self.irc_sendctcp('ACTION',self.users[fromjid][server],channel,event.getBody()[4:])
                    else:
                        self.irc_sendroom(self.users[fromjid][server],channel,event.getBody()) 
                    t = Message(to=fromjid,body=event.getBody(),typ=type,frm='%s@%s/%s' %(room, hostname,self.users[fromjid][server].nickname))
                    self.jabber.send(t)
            else:
                self.jabber.send(Error(event,ERR_ITEM_NOT_FOUND))  # or ERR_JID_MALFORMED maybe?
        elif type in ['chat', None]:
            if not irclib.is_channel(channel):
                # ARGH! need to know channel to find out nick. :(
                if event.getBody()[0:3] == '/me':
                    self.irc_sendctcp('ACTION',self.users[fromjid][server],channel,event.getBody()[4:])
                else:
                    self.irc_sendroom(self.users[fromjid][server],channel,event.getBody())
            else:
                if event.getBody()[0:3] == '/me':
                    self.irc_sendctcp('ACTION',self.users[fromjid][server],channel,event.getBody()[4:])
                else:
                    self.irc_sendroom(self.users[fromjid][server],event.getTo().getResource(),event.getBody())
                
    def xmpp_iq_discoinfo(self, con, event):
        fromjid = event.getFrom()
        to = event.getTo()
        id = event.getID()
        m = Iq(to=fromjid,frm=to, typ='result', queryNS='http://jabber.org/protocol/disco#info', payload=[Node('identity',attrs={'category':'conference','type':'irc','name':'IRC Transport'}),Node('feature',attrs={'var':'http://jabber.org/protocol/muc'})])
        m.setID(id)
        self.jabber.send(m)
        #raise xmpp.NodeProcessed
        
    def xmpp_iq_discoitems(self, con, event):
        fromjid = event.getFrom()
        to = event.getTo()
        id = event.getID()
        m = Iq(to=fromjid,frm=to, typ='result', queryNS='http://jabber.org/protocol/disco#items')
        m.setID(id)
        self.jabber.send(m)
        #raise xmpp.NodeProcessed
    
    def xmpp_iq_agents(self, con, event):
        m = Iq(to=event.getFrom(), frm=event.getTo(), typ='result', payload=[Node('agent', attrs={'jid':hostname},payload=[Node('service',payload='irc'),Node('name',payload='xmpp IRC Transport'),Node('groupchat')])])
        m.setID(event.getID())
        self.jabber.send(m)
        #raise xmpp.NodeProcessed
    
    def xmpp_iq_browse(self, con, event):
        m = Iq(to = event.getFrom(), frm = event.getTo(), typ = 'result', queryNS = 'jabber:iq:browse')
        if event.getTo() == hostname:
            m.setTagAttr('query','catagory','conference')
            m.setTagAttr('query','name','xmpp IRC Transport')
            m.setTagAttr('query','type','irc')
            m.setTagAttr('query','jid','hostname')
            m.setPayload([Node('ns',payload='http://jabber.org/protcol/muc')])
        self.jabber.send(m)
        #raise xmpp.NodeProcessed
    
    def xmpp_iq_version(self, con, event):
        fromjid = event.getFrom()
        to = event.getTo()
        id = event.getID()
        m = Iq(to = fromjid, frm = to, typ = 'result', queryNS= 'jabber:iq:version',payload=[Node('name',payload='xmpp IRC Transport'), Node('version',payload='early release 12feb04'),Node('os',payload='%s %s %s' % (os.uname()[0],os.uname()[2],os.uname()[4]))])
        m.setID(id)
        self.jabber.send(m)
        #raise xmpp.NodeProcessed
    
    def xmpp_disconnect(self):
        for each in self.users.keys():
            for item in self.users[each].keys():
                self.irc_doquit(item)
            del self.users[each]
        #del connection    
        del socketlist[connection.Connection._sock]
        while not connectxmpp():
            time.sleep(5)
        self.register_handlers()
            
    def xmpp_iq_mucadmin_get(self, con, event):
        fromjid = event.getFrom()
        to = event.getTo()
        room = to.getNode().lower()
        id = event.getID()
        try:
            channel, server = room.split('%')
        except ValueError:
            self.jabber.send(Error(event,MALFORMED_JID))
            return
        if fromjid not in self.users.keys() \
          or server not in self.users[fromjid].keys() \
          or channel not in self.users[fromjid][server].memberlist.keys():
            self.jabber.send(Error(event,ERR_ITEM_NOT_FOUND))
            return
        ns = event.getQueryNS()
        t = event.getQueryPayload()
        if t[0].getName() == 'item':
            attr = t[0].getAttrs()
            if 'role' in attr.keys():
                role = attr['role']
                affiliation = None
            elif 'affiliation' in attr.keys():
                affiliation = attr['affiliation']
                role = None
        m = Iq(to= fromjid, frm=to, typ='result', queryNS=ns)
        payload = []
        for each in self.users[fromjid][server].memberlist[channel]:
            if role != None:
                if self.users[fromjid][server].memberlist[channel][each]['role']  == role:
                    zattr = self.users[fromjid][server].memberlist[channel][each]
                    zattr['nick'] = each
                    payload.append(Node('item',attrs = zattr))
            if affiliation != None:
                if self.users[fromjid][server].memberlist[channel][each]['affiliation']  == affiliation:
                    zattr = self.users[fromjid][server].memberlist[channel][each]
                    zattr['nick'] = each
                    payload.append(Node('item',attrs = zattr))
        m.setQueryPayload(payload)
        self.jabber.send(m)

    def xmpp_iq_mucadmin_set(self, con, event):
        fromjid = event.getFrom()
        to = event.getTo()
        room = to.getNode().lower()
        id = event.getID()
        try:
            channel, server = room.split('%')
        except ValueError:
            self.jabber.send(Error(event,MALFORMED_JID))
            return
        if fromjid not in self.users.keys() \
          or server not in self.users[fromjid].keys() \
          or channel not in self.users[fromjid][server].memberlist.keys():
            self.jabber.send(Error(event,ERR_ITEM_NOT_FOUND))
            return
        ns = event.getQueryNS()
        t = event.getQueryPayload()
        if self.users[fromjid][server].memberlist[self.users[fromjid][server].nick]['role'] != 'moderator' or self.users[fromjid][server].memberlist[self.users[fromjid][server].nick]['affiliation'] != 'owner':
            self.jabber.send(Error(event,ERR_FORBIDDEN))
            return
        for each in t:
            if t[0].getName() == 'item':
                attr = t[0].getAttrs()
                if attr.has_key('role'):
                    if attr['role'] == 'moderator':
                        self.users[fromjid][server].mode(channel,'%s %s'%('+o',attr['nick']))    
                    elif attr['role'] == 'participant':
                        self.users[fromjid][server].mode(channel,'%s %s'%('+v',attr['nick']))
                    elif attr['role'] == 'visitor':
                        self.users[fromjid][server].mode(channel,'%s %s'%('-v',attr['nick']))
                        self.users[fromjid][server].mode(channel,'%s %s'%('-o',attr['nick']))
                    elif attr['role'] == 'none':
                        self.users[fromjid][server].kick(channel,attr['nick'],'Kicked')#Need to add reason gathering
                        
                        
                    #IRC methods
    def irc_doquit(self,connection):
        server = connection.server
        nickname = connection.nickname
        del self.users[connection.fromjid][server]
        connection.close()
        
    def irc_settopic(self,connection,channel,line):
        connection.topic(channel.encode(charset),line.encode(charset))
    
    def irc_sendroom(self,connection,channel,line):
        lines = line.split('/n')
        for each in lines:
            #print channel, each
            connection.privmsg(channel.encode(charset),each.encode(charset))

    def irc_sendctcp(self,type,connection,channel,line):
        lines = line.split('/n')
        for each in lines:
            #print channel, each
            connection.ctcp(type,channel.encode(charset),each.encode(charset))

    def irc_newconn(self,channel,server,nick,fromjid):
        try:
            c=self.irc.server().connect(server,6667,nick,localaddress=localaddress)
            c.fromjid = fromjid
            c.joinchan = channel
            c.memberlist = {}
            c.chanmode = {}
            #c.join(channel)
            #c.who(channel) 
            return c
        except irclib.ServerConnectionError:
            self.jabber.send(Error(Presence(to = fromjid, frm = '%s%%%s@%s/%s' % (channel,server,hostname,nick)),ERR_SERVICE_UNAVAILABLE,reply=0))  # Other candidates: ERR_GONE, ERR_REMOTE_SERVER_NOT_FOUND, ERR_REMOTE_SERVER_TIMEOUT
            return None
            
    def irc_newroom(self,conn,channel):
        conn.join(channel)
        conn.who(channel)
        #conn.topic(channel)
        conn.memberlist[channel] = {}
        conn.chanmode[channel] = {'private':False, 'secret':False, 'invite':False, 'topic':False, 'notmember':False, 'moderated':False, 'banlist':[], 'limit':False, 'key':''}

    def irc_leaveroom(self,conn,channel):
        conn.part([channel])
    
    # IRC message handlers

    def irc_error(self,conn,event):
        #conn.close()
        if conn.server in self.users[conn.fromjid].keys():
            try:
                for each in conn.memberlist.keys():
                    t = Presence(to=conn.fromjid, typ = 'unavailable', frm='%s%%%s@%s' %(each,conn.server,hostname))
                    self.jabber.send(t)
                del self.users[conn.fromjid][conn.server]
            except AttributeError:
                pass    
    
    def irc_quit(self,conn,event):
        type = 'unavailable'
        nick = irclib.nm_to_n(event.source())
        for each in conn.memberlist.keys():
            if nick in conn.memberlist[each].keys():
                del conn.memberlist[each][nick]
                name = '%s%%%s' % (each, conn.server)
                m = Presence(to=conn.fromjid,typ=type,frm='%s@%s/%s' %(name, hostname,event.source().split('!')[0]))
                self.jabber.send(m)
    
    def irc_nick(self, conn, event):
        old = irclib.nm_to_n(event.source())
        new = event.target()
        for each in conn.memberlist.keys():
            if old in conn.memberlist[each].keys():
                m = Presence(to=conn.fromjid,typ = 'unavailable',frm = '%s%%%s@%s/%s' % (each,conn.server,hostname,old))
                p = m.addChild(name='x', namespace='http://jabber.org/protocol/muc#user')
                p.addChild(name='item', attrs={'nick':new})
                p.addChild(name='status', attrs={'code':'303'})
                self.jabber.send(m)
                m = Presence(to=conn.fromjid,typ = 'available', frm = '%s%%%s@%s/%s' % (each,conn.server,hostname,new))
                self.jabber.send(m)
                t=conn.memberlist[each][old]
                del conn.memberlist[each][old]
                conn.memberlist[each][new] = t
                

    def irc_welcome(self,conn,event):
        self.irc_newroom(conn,conn.joinchan)
        del conn.joinchan
    
    def irc_nicknameinuse(self,conn,event):
        if conn.joinchan:
            error=ErrorNode(ERR_CONFLICT,text='Nickname is in use')
            self.jabber.send(Error(Presence(to=conn.fromjid, typ = 'error', frm = '%s%%%s@%s' %(conn.joinchan, conn.server, hostname)),error,reply=0))
            
    def irc_nosuchchannel(self,conn,event):
        error=ErrorNode(ERR_ITEM_NOT_FOUND,'The channel is not found')
        self.jabber.send(Presence(to=conn.fromjid, typ = 'error', frm = '%s%%%s@%s' %(event.arguments()[0], conn.server, hostname)),error,reply=0)

    def irc_notregistered(self,conn,event):
        error=ErrorNode(ERR_FORBIDDEN,text='Not registered and registration is not supported')
        self.jabber.send(Presence(to=conn.fromjid, typ = 'error', frm = '%s%%%s@%s' %(conn.joinchan, conn.server, hostname)),error)
    
    def irc_mode(self,conn,event):
        #modelist = irclib.parse_channel_modes(event.arguments())
        faddr = '%s%%%s@%s' %(event.target().lower(),conn.server,hostname)
        if irclib.is_channel(event.target()):
            if event.arguments()[0] == '+o':
                # Give Chanop
                if irclib.irc_lower(event.target().lower()) in conn.memberlist.keys():
                    for each in event.arguments()[1:]:
                        conn.memberlist[event.target().lower()][each]['role']='moderator'
                        m = Presence(to=conn.fromjid,typ='available',frm = '%s/%s' %(faddr,each))
                        t = m.addChild(name='x',namespace='http://jabber.org/protocol/muc#user')
                        p = t.addChild(name='item',attrs=conn.memberlist[event.target().lower()][each])
                        self.jabber.send(m)
            elif event.arguments()[0] in ['-o', '-v']:
                # Take Chanop or Voice
                if irclib.irc_lower(event.target().lower()) in conn.memberlist.keys():
                    for each in event.arguments()[1:]:
                        conn.memberlist[event.target().lower()][each]['role']='visitor'
                        m = Presence(to=conn.fromjid,typ='available',frm = '%s/%s' %(faddr,each))
                        t = m.addChild(name='x',namespace='http://jabber.org/protocol/muc#user')
                        p = t.addChild(name='item',attrs=conn.memberlist[event.target().lower()][each])
                        self.jabber.send(m)
            elif event.arguments()[0] == '+v':
                # Give Voice
                if irclib.irc_lower(event.target().lower()) in conn.memberlist.keys():
                    for each in event.arguments()[1:]:
                        conn.memberlist[event.target().lower()][each]['role']='participant'
                        m = Presence(to=conn.fromjid,typ='available',frm = '%s/%s' %(faddr,each))
                        t = m.addChild(name='x',namespace='http://jabber.org/protocol/muc#user')
                        p = t.addChild(name='item',attrs=conn.memberlist[event.target().lower()][each])
                        self.jabber.send(m)
                    
    def irc_chanmode(self,conn,event):
        faddr = '%s%%%s@%s' %(event.target().lower(),conn.server,hostname)
        channel = event.target().lower()
        plus = None
        for each in event.arguments()[0]:
            if each == '+':
                plus = True
            elif each == '-':
                plus = False
            elif each == 'o': #Chanop status
                for each in event.arguments()[1:]:
                    conn.who(channel,each)
            elif each == 'v': #Voice status
                for each in event.arguments()[1:]:
                    conn.who(channel,each)
            elif each == 'p': #Private Room
                conn.chanmode[event.target()]['private'] = plus
            elif each == 's': #Secret
                conn.chanmode[event.target()]['secret'] = plus
            elif each == 'i': #invite only
                conn.chanmode[event.target()]['invite'] = plus
            elif each == 't': #only chanop can set topic
                conn.chanmode[event.target()]['topic'] = plus
            elif each == 'n': #no not in channel messages
                conn.chanmode[event.target()]['notmember'] = plus
            elif each == 'm': #moderated chanel
                conn.chanmode[event.target()]['moderated'] = plus
            elif each == 'l': #set channel limit
                conn.chanmode[event.target()]['private'] = event.arguments()[1]
            elif each == 'b': #ban users
                if plus:
                    conn.chanmode[event.target()]['banlist'].append(event.arguments()[1])
                else:
                    conn.chanmode[event.target()]['banlist'].remove(event.arguments()[1])
            elif each == 'k': #set channel key
                pass
    
    def irc_part(self,conn,event):
        type = 'unavailable'
        name = '%s%%%s' % (irclib.irc_lower(event.target()), conn.server)
        nick = irclib.nm_to_n(event.source())
        try:
            if nick in conn.memberlist[irclib.irc_lower(event.target())].keys():
                del conn.memberlist[irclib.irc_lower(event.target())][event.source().split('!')[0]]
        except KeyError:
            pass
        m = Presence(to=conn.fromjid,typ=type,frm='%s@%s/%s' %(name, hostname,event.source().split('!')[0]))
        self.jabber.send(m)
    
    def irc_kick(self,conn,event):
        type = 'unavailable'
        name = '%s%%%s' % (irclib.irc_lower(event.target()), conn.server)
        m = Presence(to=conn.fromjid,typ=type,frm='%s@%s/%s' %(name, hostname,irclib.irc_lower(event.arguments()[0])))
        t=m.addChild(name='x',namespace='http://jabber.org/protocol/muc#user')
        p=t.addChild(name='item',attrs={'affiliation':'none','role':'none'})
        p.addChild(name='reason',payload=[colourparse(event.arguments()[1])])
        t.addChild(name='status',attrs={'code':'307'})
        self.jabber.send(m)
        #print self.users[conn.fromjid]
        if event.arguments()[0] == conn.nickname:
            if conn.memberlist.has_key(irclib.irc_lower(event.target())):
                del conn.memberlist[irclib.irc_lower(event.target())]
        self.test_inuse(conn)
        
    def irc_topic(self,conn,event):
        nick = event.source().split('!')[0]
        channel = event.target().lower()
        if len(event.arguments())==2:
            line = colourparse(event.arguments()[1])
        else:
            line = colourparse(event.arguments()[0])
        m = Message(to=conn.fromjid,frm = '%s%%%s@%s/%s' % (event.arguments()[0].lower(),conn.server,hostname,nick), typ='groupchat', subject = line)
        self.jabber.send(m)
        
    def irc_join(self,conn,event):
        type = 'available'
        name = '%s%%%s' % (irclib.irc_lower(event.target()), conn.server)
        nick = irclib.nm_to_n(event.source())
        if nick not in conn.memberlist[irclib.irc_lower(event.target())].keys():
            conn.memberlist[irclib.irc_lower(event.target())][nick]={'affiliation':'none','role':'none'}
        m = Presence(to=conn.fromjid,typ=type,frm='%s@%s/%s' %(name, hostname, nick))
        t=m.addChild(name='x',namespace='http://jabber.org/protocol/muc#user')
        p=t.addChild(name='item',attrs={'affiliation':'none','role':'visitor'})
        #print m.__str__()
        self.jabber.send(m)
      
    def irc_whoreply(self,conn,event):
        name = '%s%%%s' % (event.arguments()[0].lower(), conn.server)
        faddr = '%s@%s/%s' % (name, hostname, event.arguments()[4])
        m = Presence(to=conn.fromjid,typ='available',frm=faddr)
        t = m.addChild(name='x', namespace='http://jabber.org/protocol/muc#user')
        affiliation = 'none'
        role = 'none'
        if '@' in event.arguments()[5]:
            role = 'moderator'
            #affiliation = 'admin' 
        elif '+' in event.arguments()[5]:
            role = 'participant'
            #affiliation = 'member'
        elif '*' in event.arguments()[5]:
            affiliation = 'admin'
        elif role == 'none':
            role = 'visitor'
            #affiliation = 'none'
        p=t.addChild(name='item',attrs={'affiliation':affiliation,'role':role})
        self.jabber.send(m)
        try:
            if (event.arguments()[0] != '*') and (event.arguments()[4] not in conn.memberlist[event.arguments()[0].lower()].keys()):
                conn.memberlist[event.arguments()[0].lower()][event.arguments()[4]]={'affiliation':affiliation,'role':role}
        except KeyError:
            pass
        #conn.mode(event.arguments()[4],'')
        #add mode request in here
        
    def irc_message(self,conn,event):
        try:
            nick = irclib.nm_to_n(event.source())
        except:
            nick = conn.server
        if irclib.is_channel(event.target()):
            type = 'groupchat'
            room = '%s%%%s' %(event.target().lower(),conn.server)
            m = Message(to=conn.fromjid,body=colourparse(event.arguments()[0].lower()),typ=type,frm='%s@%s/%s' %(room, hostname,nick))
        else:
            type = 'chat'
            name = event.source()
            name = '%s%%%s' %(nick,conn.server)
            m = Message(to=conn.fromjid,body=colourparse(event.arguments()[0].lower()),typ=type,frm='%s@%s' %(name, hostname))
        #print m.__str__()
        self.jabber.send(m)                     
     
    def irc_ctcp(self,conn,event):
        nick = irclib.nm_to_n(event.source())
        if event.arguments()[0] == 'ACTION':
            if irclib.is_channel(event.target()):
                type = 'groupchat'
                room = '%s%%%s' %(event.target().lower(),conn.server)
                
                m = Message(to=conn.fromjid,body='/me '+colourparse(event.arguments()[1]),typ=type,frm='%s@%s/%s' %(room, hostname,nick))
            else:
                type = 'chat'
                name = event.source()
                try:
                    name = '%s%%%s' %(nick,conn.server)
                except:
                    name = '%s%%%s' %(conn.server,conn.server)
                m = Message(to=conn.fromjid,body='/me '+colourparse(event.arguments()[1]),typ=type,frm='%s@%s' %(name, hostname))
            #print m.__str__()
            self.jabber.send(m) 
        elif event.arguments()[0] == 'VERSION':
            self.irc_sendctcp('VERSION',conn,event.source(),'xmpp IRC Transport')

if __name__ == '__main__':
    configfile = ConfigParser.ConfigParser()
    configfile.add_section('transport')
    try:
        cffile = open('transport.ini','r')
    except IOError:
        print "Transport requires configuration file, please supply"    
        sys.exit(1)
    configfile.readfp(cffile)
    server = configfile.get('transport','Server')
    #print server
    hostname = configfile.get('transport','Hostname')
    #print hostname
    port = int(configfile.get('transport','Port'))
    secret = configfile.get('transport','Secret')
    if configfile.has_option('transport','LocalAddress'):
        localaddress = configfile.get('transport','LocalAddress')
    if configfile.has_option('transport','Charset'):
        charset = configfile.get('transport','Charset')
    #connection = xmpp.client.Component(hostname,port)
    #connection.connect((server,port))
    #connection.auth(hostname,secret)
    while not connectxmpp():
        time.sleep(5)
    ircobj = irclib.IRC(fn_to_add_socket=irc_add_conn,fn_to_remove_socket=irc_del_conn)
    #socketlist[connection.Connection._sock]='xmpp'
    #jabber = ComponentThread(connection)
    #irc = IrcThread(ircobj)
    transport = Transport(connection,ircobj)
    while 1:
        (i , o, e) = select.select(socketlist.keys(),[],[],1)
        for each in i:
            if socketlist[each] == 'xmpp':
                #connection.Connection.receive()
                connection.Process(0)
            else:
                ircobj.process_data([each])
                