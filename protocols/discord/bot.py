from __future__ import annotations

import calendar
import operator
from functools import reduce
from typing import TYPE_CHECKING

from disco.bot import Plugin
from disco.gateway.events import GuildCreate, ChannelCreate, MessageCreate
from disco.types.channel import ChannelType
from disco.types.permissions import Permissions
from holster.emitter import Priority
from pylinkirc.classes import *

from util.formatter.discord import DiscordMessage
from util.formatter.irc import IrcMessage

if TYPE_CHECKING:
    from disco.types import Guild, Channel as DiscordChannel, GuildMember, Message
    from protocols.discord.protocol import DiscordServer

class DiscordBotPlugin(Plugin):
    subserver = {}
    irc_dicord_perm_mapping = {
        'voice': Permissions.SEND_MESSAGES.value,
        'halfop': Permissions.KICK_MEMBERS.value,
        'op': Permissions.BAN_MEMBERS.value,
        'admin': Permissions.ADMINISTRATOR.value
    }
    ALL_PERMS = reduce(operator.ior, Permissions.values_)
    botuser = None

    def __init__(self, protocol, bot, config):
        self.protocol = protocol
        super().__init__(bot, config)

    @Plugin.listen('Ready')
    def on_ready(self, event, *args, **kwargs):
        self.client.gw.ws.emitter.on('on_close', self.protocol.websocket_close, priority=Priority.BEFORE)
        self.botuser = str(event.user.id)

    @Plugin.listen('GuildCreate')
    def on_server_connect(self, event: GuildCreate, *args, **kwargs):
        server: Guild = event.guild
        pylink_netobj: 'DiscordServer' = self.protocol._create_child(server.name, server.id)
        pylink_netobj.uplink = server.id
        member: GuildMember
        for member_id, member in server.members.items():
            uid = str(member.id)
            user = User(pylink_netobj, member.user.username, calendar.timegm(member.joined_at.timetuple()), uid, str(server.id))
            user.discord_user = member
            pylink_netobj.users[uid] = user
            if uid == self.botuser:
                pylink_netobj.pseudoclient = user
            self.protocol._add_hook(
                server.name, [
                    server.id,
                    'UID',
                    {
                        'uid': uid,
                        'ts': user.ts,
                        'nick': user.nick,
                        'realhost': user.realhost,
                        'host': user.host,
                        'ident': user.ident,
                        'ip': user.ip
                    }])
            user.permissions = self.compute_base_permissions(member, server)

        channel: DiscordChannel
        for channel_id, channel in server.channels.items():
            if channel.type == ChannelType.GUILD_TEXT:
                namelist = []
                chandata = pylink_netobj.channels[str(channel)] = Channel(pylink_netobj, name=str(channel))
                channel_modes = set()
                for uid, user in pylink_netobj.users.items():
                    discord_user = server.members[int(uid)]
                    channel_permissions = self.compute_user_channel_perms(user.permissions, discord_user, channel)
                    if channel_permissions & Permissions.READ_MESSAGES.value == Permissions.READ_MESSAGES.value:
                        namelist.append(uid)
                        pylink_netobj.users[uid].channels.add(str(channel))
                        pylink_netobj.channels[str(channel)].users.add(uid)
                        for irc_mode, discord_permission in self.irc_dicord_perm_mapping.items():
                            if channel_permissions & discord_permission == discord_permission:
                                channel_modes.add(('+%s' % pylink_netobj.cmodes[irc_mode], uid))
                pylink_netobj.apply_modes(str(channel), channel_modes)
                chandata.discord_channel = channel
                self.protocol._add_hook(
                    server.name, [
                        server.id,
                        'JOIN',
                        {
                            'channel': str(channel),
                            'users': namelist,
                            'modes': [],
                            'ts': chandata.ts,
                            'channeldata': chandata
                        }])


        self.subserver[server.name] = pylink_netobj
        pylink_netobj.connected.set()
        self.protocol._add_hook(server.name, [server.id, 'ENDBURST', {}])

    @Plugin.listen('ChannelCreate')
    def on_channel_create(self, event: ChannelCreate, *args, **kwargs):
        pass

    def compute_base_permissions(self, member, guild):
        if guild.owner == member:
            return self.ALL_PERMS

        # get @everyone role
        role_everyone = guild.roles[guild.id]
        permissions = role_everyone.permissions.value

        for role in member.roles:
            permissions |= guild.roles[role].permissions.value

        if permissions & Permissions.ADMINISTRATOR.value == Permissions.ADMINISTRATOR.value:
            return self.ALL_PERMS

        return permissions

    def compute_user_channel_perms(self, base_permissions, member, channel):
        # ADMINISTRATOR overrides any potential permission overwrites, so there is nothing to do here.
        if base_permissions & Permissions.ADMINISTRATOR.value == Permissions.ADMINISTRATOR.value:
            return self.ALL_PERMS

        permissions = base_permissions
        # Find (@everyone) role overwrite and apply it.
        overwrite_everyone = channel.overwrites.get(channel.guild_id)
        if overwrite_everyone:
            permissions &= ~overwrite_everyone.deny.value
            permissions |= overwrite_everyone.allow.value

        # Apply role specific overwrites.
        overwrites = channel.overwrites
        allow = 0
        deny = 0
        for role_id in member.roles:
            overwrite_role = overwrites.get(role_id)
            if overwrite_role:
                allow |= overwrite_role.allow.value
                deny |= overwrite_role.deny.value

        permissions &= ~deny
        permissions |= allow

        # Apply member specific overwrite if it exist.
        overwrite_member = overwrites.get(member.id)
        if overwrite_member:
            permissions &= ~overwrite_member.deny
            permissions |= overwrite_member.allow

        return permissions

    @Plugin.listen('MessageCreate')
    def on_message(self, event: MessageCreate, *args, **kwargs):
        message: Message = event.message
        subserver = None
        target = None

        # If the bot is the one sending the message, don't do anything
        if str(message.author.id) == self.botuser or message.webhook_id:
            return

        if not message.guild:
            # This is a DM
            # see if we've seen this user on any of our servers
            for server in self.subserver.values():
                if str(message.author.id) in server.users:
                    target = self.botuser
                    subserver = server.name
                    server.users[str(message.author.id)].dm_channel = str(message.channel.id)
                    server.channels[str(message.channel)] = Channel(server, name=str(message.channel))
                    server.channels[str(message.channel)].discord_channel = message.channel

                    break
            if not (subserver or target):
                return
        else:
            subserver = message.guild.name
            target = message.channel

        # TODO: figure out a way to not have to convert the message here.
        # TODO: converting here makes it so if a message was being relayed to another discord server,
        # TODO: the message conversion would be Discord->IRC->Discord, which isn't optimal
        message_content = IrcMessage.unparse(DiscordMessage.parse(message.content))
        self.protocol._add_hook(
            subserver,
            [str(message.author.id), 'PRIVMSG', {'target': str(target), 'text': message_content}]
        )

