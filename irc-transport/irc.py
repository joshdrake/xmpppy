#!/usr/bin/python
#
# XMPPPY->IRC transport
# Jan 2004 Copyright (c) Mike Albon
#
# This program is free software licensed with the GNU Public License Version 2.
# For a full copy of the license please go here http://www.gnu.org/licenses/licenses.html#GPL

import xmpppy, urllib2, sys, string, time, irclib, re, ConfigParser, os
from threading import *
from xmpppy.protocol import *


#Global definitions
True = 1
False = 0
server = None
hostname = None
port = None
secret = None
localaddress = ""
connection = None
#server = '127.0.0.1'
#hostname = 'irc.localhost'
#port = 9000
#secret = 'secret'

def colourparse(str):
    s = ''
    for e in str:
        if e == '\x00':
            print 'Black'
        elif e == '\x01':
            print 'Blue'
        elif e == '\x02':
            print 'Green'
        elif e == '\x03':
            print 'Cyan'
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
        elif e == '\x10' or e == '\x11' or e == '\x12' or e == '\x13' or e == '\x14' or e == '\x15' or e == '\x16' or e == '\x17' or e == '\x18' or e == '\x19' or e == '\x1a' or e == '\x1b' or e == '\x1c' or e == '\x1d' or e == '\x1e' or e == '\x1f':
            print 'Other Escape'
        else:
            s = '%s%s'%(s,e)
        #try:
        #    s = s.encode('utf-8','replace')
        #except:
        s = s.encode('ascii','replace')
    return s
  
  
def connectxmpp():
    global connection
    connection = xmpppy.client.Component(hostname,port)
    while not connection.connect((server,port)):
        time.sleep(10)
    if connection.auth(hostname,secret):
        return True
    else:
        return False
        

class IrcThread(Thread):
    def __init__(self,irc):
        Thread.__init__(self)
        self.irc = irc
        self.start()
        
    def run(self):
        self.irc.process_forever()
    
class ComponentThread(Thread):
    def __init__(self,connection):
        Thread.__init__(self)
        self.connection = connection
        self.start()
        
    def run(self):
        while 1:
            self.connection.Process(5)
    
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
        self.irc.add_global_handler('error',self.irc_error)
        self.irc.add_global_handler('topic',self.irc_topic)
        self.irc.add_global_handler('nicknameinuse',self.irc_nicknameinuse)
        self.irc.add_global_handler('welcome',self.irc_welcome)
        self.jabber.RegisterHandler('message',self.xmpp_message)
        self.jabber.RegisterHandler('presence',self.xmpp_presence)
        self.jabber.RegisterHandler('iq',self.xmpp_iq_discoinfo,type = 'get', ns='http://jabber.org/protocol/disco#info')
        self.jabber.RegisterHandler('iq',self.xmpp_iq_discoitems,type = 'get', ns='http://jabber.org/protocol/disco#items')
        self.jabber.RegisterHandler('iq',self.xmpp_iq_version,type = 'get', ns='jabber:iq:version')
        self.jabber.RegisterHandler('iq',self.xmpp_iq_agents,type = 'get', ns='jabber:iq:agent')
        self.jabber.RegisterHandler('iq',self.xmpp_iq_browse,type = 'get', ns='jabber:iq:browse')
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
            channel, server = string.split(room,'%')
        except ValueError:
            m = xmpppy.protocol.Presence(to=event.getFrom(),frm=event.getTo(),type='error')
            m.setError('400','Invalid JID, must be in form #room%server@transport')
            self.jabber.send(m)
            return
        if not irclib.is_channel(channel):
            m = xmpppy.protocol.Presence(to=event.getFrom(),frm=event.getTo(),type='error')
            m.setError('400','Invalid JID, must be in form #room%server@transport')
            self.jabber.send(m)
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
            m = xmpppy.protocol.Presence(to=event.getFrom(), frm=event.getTo(),type='error')
            m.setError('502','Not Implemented')
            self.jabber.send(m)
            
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
        channel, server = string.split(room,'%')
        if not self.users.has_key(fromjid):
            m = xmpppy.protocol.Message(to=event.getFrom(), frm=event.getTo(), type = 'error', body=event.getBody())
            m.setError('500','Server not connected or invalid request')
            self.jabber.send(m)
            return
        if not self.users[fromjid].has_key(server):
            m = xmpppy.protocol.Message(to=event.getFrom(), frm=event.getTo(), type = 'error', body=event.getBody())
            m.setError('500','Server not connected')
            self.jabber.send(m)
            return
        #print channel, server, fromjid, self.users[fromjid][0][(channel,server)]
        if type == 'groupchat':
            if irclib.is_channel(channel):
                if (event.getSubject() != '') and (event.getSubject() != None):
                    self.irc_settopic(self.users[fromjid][server],channel,event.getSubject())
                elif event.getBody() != '':
                    if event.getBody()[0:3] == '/me':
                        self.irc_sendctcp('ACTION',self.users[fromjid][server],channel,event.getBody()[4:])
                    else:
                        self.irc_sendroom(self.users[fromjid][server],channel,event.getBody()) 
                    t = xmpppy.protocol.Message(to=fromjid,body=event.getBody(),type=type,frm='%s@%s/%s' %(room, hostname,self.users[fromjid][server].nickname))
                    self.jabber.send(t)
            else:
                #Add error case here
                pass
        elif type == 'chat' or type == None:
            if not irclib.is_channel(channel):
                # ARGH! need to know channel to find out nick. :(
                if event.getBody()[0:3] == '/me':
                    self.irc_sendctcp('ACTION',self.users[fromjiid][server],channel,event.getBody()[4:])
                else:
                    self.irc_sendroom(self.users[fromjid][server],channel,event.getBody())
            else:
                if event.getBody()[0:3] == '/me':
                    self.irc_sendctcp('ACTION',self.users[fromjid][server],channel,event.getBody()[4:])
                else:
                    self.irc_sendroom(self.users[fromjid][server],event.getFrom().getResource(),event.getBody())
                
    def xmpp_iq_discoinfo(self, con, event):
        fromjid = event.getFrom()
        to = event.getTo()
        id = event.getID()
        m = xmpppy.protocol.Iq(to=fromjid,frm=to, type='result', queryNS='http://jabber.org/protocol/disco#info', payload=[Node('identity',attrs={'category':'conference','type':'irc','name':'IRC Transport'}),Node('feature',attrs={'var':'http://jabber.org/protocol/muc'})])
        m.setID(id)
        self.jabber.send(m)
        
    def xmpp_iq_discoitems(self, con, event):
        fromjid = event.getFrom()
        to = event.getTo()
        id = event.getID()
        m = xmpppy.protocol.Iq(to=fromjid,frm=to, type='result', queryNS='http://jabber.org/protocol/disco#items')
        m.setID(id)
        self.jabber.send(m)
    
    def xmpp_iq_agents(self, con, event):
        m = xmpppy.protocol.Iq(to=event.getFrom(), frm=event.getTo(), type='result', payload=[Node('agent', attrs={'jid':hostname},payload=[Node('service',payload='irc'),Node('name',payload='XMPPPY IRC Transport'),Node('groupchat')])])
        m.setID(event.getID())
        self.jabber.send(m)
    
    def xmpp_iq_browse(self, con, event):
        m = xmpppy.protocol.Iq(to = event.getFrom(), frm = event.getTo(), type = 'result', queryNS = 'jabber:iq:browse')
        if event.getTo() == hostname:
            m.setTagAttr('query','catagory','conference')
            m.setTagAttr('query','name','XMPPPY IRC Transport')
            m.setTagAttr('query','type','irc')
            m.setTagAttr('query','jid','hostname')
            m.setPayload([Node('ns',payload='http://jabber.org/protcol/muc')])
        self.jabber.send(m)
    
    def xmpp_iq_version(self, con, event):
        fromjid = event.getFrom()
        to = event.getTo()
        id = event.getID()
        m = xmpppy.protocol.Iq(to = fromjid, frm = to, type = 'result', queryNS= 'jabber:iq:version',payload=[Node('name',payload='XMPPPY IRC Transport'), Node('version',payload='early release 12feb04'),Node('os',payload='%s %s %s' % (os.uname()[0],os.uname()[2],os.uname()[4]))])
        m.setID(id)
        self.jabber.send(m)
    
    def xmpp_disconnect(self):
        for each in self.users.keys():
            for item in self.users[each].keys():
                self.irc_doquit(item)
            del self.users[each]
        #del connection    
        while not connectxmpp():
            time.sleep(5)
            
    #IRC methods
    def irc_doquit(self,connection):
        server = connection.server
        nickname = connection.nickname
        del self.users[connection.fromjid][server]
        connection.quit()
        
    def irc_settopic(self,connection,channel,line):
        connection.topic(channel,line)
    
    def irc_sendroom(self,connection,channel,line):
        lines = string.split(line, '/n')
        for each in lines:
            #print channel, each
            connection.privmsg(channel,each)

    def irc_sendctcp(self,type,connection,channel,line):
        lines = string.split(line, '/n')
        for each in lines:
            #print channel, each
            connection.ctcp(type,channel,each)

    def irc_newconn(self,channel,server,nick,fromjid):
        try:
            c=self.irc.server().connect(server,6667,nick,localaddress=localaddress)
            c.fromjid = fromjid
            c.joinchan = channel
            c.memberlist = {}
            #c.join(channel)
            #c.who(channel) 
            return c
        except irclib.ServerConnectionError:
            m = xmpppy.protocol.Presence(to = fromjid, type = 'error', frm = '%s%%%s@%s/%s' % (channel,server,hostname,nick))
            m.setError('404','Could not connect to irc server')
            self.jabber.send(m)
            return None
            
    def irc_newroom(self,conn,channel):
        conn.join(channel)
        conn.who(channel)
        conn.topic(channel)
        conn.memberlist[channel] = {}

    def irc_leaveroom(self,conn,channel):
        conn.part([channel])
    
    # IRC message handlers

    def irc_error(self,conn,event):
        if conn.server in self.users[conn.fromjid].keys():
            try:
                for each in self.memberlist.keys():
                    t = xmpppy.protocol.Presence(to=conn.fromjid, type = 'unavailable', frm='%s%%%s@%s' %(each,conn.server,hostname))
                    self.jabber.send(t)
                del self.users[conn.fromjid][conn.server]
            except AttributeError:
                pass    
    
    def irc_quit(self,conn,event):
        type = 'unavailable'
        for each in conn.memberlist.keys():
            if string.split(event.source(),'!')[0] in conn.memberlist[each].keys():
                del conn.memberlist[each][string.split(event.source(),'!')[0]]
                name = '%s%%%s' % (each, conn.server)
                m = xmpppy.protocol.Presence(to=conn.fromjid,type=type,frm='%s@%s/%s' %(name, hostname,string.split(event.source(),'!')[0]))
                self.jabber.send(m)
    
    def irc_nick(self, conn, event):
        old = string.split(event.source(),'!')[0]
        new = event.target()
        for each in self.memberlist.keys():
            if old in self.memberlist[each].keys():
                m = xmpppy.protocol.Presence(to=conn.fromjid,type = 'unavailable',frm = '%s%%%s@%s/%s' % (each,conn.server,hostname,old))
                p = m.addChild(name='x', namespace='http://jabber.org/protocol/muc#user')
                p.addChild(name='item', attrs={'nick':new})
                p.addChild(name='status', attrs={'code':'303'})
                self.jabber.send(m)
                m = xmpppy.protocol.Presence(to=conn.fromjid,type = 'available', frm = '%s%%%s@%s/%s' % (each,conn.server,hostname,new))
                self.jabber.send(m)
                t=self.memberlist[each][old]
                del self.memberlist[each][old]
                self.memberlist[each][new] = t
                

    def irc_welcome(self,conn,event):
        self.irc_newroom(conn,conn.joinchan)
        del conn.joinchan
    
    def irc_nicknameinuse(self,conn,event):
        if conn.joinchan:
            m = xmpppy.protocol.Presence(to=conn.fromjid, type = 'error', frm = '%s%%%s@%s' %(conn.joinchan, conn.server, hostname))
            m.setError('409','The nickname is in use')
            self.jabber.send(m)
    
    def irc_mode(self,conn,event):
        modelist = irclib.parse_channel_modes(event.arguments())
    
    def irc_part(self,conn,event):
        type = 'unavailable'
        name = '%s%%%s' % (event.target().lower(), conn.server)
        try:
            if string.split(event.source(),'!')[0] in conn.memberlist[event.target().lower()].keys():
                del conn.memberlist[event.target().lower()][string.split(event.source(),'!')[0]]
        except KeyError:
            pass
        m = xmpppy.protocol.Presence(to=conn.fromjid,type=type,frm='%s@%s/%s' %(name, hostname,string.split(event.source(),'!')[0]))
        self.jabber.send(m)
    
    def irc_kick(self,conn,event):
        type = 'unavailable'
        name = '%s%%%s' % (event.target().lower(), conn.server)
        m = xmpppy.protocol.Presence(to=conn.fromjid,type=type,frm='%s@%s/%s' %(name, hostname,event.arguments()[0]))
        if event.arguments()[0] == conn.nickname:
            t=m.addChild(name='x',namespace='http://jabber.org/protocol/muc#user')
            p=t.addChild(name='item',attrs={'affiliation':'none','role':'none'})
            p.addChild(name='reason',payload=[event.arguments()[1]])
            t.addChild(name='status',attrs={'code':'307'})
        self.jabber.send(m)
        #print self.users[conn.fromjid]
        if self.memberlist.has_key(event.target().lower()):
            del self.memberlist[event.target().lower()]
        self.test_inuse(conn)
        
    def irc_topic(self,conn,event):
        nick = string.split(event.source(),'!')[0]
        channel = event.target().lower()
        line = colourparse(event.arguments()[1]).encode('utf-8','replace')
        m = xmpppy.protocol.Message(to=conn.fromjid,frm = '%s%%%s@%s/%s' % (event.arguments()[0],conn.server,hostname,nick), type='groupchat', subject = line)
        self.jabber.send(m)
        
    def irc_join(self,conn,event):
        type = 'available'
        name = '%s%%%s' % (event.target().lower(), conn.server)
        if string.split(event.source(),'!')[0] not in conn.memberlist[event.target().lower()].keys():
            conn.memberlist[event.target().lower()][string.split(event.source(),'!')[0]]={'affiliation':'none','role':'none'}
        m = xmpppy.protocol.Presence(to=conn.fromjid,type=type,frm='%s@%s/%s' %(name, hostname,string.split(event.source(),'!')[0]))
        t=m.addChild(name='x',namespace='http://jabber.org/protocol/muc#user')
        p=t.addChild(name='item',attrs={'affiliation':'none','role':'visitor'})
        #print m.__str__()
        self.jabber.send(m)
      
    def irc_whoreply(self,conn,event):
        name = '%s%%%s' % (event.arguments()[0], conn.server)
        faddr = '%s@%s/%s' % (name, hostname, event.arguments()[4])
        m = xmpppy.protocol.Presence(to=conn.fromjid,type='available',frm=faddr)
        t = m.addChild(name='x', namespace='http://jabber.org/protocol/muc#user')
        if '@' in event.arguments()[5]:
            role = 'moderator'
            affiliation = 'admin' 
        elif '+' in event.arguments()[5]:
            role = 'participant'
            affiliation = 'member'
        else:
            role = 'visitor'
            affiliation = 'none'
        p=t.addChild(name='item',attrs={'affiliation':affiliation,'role':role})
        self.jabber.send(m)
        if (event.arguments()[0] != '*') and (event.arguments()[4] not in conn.memberlist[event.arguments()[0]].keys()):
            conn.memberlist[event.arguments()[0]][event.arguments()[4]]={'affiliation':affiliation,'role':role}
        #conn.mode(event.arguments()[4],'')
        #add mode request in here
        
    def irc_message(self,conn,event):
        if irclib.is_channel(event.target()):
            type = 'groupchat'
            room = '%s%%%s' %(event.target().lower(),conn.server)
            m = xmpppy.protocol.Message(to=conn.fromjid,body=colourparse(event.arguments()[0]).encode('utf-8','replace'),type=type,frm='%s@%s/%s' %(room, hostname,string.split(event.source(),'!')[0]))
        else:
            type = 'chat'
            name = event.source()
            try:
                name = '%s%%%s' %(string.split(event.source(),'!')[0],conn.server)
            except:
                name = '%s%%%s' %(conn.server,conn.server)
            m = xmpppy.protocol.Message(to=conn.fromjid,body=colourparse(event.arguments()[0]).encode('utf-8','replace'),type=type,frm='%s@%s' %(name, hostname))
        #print m.__str__()
        self.jabber.send(m)                     
     
    def irc_ctcp(self,conn,event):
        if event.arguments()[0] == 'ACTION':
            if irclib.is_channel(event.target()):
                type = 'groupchat'
                room = '%s%%%s' %(event.target().lower(),conn.server)
                m = xmpppy.protocol.Message(to=conn.fromjid,body='/me '+colourparse(event.arguments()[1]).encode('utf-8','replace'),type=type,frm='%s@%s/%s' %(room, hostname,string.split(event.source(),'!')[0]))
            else:
                type = 'chat'
                name = event.source()
                try:
                    name = '%s%%%s' %(string.split(event.source(),'!')[0],conn.server)
                except:
                    name = '%s%%%s' %(conn.server,conn.server)
                m = xmpppy.protocol.Message(to=conn.fromjid,body='/me '+colourparse(event.arguments()[1]).encode('utf-8','replace'),type=type,frm='%s@%s' %(name, hostname))
            #print m.__str__()
            self.jabber.send(m) 
        elif event.arguments()[0] == 'VERSION':
            self.irc_sendctcp('VERSION',conn,event.source(),'XMPPPY IRC Transport')

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
    #connection = xmpppy.client.Component(hostname,port)
    #connection.connect((server,port))
    #connection.auth(hostname,secret)
    while not connectxmpp():
        time.sleep(5)
    ircobj = irclib.IRC()
    jabber = ComponentThread(connection)
    irc = IrcThread(ircobj)
    transport = Transport(connection,ircobj)
